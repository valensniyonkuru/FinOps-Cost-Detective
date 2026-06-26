#!/usr/bin/env python3
"""
generate_cost_report.py
───────────────────────
FinOps "Cost Detective" — AWS Cost Explorer Report Generator

Produces a formatted FinOps cost report covering:
  • Month-to-date spend by service (top 10)
  • Month-over-month trend (last 3 months)
  • Daily spend for current month
  • Cost breakdown by tag:CostCenter
  • Untagged resource spend estimate
  • Forecast for current month
  • Recommended actions with estimated savings

Output formats: console (default), JSON, Markdown

Usage:
    python generate_cost_report.py
    python generate_cost_report.py --format markdown --output report.md
    python generate_cost_report.py --months 6 --format json
"""

import argparse
import json
import sys
from datetime import datetime, date, timedelta
from calendar import monthrange

import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def date_range_mtd() -> tuple[str, str]:
    """Current month start to today."""
    today = date.today()
    return today.strftime("%Y-%m-01"), today.strftime("%Y-%m-%d")


def date_range_last_n_months(n: int) -> tuple[str, str]:
    """Start of n months ago to start of current month."""
    today = date.today()
    start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    for _ in range(n - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    end = today.replace(day=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def get_service_breakdown(ce, start: str, end: str) -> list[dict]:
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    results = []
    for group in resp["ResultsByTime"][0]["Groups"]:
        amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
        if amount > 0.01:
            results.append({"service": group["Keys"][0], "cost": round(amount, 2)})
    return sorted(results, key=lambda x: x["cost"], reverse=True)


def get_monthly_trend(ce, months: int) -> list[dict]:
    start, end = date_range_last_n_months(months)
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    return [
        {
            "month": r["TimePeriod"]["Start"][:7],
            "cost":  round(float(r["Total"]["UnblendedCost"]["Amount"]), 2),
        }
        for r in resp["ResultsByTime"]
    ]


def get_daily_spend(ce, start: str, end: str) -> list[dict]:
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
    )
    return [
        {
            "date": r["TimePeriod"]["Start"],
            "cost": round(float(r["Total"]["UnblendedCost"]["Amount"]), 2),
        }
        for r in resp["ResultsByTime"]
    ]


def get_cost_by_tag(ce, start: str, end: str, tag_key: str = "CostCenter") -> list[dict]:
    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "TAG", "Key": tag_key}],
        )
        results = []
        for group in resp["ResultsByTime"][0]["Groups"]:
            tag_val = group["Keys"][0].replace(f"{tag_key}$", "") or "UNTAGGED"
            amount  = float(group["Metrics"]["UnblendedCost"]["Amount"])
            if amount > 0.01:
                results.append({"tag_value": tag_val, "cost": round(amount, 2)})
        return sorted(results, key=lambda x: x["cost"], reverse=True)
    except ClientError:
        return []


def get_forecast(ce) -> dict:
    today = date.today()
    month_end = today.replace(day=monthrange(today.year, today.month)[1])
    if today >= month_end:
        return {"mean": None, "lower": None, "upper": None}
    try:
        resp = ce.get_cost_forecast(
            TimePeriod={
                "Start": today.strftime("%Y-%m-%d"),
                "End":   month_end.strftime("%Y-%m-%d"),
            },
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
        )
        return {
            "mean":  round(float(resp["Total"]["Amount"]), 2),
            "lower": round(float(resp["ForecastResultsByTime"][0]["PredictionIntervalLowerBound"]), 2),
            "upper": round(float(resp["ForecastResultsByTime"][0]["PredictionIntervalUpperBound"]), 2),
        }
    except ClientError:
        return {"mean": None, "lower": None, "upper": None}


