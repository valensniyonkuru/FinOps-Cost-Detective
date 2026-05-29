# Audit Evidence — FinOps Cost Detective

**Audit Date:** 2026-05-29  
**AWS Account:** 734849394099 (aws-study)  
**Region:** eu-central-1 (Europe / Frankfurt)  
**Auditor:** valens.niyonkuru@amalitechtraining.org

---

## Resources Deployed via Terraform

### Zombie Assets (wasteful_resources module)

| Resource | ID | Monthly Waste |
|---|---|---|
| Unattached EBS vol-1 (20 GB gp3) | vol-0b764bc2bf26c3567 | $1.60/mo |
| Unattached EBS vol-2 (30 GB gp3) | vol-0460d57f03e6a8572 | $2.40/mo |
| Unattached EBS vol-3 (40 GB gp3) | vol-0c79a0fbcf9530caa | $3.20/mo |
| Zombie EIP 1 (unassociated) | eipalloc-0ecde7a01cf7997a3 — 63.177.152.115 | $3.60/mo |
| Zombie EIP 2 (unassociated) | eipalloc-005fe2d2956c20278 — 63.183.108.83 | $3.60/mo |
| Idle t3.large EC2 (~0% CPU) | i-01caf88c8befe4554 | $60.74/mo |

### Governance (governance module)

| Resource | ID / ARN |
|---|---|
| SNS Topic | arn:aws:sns:eu-central-1:734849394099:finops-cost-alerts-sandbox |
| AWS Budget | finops-monthly-budget-sandbox ($50.00/month, Healthy) |
| Config S3 Bucket | finops-config-audit-734849394099 |
| Config Recorder | finops-config-recorder |
| Config Rule 1 | required-tags-cost-center |
| Config Rule 2 | ec2-ebs-volume-attached |
| Config Rule 3 | eip-attached |
| Config Rule 4 | approved-ec2-instance-types |

### Compute-Optimized ASG (compute_optimized module)

| Resource | Value |
|---|---|
| ASG Name | finops-mixed-asg-sandbox |
| ASG ARN | arn:aws:autoscaling:eu-central-1:734849394099:autoScalingGroup:c8c2b4ef-d103-4d2b-94fa-6584dca2f42f:autoScalingGroupName/finops-mixed-asg-sandbox |
| Launch Template | lt-0f2a73c89bd0b6249 |
| Desired / Min / Max | 1 / 1 / 6 |
| On-Demand base | 1 instance |
| Spot percentage | 70% of scale-out |
| Status | At desired capacity |

---

## Verification Screenshots

The following screenshots were captured from the AWS Console on 2026-05-29:

1. **Gmail — SNS Subscription Confirmation** — Email received confirming subscription to `finops-cost-alerts-sandbox`
2. **EC2 Instances** — `idle-large-instance-demo` (t3.large, Running) and two `finops-mixed-asg-sandbox` instances visible
3. **Elastic IP Addresses** — `zombie-eip-1` and `zombie-eip-2` shown unassociated
4. **Auto Scaling Group Detail** — `finops-mixed-asg-sandbox` at desired capacity, scaling 1-6
5. **S3 Buckets** — `finops-config-audit-734849394099` created in eu-central-1
6. **Budget Detail** — `finops-monthly-budget-sandbox` Healthy, $7.16 of $50.00 spent
7. **Budgets Overview** — Budget status OK, Healthy

---

## SNS Alert Confirmation

Email received at `valens.niyonkuru@amalitechtraining.org` at 2:58 PM from `no-reply@sns.amazonaws.com` confirming subscription to:

```
arn:aws:sns:eu-central-1:734849394099:finops-cost-alerts-sandbox
```

Subscription was confirmed via the link in the email.
