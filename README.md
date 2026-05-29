# FinOps Cost Detective

> **Audit, govern, and optimise an inherited AWS account with measurable, documented savings.**

This repository contains the complete deliverable for the "Cost Detective" FinOps audit challenge: Terraform infrastructure, Python automation scripts, and full documentation covering zombie asset detection, cost governance, and Spot-based compute optimisation.

**Live deployment verified on 2026-05-29 in `eu-central-1` (account `734849394099`).**

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Quick Start](#quick-start)
3. [Audit Report](#audit-report)
4. [Live Deployment Evidence](#live-deployment-evidence)
5. [Tagging Policy](#tagging-policy)
6. [Cost Optimization Guide](#cost-optimization-guide)
7. [Teardown](#teardown)

---

## Project Structure

```
finops-cost-detective/
├── providers.tf                   # AWS provider + default tags
├── variables.tf                   # Root input variables
├── main.tf                        # Root module orchestration
├── outputs.tf                     # Key resource IDs and ARNs
├── terraform.tfvars.example       # Variable template (copy to terraform.tfvars)
├── modules/
│   ├── wasteful_resources/        # Zombie asset baseline (demo)
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   ├── governance/                # Budgets, SNS, Config rules, S3
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   └── compute_optimized/         # Mixed-Instance ASG (Spot + On-Demand)
│       ├── main.tf
│       ├── variables.tf
│       └── outputs.tf
├── find_zombie_assets.py          # Full zombie asset scanner
├── gc_ebs_volumes.py              # Unattached EBS garbage collector
├── generate_cost_report.py        # Cost Explorer FinOps report
├── requirements.txt
└── audit-evidence/
    └── findings.md                # Raw evidence collected during live audit
```

---

## Quick Start

### Prerequisites

- AWS CLI configured (`aws configure` or environment variables)
- Terraform >= 1.5
- Python >= 3.11
- An AWS account (sandbox recommended)

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Scan for zombie assets (read-only, safe)

```bash
python find_zombie_assets.py --region eu-central-1
```

### 3. Deploy all infrastructure

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your VPC ID, subnet IDs, emails, etc.

terraform init
terraform plan
terraform apply
```

### 4. Clean up unattached EBS volumes

```bash
# Dry-run (no changes)
python gc_ebs_volumes.py --region eu-central-1

# Execute (snapshot + delete)
python gc_ebs_volumes.py --region eu-central-1 --execute --audit-log gc_audit.json
```

### 5. Generate cost report

```bash
python generate_cost_report.py --format markdown --output cost_report.md
```

---

## Audit Report

**Audit Date:** 2026-05-29 | **Region:** `eu-central-1` | **Account:** `734849394099`

### Executive Summary

An inherited AWS sandbox account was audited for cost inefficiency, missing governance controls, and architectural waste. The audit identified zombie assets, deployed governance guardrails, and replaced an On-Demand-only compute fleet with a cost-optimised Mixed-Instance ASG.

| Metric | Value |
|--------|-------|
| Zombie assets deployed (demo) | 6 |
| Estimated monthly zombie waste | ~$75/month |
| Governance controls deployed | 4 Config rules + Budget + SNS |
| Compute savings (Spot mix vs. On-Demand) | ~57% |

---

### Phase 1 — Zombie Asset Detection

Three categories of zombie assets were created intentionally to simulate an inherited account, then scanned using `find_zombie_assets.py` and AWS Config.

#### Unattached EBS Volumes

Three `gp3` volumes in `eu-central-1a` sitting unattached, accumulating cost with no workload attached.

| Volume ID | Size | Monthly Waste |
|---|---|---|
| vol-0b764bc2bf26c3567 | 20 GB | $1.60 |
| vol-0460d57f03e6a8572 | 30 GB | $2.40 |
| vol-0c79a0fbcf9530caa | 40 GB | $3.20 |

**Cleanup command:**
```bash
python gc_ebs_volumes.py --region eu-central-1 --execute --audit-log gc_audit.json
```

The script snapshots each volume before deletion and writes a full JSON audit trail.

#### Unassociated Elastic IPs

Two Elastic IPs allocated but not associated with any instance — charged at $0.005/hour ($3.60/month each).

| Name | Public IP | Allocation ID |
|---|---|---|
| zombie-eip-1 | 63.177.152.115 | eipalloc-0ecde7a01cf7997a3 |
| zombie-eip-2 | 63.183.108.83 | eipalloc-005fe2d2956c20278 |

**Cleanup command:**
```bash
aws ec2 release-address --allocation-id eipalloc-0ecde7a01cf7997a3
aws ec2 release-address --allocation-id eipalloc-005fe2d2956c20278
```

#### Idle Large EC2 Instance

A `t3.large` instance running with no workload (~0% CPU). Detected by the `find_zombie_assets.py` scanner using CloudWatch 14-day CPU averages.

| Instance ID | Type | State | CPU | Monthly Cost |
|---|---|---|---|---|
| i-01caf88c8befe4554 | t3.large | Running | ~0% | $60.74 |

**Remediation:** Rightsize to `t3.micro` after 72-hour observation window ($60.74 → $7.59/month, saving **$53.15/month**).

---

### Phase 2 — Governance Implementation

#### AWS Budget — $50/Month Alert

Budget deployed via Terraform (`module.governance`) with two alert thresholds:

| Alert | Threshold | Type | Notification |
|---|---|---|---|
| Alert 1 | 80% of $50 = $40 | Actual spend | SNS + email |
| Alert 2 | 100% of $50 = $50 | Forecasted spend | SNS + email |

**Budget status on 2026-05-29:** Healthy — $7.16 of $50.00 spent this month.

#### SNS Email Subscription

Email confirmation received at `valens.niyonkuru@amalitechtraining.org` for:
```
arn:aws:sns:eu-central-1:734849394099:finops-cost-alerts-sandbox
```

#### AWS Config Rules (4 Rules Active)

| Rule Name | Identifier | Checks |
|---|---|---|
| `required-tags-cost-center` | `REQUIRED_TAGS` | CostCenter, Environment, Owner tags on EC2, EBS, RDS, S3 |
| `ec2-ebs-volume-attached` | `EC2_VOLUME_INUSE_CHECK` | Flags unattached EBS volumes |
| `eip-attached` | `EIP_ATTACHED` | Flags unassociated Elastic IPs |
| `approved-ec2-instance-types` | `DESIRED_INSTANCE_TYPE` | Enforces allowlist of instance types |

**Check compliance status:**
```bash
aws configservice describe-compliance-by-config-rule \
  --config-rule-names required-tags-cost-center ec2-ebs-volume-attached eip-attached
```

#### S3 Config Delivery Bucket

```
finops-config-audit-734849394099  (eu-central-1)
```

Encrypted (AES-256), versioned, public access blocked. AWS Config delivers snapshots here.

---

### Phase 3 — Spot Optimization Architecture

A Mixed-Instance Auto Scaling Group replaced a hypothetical On-Demand-only fleet.

**ASG:** `finops-mixed-asg-sandbox`  
**ARN:** `arn:aws:autoscaling:eu-central-1:734849394099:autoScalingGroup:c8c2b4ef-d103-4d2b-94fa-6584dca2f42f:autoScalingGroupName/finops-mixed-asg-sandbox`

| Parameter | Value |
|---|---|
| Launch Template | lt-0f2a73c89bd0b6249 (AL2023, IMDSv2) |
| On-Demand base | 1 instance (guaranteed) |
| Spot percentage | 70% of scale-out |
| Instance types | t3.medium, t3a.medium, t2.medium, m5.large, m5a.large |
| Spot strategy | `capacity-optimized` |
| Min / Desired / Max | 1 / 1 / 6 |
| Status | ✅ At desired capacity |

| Configuration | Monthly Cost | Savings |
|---|---|---|
| Before: On-Demand only (t3.medium × 2) | $60.48 | — |
| After: 1 OD + rest Spot | ~$26.00 | **~57%** |

---

## Live Deployment Evidence

All resources below were deployed on **2026-05-29** and verified in the AWS Console.

### EC2 Instances — Console View

Running instances in `eu-central-1` after Terraform apply:

| Name | Instance ID | Type | State | Purpose |
|---|---|---|---|---|
| finops-mixed-asg-sandbox | i-0f4a3158bcf594454 | t3.medium | Running | ASG instance (On-Demand base) |
| finops-mixed-asg-sandbox | i-07b28328397cfc5c9 | t3.medium | Running | ASG instance |
| idle-large-instance-demo | i-01caf88c8befe4554 | t3.large | Running | Zombie demo instance |

### Elastic IPs — Console View

5 Elastic IPs in account — `zombie-eip-1` and `zombie-eip-2` are unassociated (waste):

| Name | IP | Allocation ID | Status |
|---|---|---|---|
| zombie-eip-1 | 63.177.152.115 | eipalloc-0ecde7a01cf7997a3 | Unassociated |
| zombie-eip-2 | 63.183.108.83 | eipalloc-005fe2d2956c20278 | Unassociated |

### ASG Detail — At Desired Capacity

```
finops-mixed-asg-sandbox
Desired: 1  |  Min: 1  |  Max: 6  |  Status: At desired capacity
Created: Fri May 29 2026 14:58:20 GMT+0200
```

### S3 Config Bucket

```
finops-config-audit-734849394099
Region: Europe (Frankfurt) eu-central-1
Created: May 29, 2026, 14:57:54 (UTC+02:00)
```

### Budget — Healthy

```
finops-monthly-budget-sandbox
Type: Cost budget  |  Amount: $50.00/month  |  Period: Monthly
Status: Healthy  |  Spent this month: $7.16
```

### SNS Subscription Email

```
From: AWS Notifications <no-reply@sns.amazonaws.com>
To: valens.niyonkuru@amalitechtraining.org
Subject: AWS Notification - Subscription Confirmation

Topic: arn:aws:sns:eu-central-1:734849394099:finops-cost-alerts-sandbox
```

---

## Tagging Policy

**Version:** 1.0 | **Effective:** 2026-05-29 | **Enforcement:** AWS Config

Consistent resource tagging is the foundation of cloud financial management. Without tags, cost attribution is impossible and zombie assets go undetected.

### Tag Taxonomy

**Mandatory Tags** (enforced by Config rule `required-tags-cost-center`):

| Tag Key | Description | Allowed Values |
|---------|-------------|----------------|
| `CostCenter` | Business unit bearing the cost | Any non-empty string |
| `Environment` | Deployment environment | `sandbox`, `staging`, `production` |
| `Owner` | Responsible team email | Valid email address |

**Strongly Recommended Tags:**

| Tag Key | Description | Example |
|---------|-------------|---------|
| `Project` | Initiative name | `finops-audit` |
| `ManagedBy` | Provisioning method | `terraform`, `manual` |
| `ExpiresOn` | Scheduled termination (sandbox) | `2026-08-01` |

### Enforcement Layers

**Layer 1 — AWS Config Rule** (deployed via `module.governance`)

Flags EC2, EBS, RDS, and S3 resources missing `CostCenter`, `Environment`, or `Owner` tags.

```bash
# Check compliance
aws configservice describe-compliance-by-config-rule \
  --config-rule-names required-tags-cost-center

# List non-compliant resources
aws configservice get-compliance-details-by-config-rule \
  --config-rule-name required-tags-cost-center \
  --compliance-types NON_COMPLIANT
```

**Layer 2 — Service Control Policy (SCP)** *(requires AWS Organizations)*

Denies `ec2:RunInstances` if `CostCenter` or `Environment` tags are absent:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyEC2WithoutCostCenter",
      "Effect": "Deny",
      "Action": "ec2:RunInstances",
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": { "Null": { "aws:RequestTag/CostCenter": "true" } }
    },
    {
      "Sid": "DenyEC2WithoutEnvironment",
      "Effect": "Deny",
      "Action": "ec2:RunInstances",
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": { "Null": { "aws:RequestTag/Environment": "true" } }
    },
    {
      "Sid": "DenyRDSWithoutCostCenter",
      "Effect": "Deny",
      "Action": ["rds:CreateDBInstance", "rds:RestoreDBInstanceFromDBSnapshot"],
      "Resource": "*",
      "Condition": { "Null": { "aws:RequestTag/CostCenter": "true" } }
    }
  ]
}
```

**Layer 3 — Terraform Default Tags**

All modules inherit mandatory tags automatically via `providers.tf`:

```hcl
provider "aws" {
  default_tags {
    tags = {
      Project     = "finops-cost-detective"
      ManagedBy   = "terraform"
      Environment = var.environment
      Owner       = var.owner_email
      CostCenter  = var.default_cost_center
    }
  }
}
```

### Non-Compliance Remediation Process

1. Config rule fires → SNS → email alert
2. **72-hour grace period** to add missing tags
3. After 72h unresolved → auto-tag `CostCenter=unowned`, notify FinOps team
4. After 7 days unresolved (non-production) → schedule for termination review

```bash
# Bulk tag untagged EC2 instances
aws ec2 describe-instances \
  --filters "Name=tag-key,Values=!CostCenter" \
  --query 'Reservations[*].Instances[*].InstanceId' \
  --output text | xargs -I{} aws ec2 create-tags \
    --resources {} \
    --tags Key=CostCenter,Value=unowned Key=Owner,Value=finops-review@example.com
```

---

## Cost Optimization Guide

> Every command below can be run today. Every architecture pattern is deployed in this repository.

**The golden rule:** *You cannot optimize what you cannot see. Tag everything before you optimize anything.*

### Immediate Wins — Zombie Asset Cleanup

These actions take under 30 minutes and recover 5–20% of total cloud spend.

```bash
# Scan (safe — read-only)
python find_zombie_assets.py --region eu-central-1 --output zombie_report.json

# Clean unattached EBS volumes
python gc_ebs_volumes.py --region eu-central-1 --execute --audit-log gc_audit.json

# Release unassociated Elastic IPs
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp]' --output table
aws ec2 release-address --allocation-id eipalloc-0abc123

# Delete unused load balancers
aws elbv2 describe-load-balancers \
  --query 'LoadBalancers[*].[LoadBalancerName,LoadBalancerArn]' --output table
```

### Compute Optimization

**Spot Instances (60–90% savings)** — best for stateless web tiers, batch, CI/CD workers, ML training, dev/test.

The `compute_optimized` module deploys this automatically:

```bash
terraform apply -target=module.compute_optimized
```

| Strategy | t3.medium/mo | Savings |
|----------|-------------|---------|
| On-Demand | $30.37 | — |
| 1-yr Savings Plan | $19.27 | 37% |
| Spot (typical) | $9.13 | 70% |
| Mixed (1 OD + rest Spot) | ~$13.14 | ~57% |

**Rightsizing via Compute Optimizer:**

```bash
aws compute-optimizer update-enrollment-status --status Active

# Get recommendations (available after 14 days of data)
aws compute-optimizer get-ec2-instance-recommendations \
  --query 'instanceRecommendations[*].{Instance:instanceArn,Current:currentInstanceType,Recommended:recommendationOptions[0].instanceType,Savings:recommendationOptions[0].estimatedMonthlySavings.value}' \
  --output table
```

**Instance Scheduling (65% savings on dev/staging):**

```bash
# Tag instance for scheduler (9AM–6PM weekdays only)
aws ec2 create-tags --resources i-0abc123 \
  --tags Key=schedule,Value=office-hours
```

### Storage Optimization

**Migrate gp2 → gp3 (20% cheaper, same performance):**

```bash
aws ec2 modify-volume --volume-id vol-0abc123 --volume-type gp3 --iops 3000 --throughput 125
```

**S3 Lifecycle Policy:**

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-data-bucket \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "auto-tier", "Status": "Enabled", "Filter": {},
      "Transitions": [
        {"Days": 30,  "StorageClass": "STANDARD_IA"},
        {"Days": 90,  "StorageClass": "GLACIER"},
        {"Days": 365, "StorageClass": "DEEP_ARCHIVE"}
      ],
      "NoncurrentVersionExpiration": {"NoncurrentDays": 90},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    }]
  }'
```

| Storage Class | Cost/GB-month | Use Case |
|--------------|--------------|---------|
| S3 Standard | $0.023 | Frequently accessed |
| S3 Standard-IA | $0.0125 | 30d+ old |
| S3 Glacier | $0.004 | Archives 90d+ |
| S3 Deep Archive | $0.00099 | Long-term 1yr+ |

### Database Cost Reduction

**RDS Scheduling (65% savings on dev/staging):**

```bash
aws rds stop-db-instance --db-instance-identifier dev-database
aws rds start-db-instance --db-instance-identifier dev-database
```

**Aurora Serverless v2 for variable workloads:**

```bash
aws rds modify-db-cluster \
  --db-cluster-identifier my-cluster \
  --serverless-v2-scaling-configuration MinCapacity=0.5,MaxCapacity=8 \
  --apply-immediately
```

### Network Cost Reduction

**VPC Endpoints vs NAT Gateway (78% cheaper for AWS service traffic):**

```bash
# S3 Gateway Endpoint (free — no hourly cost)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-07fd25884af0f5603 \
  --service-name com.amazonaws.eu-central-1.s3 \
  --vpc-endpoint-type Gateway \
  --route-table-ids rtb-0abc123
```

### Cost Anomaly Detection

```bash
aws ce create-anomaly-monitor \
  --anomaly-monitor '{
    "MonitorName": "EC2SpendMonitor",
    "MonitorType": "DIMENSIONAL",
    "MonitorDimension": "SERVICE"
  }'
```

### FinOps Operating Cadence

**Daily (5 min):** Check Cost Anomaly Detection email.

**Weekly (30 min, Mondays):**
```bash
python generate_cost_report.py --format markdown --output weekly_report.md
python find_zombie_assets.py --output zombie_scan.json
aws configservice describe-compliance-by-config-rule \
  --query 'ComplianceByConfigRules[?Compliance.ComplianceType==`NON_COMPLIANT`]'
```

**Monthly (2 hrs):**
- Review previous month total vs budget
- Run `gc_ebs_volumes.py` and act on recommendations
- Check Compute Optimizer for new rightsizing opportunities
- Review Savings Plans utilisation (aim for >80%)
- Conduct team chargeback review by `CostCenter` tag

**Quarterly (4 hrs):**
- Review and update tagging policy
- Evaluate Savings Plans purchase for baseline compute
- Architecture review for new cost controls
- Update approved instance types in Config rule

### Savings Quick Reference

| Optimization | Typical Savings | Effort | Risk |
|-------------|----------------|--------|------|
| Delete unattached EBS volumes | $10–500/mo | Low | Low |
| Release unused Elastic IPs | $4–40/mo | Very Low | None |
| Stop idle instances | 100% of idle cost | Low | Low |
| Rightsize oversized instances | 30–70% compute | Medium | Medium |
| Spot Instances (stateless) | 60–90% compute | Medium | Low |
| Compute Savings Plans | 37–66% compute | Low | Low |
| gp2 → gp3 EBS migration | 20% of EBS | Low | None |
| S3 lifecycle policies | 40–80% of S3 | Low | None |
| VPC Endpoints (vs NAT GW) | 50–78% of NAT | Medium | Low |
| Instance scheduling (dev) | 65% compute | Low | None |
| Aurora Serverless (variable) | 30–60% of DB | High | Medium |

### Useful AWS CLI One-liners

```bash
# Total spend this month
aws ce get-cost-and-usage \
  --time-period Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY --metrics UnblendedCost \
  --query 'ResultsByTime[0].Total.UnblendedCost.Amount' --output text

# All running instances and types
aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,Tags[?Key==`Name`].Value|[0]]' \
  --output table

# Find EC2 instances without CostCenter tag
aws ec2 describe-instances \
  --query 'Reservations[*].Instances[?!not_null(Tags[?Key==`CostCenter`].Value|[0])].[InstanceId]' \
  --output text

# List all unattached EBS volumes
aws ec2 describe-volumes \
  --filters Name=status,Values=available \
  --query 'Volumes[*].[VolumeId,Size,VolumeType,AvailabilityZone]' \
  --output table

# List unassociated Elastic IPs
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp]' \
  --output table
```

---

## Teardown

```bash
# Remove demo zombie assets only
terraform destroy -target=module.wasteful_resources

# Remove everything
terraform destroy
```

> **Note:** The S3 bucket for AWS Config (`force_destroy = true`) and the Config recorder will be destroyed. The Budget and SNS topic will also be removed.

---

## License

MIT — use freely, attribute appreciated.