def render_console(report: dict):
    sep = "=" * 64

    print(f"\n{sep}")
    print(f"  AWS FINOPS COST REPORT — {report['generated_at'][:10]}")
    print(f"  Account: {report['account_id']}  |  Region: {report['region']}")
    print(sep)

    # MTD Summary
    mtd = report["mtd_total"]
    print(f"\n  📊 Month-to-Date Spend ({report['mtd_period']['start']} → {report['mtd_period']['end']})")
    print(f"     Total:    ${mtd:,.2f}")
    if report["forecast"]["mean"]:
        print(f"     Forecast: ${report['forecast']['mean']:,.2f}  (range: ${report['forecast']['lower']:,.2f}–${report['forecast']['upper']:,.2f})")
    print()

    # Top services
    print("  🏆 Top Services by Spend")
    print(f"  {'Service':<45} {'Cost':>10}")
    print("  " + "─" * 57)
    for s in report["top_services"][:10]:
        bar = "█" * min(int(s["cost"] / max(report["top_services"][0]["cost"], 1) * 20), 20)
        print(f"  {s['service'][:45]:<45} ${s['cost']:>9,.2f}  {bar}")

    # Monthly trend
    print(f"\n  📈 Monthly Trend (last {len(report['monthly_trend'])} months)")
    for m in report["monthly_trend"]:
        bar = "█" * min(int(m["cost"] / max((t["cost"] for t in report["monthly_trend"]), default=1) * 30), 30)
        print(f"  {m['month']}  ${m['cost']:>9,.2f}  {bar}")

    # Cost by CostCenter
    if report["cost_by_cost_center"]:
        print("\n  🏷  Cost by CostCenter Tag")
        untagged_cost = next((x["cost"] for x in report["cost_by_cost_center"] if x["tag_value"] == "UNTAGGED"), 0)
        if untagged_cost > 0:
            pct = untagged_cost / mtd * 100 if mtd else 0
            print(f"  ⚠️  Untagged resources: ${untagged_cost:,.2f} ({pct:.0f}% of spend) — fix tagging!")
        for c in report["cost_by_cost_center"][:10]:
            print(f"  {c['tag_value']:<40} ${c['cost']:>10,.2f}")

    # Recommendations
    print("\n  💡 Recommended Actions")
    for i, rec in enumerate(report["recommendations"], 1):
        print(f"  {i}. {rec['action']}")
        if rec.get("estimated_savings"):
            print(f"     Estimated savings: {rec['estimated_savings']}")

    print(f"\n{sep}\n")


def render_markdown(report: dict) -> str:
    lines = [
        "# AWS FinOps Cost Report",
        "",
        f"**Generated:** {report['generated_at'][:19]} UTC  ",
        f"**Account:** `{report['account_id']}`  ",
        f"**Region:** `{report['region']}`",
        "",
        "---",
        "",
        "## Month-to-Date Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Period | {report['mtd_period']['start']} → {report['mtd_period']['end']} |",
        f"| MTD Total | **${report['mtd_total']:,.2f}** |",
    ]

    fc = report["forecast"]
    if fc["mean"]:
        lines += [
            f"| Forecast (month-end) | ${fc['mean']:,.2f} |",
            f"| Forecast range | ${fc['lower']:,.2f} – ${fc['upper']:,.2f} |",
        ]

    lines += [
        "",
        "## Top 10 Services by Spend",
        "",
        "| # | Service | Cost (USD) |",
        "|---|---------|-----------|",
    ]
    for i, s in enumerate(report["top_services"][:10], 1):
        lines.append(f"| {i} | {s['service']} | ${s['cost']:,.2f} |")

    lines += [
        "",
        "## Monthly Trend",
        "",
        "| Month | Spend (USD) |",
        "|-------|------------|",
    ]
    for m in report["monthly_trend"]:
        lines.append(f"| {m['month']} | ${m['cost']:,.2f} |")

    if report["cost_by_cost_center"]:
        lines += [
            "",
            "## Cost by CostCenter Tag",
            "",
            "| CostCenter | Cost (USD) |",
            "|-----------|-----------|",
        ]
        for c in report["cost_by_cost_center"][:10]:
            lines.append(f"| {c['tag_value']} | ${c['cost']:,.2f} |")

    lines += [
        "",
        "## Recommended Actions",
        "",
    ]
    for i, rec in enumerate(report["recommendations"], 1):
        savings = f" *(Est. savings: {rec['estimated_savings']})*" if rec.get("estimated_savings") else ""
        lines.append(f"{i}. **{rec['action']}**{savings}")
        if rec.get("detail"):
            lines.append(f"   {rec['detail']}")

    return "\n".join(lines)


