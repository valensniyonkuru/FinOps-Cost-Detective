#!/usr/bin/env python3
"""
gc_ebs_volumes.py
─────────────────
FinOps "Cost Detective" — Unattached EBS Garbage Collector

Safely identifies and (optionally) deletes all EBS volumes in
"available" (unattached) state. Follows a two-phase approach:

  Phase 1 — SCAN (default):  list all zombie volumes, estimate waste
  Phase 2 — COLLECT (--execute): snapshot each volume, then delete

Safety features:
  • Dry-run by default — add --execute to actually delete
  • Creates a snapshot of each volume before deletion
  • Skips volumes tagged with  finops:keep = true
  • Writes a JSON audit trail of every action taken
  • Confirms before deleting volumes > 100 GiB

Usage:
    # List only (safe, no changes)
    python gc_ebs_volumes.py

    # List and delete (requires explicit flag)
    python gc_ebs_volumes.py --execute

    # Specific region, save audit log
    python gc_ebs_volumes.py --execute --region eu-west-1 --audit-log gc_audit.json

    # Skip snapshot creation (faster, less safe)
    python gc_ebs_volumes.py --execute --no-snapshot
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# ── Pricing (us-east-1 approximations) ──────────────────────────────────────
PRICE_PER_GB = {"gp2": 0.10, "gp3": 0.08, "io1": 0.125, "io2": 0.125, "st1": 0.045, "sc1": 0.025}
SNAPSHOT_PRICE_PER_GB = 0.05   # Standard snapshot storage


def estimate_monthly_cost(size_gb: int, volume_type: str) -> float:
    return size_gb * PRICE_PER_GB.get(volume_type, 0.10)


def get_tag(tags: list, key: str, default: str = "") -> str:
    return next((t["Value"] for t in (tags or []) if t["Key"] == key), default)


def scan_unattached_volumes(ec2) -> list[dict]:
    """Return list of unattached EBS volumes with metadata."""
    volumes = []
    paginator = ec2.get_paginator("describe_volumes")

    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for v in page["Volumes"]:
            tags     = v.get("Tags", [])
            keep_tag = get_tag(tags, "finops:keep", "false").lower()
            volumes.append({
                "VolumeId":   v["VolumeId"],
                "Size":       v["Size"],
                "VolumeType": v["VolumeType"],
                "AZ":         v["AvailabilityZone"],
                "CreateTime": v["CreateTime"],
                "Name":       get_tag(tags, "Name", v["VolumeId"]),
                "CostCenter": get_tag(tags, "CostCenter", "UNTAGGED"),
                "KeepTag":    keep_tag == "true",
                "MonthlyCost": estimate_monthly_cost(v["Size"], v["VolumeType"]),
                "Tags":       tags,
            })
    return volumes


def create_snapshot(ec2, volume_id: str, volume_name: str) -> str | None:
    """Snapshot a volume before deletion. Returns snapshot ID or None."""
    desc = f"gc-pre-delete-{volume_id}-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    try:
        snap = ec2.create_snapshot(
            VolumeId=volume_id,
            Description=desc,
            TagSpecifications=[{
                "ResourceType": "snapshot",
                "Tags": [
                    {"Key": "Name",             "Value": f"gc-{volume_name}"},
                    {"Key": "gc:source-volume",  "Value": volume_id},
                    {"Key": "gc:created-by",     "Value": "gc_ebs_volumes.py"},
                    {"Key": "gc:timestamp",      "Value": datetime.now(tz=timezone.utc).isoformat()},
                    {"Key": "finops:keep",       "Value": "false"},   # Snapshot itself is disposable
                ],
            }],
        )
        snap_id = snap["SnapshotId"]
        print(f"      📸 Snapshot {snap_id} created … waiting for completion")

        # Wait for snapshot to reach 'completed' state
        waiter = ec2.get_waiter("snapshot_completed")
        waiter.wait(
            SnapshotIds=[snap_id],
            WaiterConfig={"Delay": 15, "MaxAttempts": 40},
        )
        print(f"      ✅ Snapshot {snap_id} complete")
        return snap_id
    except ClientError as e:
        print(f"      ❌ Snapshot failed: {e.response['Error']['Message']}")
        return None


def delete_volume(ec2, volume_id: str) -> bool:
    """Delete an EBS volume. Returns True on success."""
    try:
        ec2.delete_volume(VolumeId=volume_id)
        return True
    except ClientError as e:
        print(f"      ❌ Delete failed: {e.response['Error']['Message']}")
        return False


def main():
    parser = argparse.ArgumentParser(description="EBS Garbage Collector")
    parser.add_argument("--region",    default="us-east-1")
    parser.add_argument("--profile",   default=None)
    parser.add_argument("--execute",   action="store_true", help="Actually delete volumes (default is dry-run)")
    parser.add_argument("--no-snapshot", action="store_true", help="Skip snapshot creation before deletion")
    parser.add_argument("--audit-log", default=None, help="Path to write JSON audit log")
    args = parser.parse_args()

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  EBS GARBAGE COLLECTOR  —  Mode: {mode}")
    print(f"  Region: {args.region}")
    print(f"{'='*60}\n")

    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        ec2     = session.client("ec2", region_name=args.region)
        sts     = session.client("sts")
        account_id = sts.get_caller_identity()["Account"]
    except NoCredentialsError:
        print("ERROR: No AWS credentials configured.")
        sys.exit(1)

    print(f"Account: {account_id}\n")
    print("🔍 Scanning for unattached EBS volumes …\n")

    volumes = scan_unattached_volumes(ec2)

    if not volumes:
        print("✅ No unattached EBS volumes found. Account is clean!\n")
        sys.exit(0)

    # ── Print inventory ──────────────────────────────────────────────────────
    total_waste = sum(v["MonthlyCost"] for v in volumes)
    keep_count  = sum(1 for v in volumes if v["KeepTag"])
    gc_targets  = [v for v in volumes if not v["KeepTag"]]

    print(f"Found {len(volumes)} unattached volume(s)  |  {keep_count} protected (finops:keep=true)  |  {len(gc_targets)} eligible for GC")
    print(f"Estimated monthly waste: ${total_waste:,.2f} USD\n")

    header = f"{'VolumeId':<24} {'Name':<30} {'Size':>6} {'Type':<6} {'$/mo':>7}  {'Keep'}"
    print(header)
    print("─" * len(header))
    for v in sorted(volumes, key=lambda x: x["MonthlyCost"], reverse=True):
        flag = "🔒 KEEP" if v["KeepTag"] else "🗑  GC"
        print(f"{v['VolumeId']:<24} {v['Name'][:30]:<30} {v['Size']:>5}G {v['VolumeType']:<6} ${v['MonthlyCost']:>6.2f}  {flag}")

    print()

    # ── Dry-run exit ─────────────────────────────────────────────────────────
    if not args.execute:
        print("ℹ️  DRY-RUN: No volumes were modified.")
        print("   Re-run with --execute to proceed with deletion.\n")

        report = {
            "mode":         "dry-run",
            "timestamp":    datetime.now(tz=timezone.utc).isoformat(),
            "account_id":   account_id,
            "region":       args.region,
            "total_found":  len(volumes),
            "gc_eligible":  len(gc_targets),
            "estimated_monthly_savings_usd": round(sum(v["MonthlyCost"] for v in gc_targets), 2),
            "volumes":      [{k: str(v) if not isinstance(v, (str, int, float, bool)) else v for k, v in vol.items() if k != "Tags"} for vol in volumes],
        }
        if args.audit_log:
            with open(args.audit_log, "w") as fh:
                json.dump(report, fh, indent=2, default=str)
            print(f"📄 Audit log: {args.audit_log}")
        return

    # ── Execute: Snapshot + Delete ───────────────────────────────────────────
    audit_log = []
    deleted_count  = 0
    skipped_count  = 0
    total_saved    = 0.0

    for v in gc_targets:
        print(f"\n🗑  Processing {v['VolumeId']} ({v['Name']}) — {v['Size']} GiB {v['VolumeType']}")

        # Warn on large volumes
        if v["Size"] > 100:
            confirm = input(f"   ⚠️  Volume is {v['Size']} GiB. Type 'yes' to continue: ").strip().lower()
            if confirm != "yes":
                print("   ⏭  Skipped by user.")
                audit_log.append({"volume_id": v["VolumeId"], "action": "skipped_user", "reason": "user_declined"})
                skipped_count += 1
                continue

        # Snapshot
        snapshot_id = None
        if not args.no_snapshot:
            snapshot_id = create_snapshot(ec2, v["VolumeId"], v["Name"])
            if snapshot_id is None:
                print("   ⏭  Skipping deletion (snapshot failed).")
                audit_log.append({"volume_id": v["VolumeId"], "action": "skipped_snapshot_failed"})
                skipped_count += 1
                continue

        # Delete
        success = delete_volume(ec2, v["VolumeId"])
        if success:
            print(f"      🗑  Volume {v['VolumeId']} deleted — saving ${v['MonthlyCost']:.2f}/mo")
            deleted_count += 1
            total_saved   += v["MonthlyCost"]
            audit_log.append({
                "volume_id":   v["VolumeId"],
                "name":        v["Name"],
                "size_gb":     v["Size"],
                "action":      "deleted",
                "snapshot_id": snapshot_id,
                "monthly_savings_usd": round(v["MonthlyCost"], 2),
                "timestamp":   datetime.now(tz=timezone.utc).isoformat(),
            })
        else:
            skipped_count += 1
            audit_log.append({"volume_id": v["VolumeId"], "action": "delete_failed"})

        time.sleep(0.5)   # Brief pause between API calls

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  GC COMPLETE")
    print(f"  Deleted:  {deleted_count} volumes")
    print(f"  Skipped:  {skipped_count} volumes")
    print(f"  Savings:  ${total_saved:,.2f}/mo  (${total_saved * 12:,.2f}/yr)")
    print(f"{'='*60}\n")

    report = {
        "mode":          "execute",
        "timestamp":     datetime.now(tz=timezone.utc).isoformat(),
        "account_id":    account_id,
        "region":        args.region,
        "deleted_count": deleted_count,
        "skipped_count": skipped_count,
        "monthly_savings_usd": round(total_saved, 2),
        "annual_savings_usd":  round(total_saved * 12, 2),
        "actions":       audit_log,
    }

    if args.audit_log:
        with open(args.audit_log, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"📄 Audit log: {args.audit_log}")


if __name__ == "__main__":
    main()
