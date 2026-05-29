# AWS Cost Optimization Guide — End-to-End FinOps Playbook

**Version:** 1.0  
**Author:** FinOps Team  
**Last Updated:** 2025-07-15  

> This is a practical, implementable guide. Every command can be run today. Every architecture pattern is deployed in the `terraform/` directory of this repository.

---

## Table of Contents

1. [FinOps Fundamentals](#1-finops-fundamentals)
2. [Immediate Wins — Zombie Asset Cleanup](#2-immediate-wins--zombie-asset-cleanup)
3. [Cost Visibility — Tagging & Reporting](#3-cost-visibility--tagging--reporting)
4. [Budget Governance](#4-budget-governance)
5. [Compute Optimization — Spot & Savings Plans](#5-compute-optimization--spot--savings-plans)
6. [Storage Optimization](#6-storage-optimization)
7. [Database Cost Reduction](#7-database-cost-reduction)
8. [Network Cost Reduction](#8-network-cost-reduction)
9. [The FinOps Operating Cadence](#9-the-finops-operating-cadence)
10. [Quick Reference — Savings Estimates](#10-quick-reference--savings-estimates)

---

## 1. FinOps Fundamentals

FinOps (Financial Operations) applies DevOps agility to cloud finance. The three pillars are:

**Inform → Optimize → Operate**

| Pillar | What it means | Tools in this repo |
|--------|--------------|-------------------|
| **Inform** | Know what you're spending and on what | `generate_cost_report.py`, tagging policy, Cost Explorer |
| **Optimize** | Eliminate waste, rightsize, use cheaper purchase options | `gc_ebs_volumes.py`, Spot ASG, Savings Plans |
| **Operate** | Embed cost awareness into engineering workflows | Budgets, Config rules, pre-commit hooks, runbooks |

**The golden rule of cloud cost management:**  
*You cannot optimize what you cannot see. Tag everything before you optimize anything.*

---

## 2. Immediate Wins — Zombie Asset Cleanup

These actions take under 30 minutes and typically recover 5–20% of total cloud spend.

### Step 1: Run the zombie scanner

```bash
cd scripts/
pip install -r requirements.txt

# Scan (safe — read-only)
python find_zombie_assets.py --region us-east-1 --output zombie_report.json

# Review output — look for HIGH risk findings
cat zombie_report.json | python -m json.tool | grep -A5 '"risk": "HIGH"'
```

### Step 2: Clean up unattached EBS volumes

```bash
# Dry-run first
python gc_ebs_volumes.py --region us-east-1

# When ready, execute (creates snapshots automatically)
python gc_ebs_volumes.py --region us-east-1 --execute --audit-log gc_audit.json
```

**Manual check in console:**
1. EC2 → Volumes → Filter: State = available
2. Select all → Actions → Delete

### Step 3: Release unassociated Elastic IPs

```bash
# List unassociated EIPs
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp]' \
  --output table

# Release each one
aws ec2 release-address --allocation-id eipalloc-0abc123
```

**Cost:** $0.005/hour ($3.60/month) per idle EIP. Even one unused EIP is $43.20/year.

### Step 4: Identify and stop idle instances

```bash
# List instances with < 5% average CPU (last 14 days)
python find_zombie_assets.py --region us-east-1 | grep -A5 "Idle EC2"

# Stop a specific instance
aws ec2 stop-instances --instance-ids i-0abc123

# Schedule auto-stop for non-prod (evenings + weekends = ~65% savings)
# Use AWS Instance Scheduler or a simple EventBridge rule
```

**Instance Scheduler approach (saves 65% on dev/staging):**
```bash
# Tag instance for scheduler
aws ec2 create-tags --resources i-0abc123 \
  --tags Key=schedule,Value=office-hours   # 9AM-6PM weekdays only
```

### Step 5: Delete unused load balancers

```bash
# List ALBs with no healthy targets
aws elbv2 describe-load-balancers \
  --query 'LoadBalancers[*].[LoadBalancerName,LoadBalancerArn,CreatedTime]' \
  --output table

# For each LB, check target groups
aws elbv2 describe-target-groups --load-balancer-arn arn:aws:elasticloadbalancing:...

# Delete if unused
aws elbv2 delete-load-balancer --load-balancer-arn arn:aws:elasticloadbalancing:...
```

---

## 3. Cost Visibility — Tagging & Reporting

### Set up Cost Explorer groups

1. **AWS Console → Billing → Cost Explorer**
2. Click **Explore costs**
3. Group by **Tag: CostCenter**
4. Set date: **Last 3 months**
5. Enable **Daily granularity** to spot anomalies

### Generate automated cost report

```bash
# Console output
python scripts/generate_cost_report.py --region us-east-1

# Markdown report (for wikis/PRs)
python scripts/generate_cost_report.py --format markdown --output this_weeks_report.md

# JSON for programmatic consumption
python scripts/generate_cost_report.py --format json --output cost_data.json
```

### Enable Cost Anomaly Detection

```bash
# Create an anomaly monitor for EC2 spend
aws ce create-anomaly-monitor \
  --anomaly-monitor '{
    "MonitorName": "EC2SpendMonitor",
    "MonitorType": "DIMENSIONAL",
    "MonitorDimension": "SERVICE"
  }'

# Create an alert (triggers on anomalies > $10)
aws ce create-anomaly-subscription \
  --anomaly-subscription '{
    "SubscriptionName": "EC2AnomalyAlert",
    "MonitorArnList": ["arn:aws:ce::123456789012:anomalymonitor/..."],
    "Subscribers": [{"Address": "finops@company.com", "Type": "EMAIL"}],
    "Threshold": 10,
    "Frequency": "DAILY"
  }'
```

---

## 4. Budget Governance

### Terraform deployment (already in this repo)

```bash
cd terraform/
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

terraform init
terraform plan
terraform apply -target=module.governance
```

This creates:
- Monthly budget with $50 limit
- Alert at 80% actual spend
- Alert at 100% forecasted spend
- SNS topic + email subscription
- AWS Config rules for tag enforcement

### Manual budget creation (AWS Console)

1. **Billing → Budgets → Create budget**
2. Choose **Cost budget**
3. Period: **Monthly**, Amount: **$50**
4. Add alert: **Threshold 80%**, **Actual**, email + SNS
5. Add alert: **Threshold 100%**, **Forecasted**, email + SNS

### Zero-spend alert for sandbox accounts

```bash
# Create a $1 budget that fires when ANY spend occurs
aws budgets create-budget \
  --account-id 123456789012 \
  --budget '{
    "BudgetName": "zero-spend-alert",
    "BudgetType": "COST",
    "BudgetLimit": {"Amount": "1", "Unit": "USD"},
    "TimeUnit": "MONTHLY"
  }' \
  --notifications-with-subscribers '[{
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 0.01
    },
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "you@company.com"}]
  }]'
```

---

## 5. Compute Optimization — Spot & Savings Plans

### 5.1 Spot Instances (up to 90% savings)

**Best for:** Stateless web tiers, batch processing, CI/CD workers, ML training, dev/test environments.  
**Not suitable for:** Single-instance databases, stateful apps without graceful interruption handling.

**Deploy the Mixed-Instance ASG:**

```bash
cd terraform/
terraform apply -target=module.compute_optimized
```

This creates an ASG with:
- 1 On-Demand base instance (stable anchor)
- 70% Spot for scale-out capacity
- 5 instance type overrides (reduces interruption risk)
- `capacity-optimized` allocation strategy
- IMDSv2 enforced on all instances

**Handle Spot interruptions in your application:**

```bash
# In your EC2 user_data — poll for interruption notice
while true; do
  TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
  
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/spot/interruption-action)
  
  if [ "$STATUS" = "200" ]; then
    echo "Spot interruption notice received — gracefully shutting down"
    # Your graceful shutdown logic here (drain connections, finish job, etc.)
    systemctl stop myapp
    break
  fi
  sleep 5
done
```

**Cost comparison:**

| Strategy | t3.medium/hr | Monthly (730hr) | Savings |
|----------|-------------|----------------|---------|
| On-Demand | $0.0416 | $30.37 | — |
| 1-yr Savings Plan | $0.0264 | $19.27 | 37% |
| Spot (typical) | $0.0125 | $9.13 | 70% |
| Mixed (1 OD + rest Spot) | ~$0.0180 | ~$13.14 | ~57% |

### 5.2 Compute Savings Plans

**Best for:** Predictable baseline workloads that run 24/7.  
**How to purchase:**

1. **Cost Explorer → Savings Plans → Recommendations**
2. Select **Compute Savings Plan** (flexible — covers EC2, Fargate, Lambda)
3. Term: **1 year** (37% savings) or **3 year** (66% savings)
4. Payment: **No upfront** (safest for first purchase)
5. Commitment: Start with **50-70% of your baseline compute spend**

```bash
# Check current Savings Plans recommendations
aws savingsplans describe-savings-plans-offering-rates \
  --savings-plan-offering-ids \
  $(aws savingsplans describe-savings-plans-offerings \
    --product-type "Compute" \
    --plan-types "ComputeSavingsPlans" \
    --query 'searchResults[0].offeringId' --output text)
```

### 5.3 Rightsizing

```bash
# Enable AWS Compute Optimizer (free)
aws compute-optimizer update-enrollment-status --status Active

# Get recommendations after 14 days of data collection
aws compute-optimizer get-ec2-instance-recommendations \
  --query 'instanceRecommendations[*].{
    Instance:instanceArn,
    Current:currentInstanceType,
    Recommended:recommendationOptions[0].instanceType,
    Savings:recommendationOptions[0].estimatedMonthlySavings.value
  }' \
  --output table
```

---

## 6. Storage Optimization

### EBS Volume Optimization

```bash
# Find gp2 volumes (upgrade to gp3 = same performance, 20% cheaper)
aws ec2 describe-volumes \
  --filters Name=volume-type,Values=gp2 \
  --query 'Volumes[*].[VolumeId,Size,State]' \
  --output table

# Migrate a volume from gp2 to gp3 (zero downtime, no detach needed)
aws ec2 modify-volume \
  --volume-id vol-0abc123 \
  --volume-type gp3 \
  --iops 3000 \
  --throughput 125
```

**Savings:** gp3 is $0.08/GB-month vs gp2's $0.10/GB-month — **20% cheaper with equal baseline performance**.

### S3 Lifecycle Policies

```bash
# Apply lifecycle policy: move to IA after 30d, Glacier after 90d
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-data-bucket \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "auto-tier",
      "Status": "Enabled",
      "Filter": {},
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
| S3 Standard-IA | $0.0125 | Infrequent (30d+ old) |
| S3 Glacier | $0.004 | Archives (90d+) |
| S3 Deep Archive | $0.00099 | Long-term (1yr+) |

---

## 7. Database Cost Reduction

### Aurora Serverless v2 for Variable Workloads

For databases with unpredictable traffic patterns, Aurora Serverless v2 scales to zero (well, 0.5 ACUs minimum) during idle periods.

```bash
# Convert existing Aurora cluster to Serverless v2
aws rds modify-db-cluster \
  --db-cluster-identifier my-cluster \
  --serverless-v2-scaling-configuration MinCapacity=0.5,MaxCapacity=8 \
  --apply-immediately
```

### RDS Instance Scheduling (dev/staging)

Stop non-production RDS instances outside business hours. AWS charges for storage but not compute when stopped.

```bash
# Stop dev RDS (evenings)
aws rds stop-db-instance --db-instance-identifier dev-database

# Start dev RDS (mornings) — or use EventBridge Scheduler
aws rds start-db-instance --db-instance-identifier dev-database
```

**Savings:** If you stop an RDS instance 16 hours/day and weekends, compute costs drop by ~65%.

### RDS Reserved Instances

For production databases that run 24/7, Reserved Instances save 40-60%:

1. **RDS Console → Reserved Instances → Purchase**
2. Engine: Match your production DB
3. Term: 1 year No Upfront = 40% savings; 1 year All Upfront = 43% savings

---

## 8. Network Cost Reduction

### Identify data transfer costs

```bash
# Cost Explorer — filter by "Data Transfer" service
aws ce get-cost-and-usage \
  --time-period Start=2025-06-01,End=2025-07-01 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["AWS Data Transfer"]}}' \
  --query 'ResultsByTime[0].Total.UnblendedCost.Amount'
```

### Use VPC Endpoints to eliminate NAT Gateway costs

Data through a NAT Gateway costs $0.045/GB. VPC Interface Endpoints cost $0.01/GB — **78% cheaper** for AWS service traffic.

```bash
# Create S3 Gateway Endpoint (free — no hourly cost)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-0abc123 \
  --service-name com.amazonaws.us-east-1.s3 \
  --vpc-endpoint-type Gateway \
  --route-table-ids rtb-0abc123

# Create SSM Interface Endpoint (replaces NAT for SSM traffic)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-0abc123 \
  --service-name com.amazonaws.us-east-1.ssm \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-0abc123 \
  --security-group-ids sg-0abc123
```

### Eliminate cross-AZ data transfer

Cross-AZ traffic costs $0.01/GB each direction. Keep application and database in the same AZ for read-heavy workloads.

```bash
# Check which AZ your RDS primary is in
aws rds describe-db-instances \
  --db-instance-identifier my-db \
  --query 'DBInstances[0].AvailabilityZone'

# Then launch application EC2 instances in the same AZ
aws ec2 run-instances \
  --placement '{"AvailabilityZone": "us-east-1a"}' \
  ...
```

---

## 9. The FinOps Operating Cadence

### Daily (5 minutes)

- [ ] Check Cost Anomaly Detection email
- [ ] Review yesterday's spend if > $X threshold in budget alert

### Weekly (30 minutes, Mondays)

```bash
# Generate weekly report
python scripts/generate_cost_report.py --format markdown --output weekly_$(date +%Y%m%d).md

# Run zombie scan
python scripts/find_zombie_assets.py --output zombie_$(date +%Y%m%d).json

# Check Config compliance
aws configservice describe-compliance-by-config-rule \
  --query 'ComplianceByConfigRules[?Compliance.ComplianceType==`NON_COMPLIANT`]'
```

### Monthly (2 hours, first week of month)

- [ ] Review previous month total vs budget
- [ ] Run `gc_ebs_volumes.py` and act on recommendations
- [ ] Check Compute Optimizer for new rightsizing opportunities
- [ ] Review Savings Plans utilisation (aim for >80%)
- [ ] Conduct team chargeback review (Cost Explorer by CostCenter tag)
- [ ] Update `AUDIT_REPORT.md` with findings and actions

### Quarterly (4 hours)

- [ ] Review and update tagging policy
- [ ] Evaluate Savings Plans purchase for next quarter baseline
- [ ] Architecture review: any new services that need cost controls?
- [ ] Review and update approved instance types in Config rule

---

## 10. Quick Reference — Savings Estimates

| Optimization | Typical Savings | Effort | Risk |
|-------------|----------------|--------|------|
| Delete unattached EBS volumes | $10–500/mo | Low | Low |
| Release unused Elastic IPs | $4–40/mo | Very Low | None |
| Stop idle instances | 100% of idle cost | Low | Low |
| Rightsize oversized instances | 30–70% of compute | Medium | Medium |
| Spot Instances (stateless) | 60–90% of compute | Medium | Low |
| Compute Savings Plans | 37–66% of compute | Low | Low |
| gp2 → gp3 EBS migration | 20% of EBS | Low | None |
| S3 lifecycle policies | 40–80% of S3 | Low | None |
| VPC Endpoints (vs NAT GW) | 50–78% of NAT | Medium | Low |
| Instance scheduling (dev) | 65% of compute | Low | None |
| Aurora Serverless (variable) | 30–60% of DB | High | Medium |

---

## Appendix A: Useful AWS CLI One-liners

```bash
# Total spend this month
aws ce get-cost-and-usage \
  --time-period Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --query 'ResultsByTime[0].Total.UnblendedCost.Amount' \
  --output text

# All running instances and their types
aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,Tags[?Key==`Name`].Value|[0]]' \
  --output table

# S3 bucket sizes
aws s3api list-buckets --query 'Buckets[*].Name' --output text | \
  xargs -I{} aws cloudwatch get-metric-statistics \
    --namespace AWS/S3 --metric-name BucketSizeBytes \
    --dimensions Name=BucketName,Value={} Name=StorageType,Value=StandardStorage \
    --start-time $(date -d '2 days ago' +%Y-%m-%dT00:00:00) \
    --end-time $(date +%Y-%m-%dT00:00:00) \
    --period 86400 --statistics Average \
    --query 'Datapoints[0].Average' --output text

# Find resources without CostCenter tag (EC2)
aws ec2 describe-instances \
  --query 'Reservations[*].Instances[?!not_null(Tags[?Key==`CostCenter`].Value|[0])].[InstanceId]' \
  --output text
```

---

*This guide is maintained in the `finops` repository. PRs welcome. For questions: finops@company.com*