def build_recommendations(report: dict) -> list[dict]:
    recs = []
    mtd = report["mtd_total"]

    # Untagged spend
    untagged = next((x for x in report.get("cost_by_cost_center", []) if x["tag_value"] == "UNTAGGED"), None)
    if untagged and untagged["cost"] > 5:
        recs.append({
            "action": f"Enforce CostCenter tagging — ${untagged['cost']:,.2f} of spend is untagged",
            "estimated_savings": "Visibility only; enables chargeback",
            "detail": "Enable the required-tags Config rule and set an SCP to block untagged launches.",
        })

    # Budget forecast overage
    fc = report["forecast"]
    if fc["mean"] and fc["mean"] > 50:
        recs.append({
            "action": f"Forecasted spend ${fc['mean']:,.2f} will exceed the $50 budget",
            "estimated_savings": f"${fc['mean'] - 50:,.2f} overage if no action taken",
            "detail": "Review top services and schedule auto-stop for non-production workloads.",
        })

    # Spot opportunity
    ec2_spend = next((s["cost"] for s in report["top_services"] if "EC2" in s["service"]), 0)
    if ec2_spend > 20:
        recs.append({
            "action": "Migrate stateless EC2 workloads to Spot Instances",
            "estimated_savings": f"Up to ${ec2_spend * 0.7:,.2f}/mo (70% of EC2 spend)",
            "detail": "Use Mixed-Instance ASG with 70% Spot. See compute_optimized Terraform module.",
        })

    # Savings Plans
    if mtd > 100:
        recs.append({
            "action": "Purchase Compute Savings Plan for predictable workloads",
            "estimated_savings": "Up to 66% vs On-Demand",
            "detail": "Analyse 30-day usage, then buy a 1-year Compute Savings Plan.",
        })

    recs.append({
        "action": "Run gc_ebs_volumes.py to delete unattached EBS volumes",
        "estimated_savings": "Variable — check zombie asset scan output",
        "detail": "python scripts/gc_ebs_volumes.py  (dry-run first, then --execute)",
    })

    recs.append({
        "action": "Enable AWS Compute Optimizer and review recommendations weekly",
        "estimated_savings": "Typically 15-25% on rightsized instances",
    })

    return recs


def main():
    parser = argparse.ArgumentParser(description="FinOps Cost Explorer Report")
    parser.add_argument("--region",  default="us-east-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--months",  type=int, default=3)
    parser.add_argument("--format",  choices=["console", "json", "markdown"], default="console")
    parser.add_argument("--output",  default=None)
    args = parser.parse_args()

    try:
        session    = boto3.Session(profile_name=args.profile, region_name=args.region)
        ce         = session.client("ce", region_name="us-east-1")   # Cost Explorer is global
        sts        = session.client("sts")
        account_id = sts.get_caller_identity()["Account"]
    except NoCredentialsError:
        print("ERROR: No AWS credentials configured.")
        sys.exit(1)

    print(f"Pulling Cost Explorer data for account {account_id} …", flush=True)

    start_mtd, end_mtd = date_range_mtd()

    # ── Gather data ──────────────────────────────────────────────────────────
    top_services      = get_service_breakdown(ce, start_mtd, end_mtd)
    monthly_trend     = get_monthly_trend(ce, args.months)
    daily_spend       = get_daily_spend(ce, start_mtd, end_mtd)
    cost_by_cc        = get_cost_by_tag(ce, start_mtd, end_mtd, "CostCenter")
    forecast          = get_forecast(ce)
    mtd_total         = sum(s["cost"] for s in top_services)

    report = {
        "generated_at":         datetime.utcnow().isoformat(),
        "account_id":           account_id,
        "region":               args.region,
        "mtd_period":           {"start": start_mtd, "end": end_mtd},
        "mtd_total":            round(mtd_total, 2),
        "forecast":             forecast,
        "top_services":         top_services,
        "monthly_trend":        monthly_trend,
        "daily_spend":          daily_spend,
        "cost_by_cost_center":  cost_by_cc,
        "recommendations":      [],   # Filled below
    }
    report["recommendations"] = build_recommendations(report)

    # ── Render ───────────────────────────────────────────────────────────────
    if args.format == "console":
        render_console(report)
        output = None
    elif args.format == "markdown":
        output = render_markdown(report)
    else:
        output = json.dumps(report, indent=2, default=str)

    if output:
        if args.output:
            with open(args.output, "w") as fh:
                fh.write(output)
            print(f"\n📄 Report saved to {args.output}")
        else:
            print(output)


if __name__ == "__main__":
    main()
