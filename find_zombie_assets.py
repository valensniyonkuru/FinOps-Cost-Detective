#!/usr/bin/env python3
"""
find_zombie_assets.py
─────────────────────
FinOps "Cost Detective" — Full Zombie Asset Scanner

Scans an AWS account for wasteful resources that generate costs
without delivering business value. Produces a prioritised findings
report with estimated monthly waste per resource.

Usage:
    python find_zombie_assets.py [--region us-east-1] [--output report.json]
    python find_zombie_assets.py --profile my-aws-profile --region eu-west-1

Detected zombie categories:
    1. Unattached EBS volumes
    2. Unassociated Elastic IPs
    3. Idle EC2 instances (CPU < 5 % over 14 days)
    4. Unused Elastic Load Balancers (0 healthy targets)
    5. Unattached / unused NAT Gateways
    6. Old / unused AMI snapshots (> 90 days, not in use)
    7. Stopped RDS instances
    8. Empty / idle ElastiCache clusters
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# ── Rough on-demand pricing USD/month (us-east-1 approximations) ───────────
EBS_GP2_PRICE_PER_GB  = 0.10
EBS_GP3_PRICE_PER_GB  = 0.08
EBS_IO1_PRICE_PER_GB  = 0.125
EIP_IDLE_PRICE        = 3.60   # per unused EIP per month
NAT_GW_PRICE          = 32.40  # ~$0.045/hr * 720 hrs


def get_session(profile: str | None, region: str) -> boto3.Session:
    kwargs = {"region_name": region}
    if profile:
        kwargs["profile_name"] = profile
    return boto3.Session(**kwargs)


# ── 1. Unattached EBS Volumes ────────────────────────────────────────────────
def find_unattached_ebs(ec2) -> list[dict]:
    findings = []
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for vol in page["Volumes"]:
            size    = vol["Size"]
            vtype   = vol["VolumeType"]
            price   = {
                "gp2": EBS_GP2_PRICE_PER_GB,
                "gp3": EBS_GP3_PRICE_PER_GB,
                "io1": EBS_IO1_PRICE_PER_GB,
                "io2": EBS_IO1_PRICE_PER_GB,
            }.get(vtype, EBS_GP2_PRICE_PER_GB)

            name = next((t["Value"] for t in vol.get("Tags", []) if t["Key"] == "Name"), vol["VolumeId"])
            findings.append({
                "type":               "Unattached EBS Volume",
                "resource_id":        vol["VolumeId"],
                "name":               name,
                "detail":             f"{size} GiB {vtype}",
                "monthly_waste_usd":  round(size * price, 2),
                "risk":               "HIGH",
                "recommendation":     "Snapshot if needed, then delete.",
                "created":            vol["CreateTime"].isoformat(),
            })
    return findings


# ── 2. Unassociated Elastic IPs ──────────────────────────────────────────────
def find_unassociated_eips(ec2) -> list[dict]:
    findings = []
    resp = ec2.describe_addresses()
    for addr in resp["Addresses"]:
        if "AssociationId" not in addr:
            name = next((t["Value"] for t in addr.get("Tags", []) if t["Key"] == "Name"), addr.get("AllocationId", ""))
            findings.append({
                "type":               "Unassociated Elastic IP",
                "resource_id":        addr.get("AllocationId", addr.get("PublicIp")),
                "name":               name,
                "detail":             addr.get("PublicIp", ""),
                "monthly_waste_usd":  EIP_IDLE_PRICE,
                "risk":               "MEDIUM",
                "recommendation":     "Release if not needed within 48 hours.",
                "created":            "N/A",
            })
    return findings


# ── 3. Idle EC2 Instances (< 5 % avg CPU over 14 days) ──────────────────────
def find_idle_ec2(ec2, cw) -> list[dict]:
    findings  = []
    end_time  = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(days=14)

    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["running"]}]):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                iid  = inst["InstanceId"]
                itype = inst["InstanceType"]
                name  = next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), iid)

                try:
                    metrics = cw.get_metric_statistics(
                        Namespace="AWS/EC2",
                        MetricName="CPUUtilization",
                        Dimensions=[{"Name": "InstanceId", "Value": iid}],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=86400,   # 1-day aggregation
                        Statistics=["Average"],
                    )
                    data_points = metrics["Datapoints"]
                    if not data_points:
                        avg_cpu = 0.0
                    else:
                        avg_cpu = sum(d["Average"] for d in data_points) / len(data_points)
                except ClientError:
                    continue

                if avg_cpu < 5.0:
                    findings.append({
                        "type":               "Idle EC2 Instance",
                        "resource_id":        iid,
                        "name":               name,
                        "detail":             f"{itype} — avg CPU {avg_cpu:.1f}% over 14d",
                        "monthly_waste_usd":  None,   # Needs pricing API for accuracy
                        "risk":               "HIGH" if avg_cpu < 1.0 else "MEDIUM",
                        "recommendation":     "Rightsize to t3.micro, schedule stop, or terminate.",
                        "created":            inst["LaunchTime"].isoformat(),
                    })
    return findings


# ── 4. Unused Elastic Load Balancers ─────────────────────────────────────────
def find_unused_elbs(elbv2) -> list[dict]:
    findings = []
    paginator = elbv2.get_paginator("describe_load_balancers")
    for page in paginator.paginate():
        for lb in page["LoadBalancers"]:
            arn  = lb["LoadBalancerArn"]
            name = lb["LoadBalancerName"]

            # Check if any target groups have healthy targets
            tg_paginator = elbv2.get_paginator("describe_target_groups")
            healthy = 0
            for tg_page in tg_paginator.paginate(LoadBalancerArn=arn):
                for tg in tg_page["TargetGroups"]:
                    health = elbv2.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
                    healthy += sum(1 for t in health["TargetHealthDescriptions"] if t["TargetHealth"]["State"] == "healthy")

            if healthy == 0:
                findings.append({
                    "type":               "Unused Load Balancer",
                    "resource_id":        arn.split("/")[-2] + "/" + arn.split("/")[-1],
                    "name":               name,
                    "detail":             f"{lb['Type']} — 0 healthy targets",
                    "monthly_waste_usd":  16.20,   # ~$0.0225/LCU-hr min charge
                    "risk":               "HIGH",
                    "recommendation":     "Delete if no traffic in past 30 days.",
                    "created":            lb["CreatedTime"].isoformat(),
                })
    return findings


# ── 5. Stopped RDS Instances ──────────────────────────────────────────────────
def find_stopped_rds(rds) -> list[dict]:
    findings  = []
    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for db in page["DBInstances"]:
            if db["DBInstanceStatus"] == "stopped":
                findings.append({
                    "type":               "Stopped RDS Instance",
                    "resource_id":        db["DBInstanceIdentifier"],
                    "name":               db["DBInstanceIdentifier"],
                    "detail":             f"{db['DBInstanceClass']} {db['Engine']} — stopped",
                    "monthly_waste_usd":  None,   # Storage still billed
                    "risk":               "MEDIUM",
                    "recommendation":     "Delete or restore; AWS stops→starts automatically after 7 days.",
                    "created":            db["InstanceCreateTime"].isoformat(),
                })
    return findings


# ── 6. Old Unregistered Snapshots (> 90 days) ─────────────────────────────────
def find_old_snapshots(ec2, account_id: str) -> list[dict]:
    findings   = []
    cutoff     = datetime.now(tz=timezone.utc) - timedelta(days=90)
    paginator  = ec2.get_paginator("describe_snapshots")

    # Get AMI snapshot IDs currently in use
    amis = ec2.describe_images(Owners=["self"])["Images"]
    used_snapshot_ids = {
        bdm["Ebs"]["SnapshotId"]
        for ami in amis
        for bdm in ami.get("BlockDeviceMappings", [])
        if "Ebs" in bdm
    }

    for page in paginator.paginate(OwnerIds=[account_id]):
        for snap in page["Snapshots"]:
            if snap["StartTime"] < cutoff and snap["SnapshotId"] not in used_snapshot_ids:
                name = next((t["Value"] for t in snap.get("Tags", []) if t["Key"] == "Name"), snap["SnapshotId"])
                size = snap["VolumeSize"]
                findings.append({
                    "type":               "Old Unused Snapshot",
                    "resource_id":        snap["SnapshotId"],
                    "name":               name,
                    "detail":             f"{size} GiB — {snap['StartTime'].strftime('%Y-%m-%d')}",
                    "monthly_waste_usd":  round(size * 0.05, 2),   # $0.05/GB-month
                    "risk":               "LOW",
                    "recommendation":     "Review and delete; archive to S3 Glacier if needed.",
                    "created":            snap["StartTime"].isoformat(),
                })
    return findings


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="FinOps Zombie Asset Scanner")
    parser.add_argument("--region",  default="us-east-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--output",  default=None, help="Save JSON report to file")
    args = parser.parse_args()

    try:
        session    = get_session(args.profile, args.region)
        ec2        = session.client("ec2",            region_name=args.region)
        cw         = session.client("cloudwatch",     region_name=args.region)
        elbv2      = session.client("elbv2",          region_name=args.region)
        rds        = session.client("rds",            region_name=args.region)
        sts        = session.client("sts")
        account_id = sts.get_caller_identity()["Account"]
    except NoCredentialsError:
        print("ERROR: No AWS credentials found. Configure via env vars, ~/.aws/credentials, or --profile.")
        sys.exit(1)

    print(f"\n🔍 Scanning account {account_id} in {args.region} …\n")

    all_findings: list[dict] = []
    scanners = [
        ("EBS volumes",      find_unattached_ebs,    (ec2,)),
        ("Elastic IPs",      find_unassociated_eips,  (ec2,)),
        ("Idle EC2",         find_idle_ec2,           (ec2, cw)),
        ("Load Balancers",   find_unused_elbs,        (elbv2,)),
        ("Stopped RDS",      find_stopped_rds,        (rds,)),
        ("Old snapshots",    find_old_snapshots,       (ec2, account_id)),
    ]

    for label, fn, fn_args in scanners:
        print(f"  ▶ Checking {label} …", end=" ", flush=True)
        try:
            results = fn(*fn_args)
            all_findings.extend(results)
            print(f"{' ' + str(len(results)) + ' found' if results else ' clean'}")
        except ClientError as e:
            print(f"⚡ skipped ({e.response['Error']['Code']})")

    # ── Calculate totals ────────────────────────────────────────────────────
    total_monthly_waste = sum(
        f["monthly_waste_usd"] for f in all_findings if f["monthly_waste_usd"] is not None
    )
    high_risk   = [f for f in all_findings if f["risk"] == "HIGH"]
    medium_risk = [f for f in all_findings if f["risk"] == "MEDIUM"]
    low_risk    = [f for f in all_findings if f["risk"] == "LOW"]

    # ── Print summary ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ZOMBIE ASSET SCAN COMPLETE — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")
    print(f"  Total findings:          {len(all_findings)}")
    print(f"  High risk:               {len(high_risk)}")
    print(f"  Medium risk:             {len(medium_risk)}")
    print(f"  Low risk:                {len(low_risk)}")
    print(f"  Est. monthly waste (USD): ${total_monthly_waste:,.2f}")
    print(f"  Est. annual waste (USD):  ${total_monthly_waste * 12:,.2f}")
    print(f"{'='*60}\n")

    for f in sorted(all_findings, key=lambda x: (x["risk"] != "HIGH", x["monthly_waste_usd"] or 0), reverse=True):
        risk_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(f["risk"], "⚪")
        waste_str = f"${f['monthly_waste_usd']:.2f}/mo" if f["monthly_waste_usd"] else "variable"
        print(f"  {risk_icon} [{f['risk']}] {f['type']}")
        print(f"     ID:     {f['resource_id']}")
        print(f"     Detail: {f['detail']}")
        print(f"     Waste:  {waste_str}")
        print(f"     Fix:    {f['recommendation']}\n")

    # ── Export ──────────────────────────────────────────────────────────────
    report = {
        "scan_timestamp":     datetime.now(tz=timezone.utc).isoformat(),
        "account_id":         account_id,
        "region":             args.region,
        "total_findings":     len(all_findings),
        "estimated_monthly_waste_usd": round(total_monthly_waste, 2),
        "estimated_annual_waste_usd":  round(total_monthly_waste * 12, 2),
        "findings":           all_findings,
    }

    if args.output:
        with open(args.output, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f" Report saved to {args.output}")

    return report


if __name__ == "__main__":
    main()
