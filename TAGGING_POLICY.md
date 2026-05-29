# AWS Tagging Policy

**Version:** 1.0  
**Owner:** FinOps Team  
**Effective Date:** 2025-07-15  
**Enforcement:** AWS Config + Service Control Policy  

---

## Purpose

Consistent resource tagging is the foundation of cloud financial management. Without tags, cost attribution is impossible, zombie assets go undetected, and engineering teams cannot be held accountable for their cloud spend. This policy defines the mandatory tag taxonomy, enforcement mechanism, and remediation process for non-compliant resources.

---

## Tag Taxonomy

### Mandatory Tags (enforced by Config rule + SCP)

| Tag Key | Description | Allowed Values | Example |
|---------|-------------|----------------|---------|
| `CostCenter` | Business unit or project bearing the cost | Any non-empty string | `platform-team`, `product-checkout`, `ml-infra` |
| `Environment` | Deployment environment | `sandbox`, `staging`, `production` | `production` |
| `Owner` | Email of the team or individual responsible | Valid email address | `platform@company.com` |

### Strongly Recommended Tags

| Tag Key | Description | Example |
|---------|-------------|---------|
| `Project` | Project or initiative name | `finops-audit`, `payments-v2` |
| `ManagedBy` | Provisioning method | `terraform`, `cdk`, `manual` |
| `ExpiresOn` | Scheduled termination date (for sandbox resources) | `2025-08-01` |
| `DataClassification` | Sensitivity level | `public`, `internal`, `confidential` |

### Reserved Tags (do not override)

| Tag Key | Set By | Purpose |
|---------|--------|---------|
| `aws:cloudformation:*` | CloudFormation | Stack tracking |
| `aws:autoscaling:*` | ASG | Instance lifecycle |

---

## Enforcement Architecture

### Layer 1: Service Control Policy (SCP)

Applied at the AWS Organization level to prevent launching EC2 instances without the `CostCenter` tag.

**Deploy to AWS Organizations > Policies > Service Control Policies:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyEC2WithoutCostCenter",
      "Effect": "Deny",
      "Action": [
        "ec2:RunInstances"
      ],
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {
        "Null": {
          "aws:RequestTag/CostCenter": "true"
        }
      }
    },
    {
      "Sid": "DenyEC2WithoutEnvironment",
      "Effect": "Deny",
      "Action": [
        "ec2:RunInstances"
      ],
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {
        "Null": {
          "aws:RequestTag/Environment": "true"
        }
      }
    },
    {
      "Sid": "DenyRDSWithoutCostCenter",
      "Effect": "Deny",
      "Action": [
        "rds:CreateDBInstance",
        "rds:RestoreDBInstanceFromDBSnapshot"
      ],
      "Resource": "*",
      "Condition": {
        "Null": {
          "aws:RequestTag/CostCenter": "true"
        }
      }
    }
  ]
}
```

**Test the SCP:**
```bash
# This should FAIL (no CostCenter tag)
aws ec2 run-instances \
  --image-id ami-0abcdef1234567890 \
  --instance-type t3.micro \
  --count 1

# This should SUCCEED (CostCenter tag present)
aws ec2 run-instances \
  --image-id ami-0abcdef1234567890 \
  --instance-type t3.micro \
  --count 1 \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=CostCenter,Value=platform-team},{Key=Environment,Value=sandbox},{Key=Owner,Value=me@company.com}]'
```

---

### Layer 2: AWS Config Rules

Deployed via the `governance` Terraform module. Rules run continuously and flag non-compliant resources.

| Rule | Resources Checked | Non-Compliance Action |
|------|------------------|----------------------|
| `required-tags-cost-center` | EC2, EBS, RDS, S3 | Flag + SNS alert |
| `ec2-ebs-volume-attached` | EBS volumes | Flag + SNS alert |
| `eip-attached` | Elastic IPs | Flag + SNS alert |
| `approved-ec2-instance-types` | EC2 instances | Flag + SNS alert |

**View compliance status:**
```bash
aws configservice describe-compliance-by-config-rule \
  --config-rule-names required-tags-cost-center
```

**List non-compliant resources:**
```bash
aws configservice get-compliance-details-by-config-rule \
  --config-rule-name required-tags-cost-center \
  --compliance-types NON_COMPLIANT \
  --query 'EvaluationResults[*].EvaluationResultIdentifier.EvaluationResultQualifier'
```

---

### Layer 3: Infrastructure-as-Code Standards

All Terraform modules **must** pass the `CostCenter`, `Environment`, and `Owner` tags through the root `default_tags` block in `providers.tf`. This is non-negotiable for any IaC-provisioned resource.

```hcl
# providers.tf — enforced default tags
provider "aws" {
  default_tags {
    tags = {
      CostCenter  = var.default_cost_center
      Environment = var.environment
      Owner       = var.owner_email
      ManagedBy   = "terraform"
    }
  }
}
```

**Pre-commit hook** — add to `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/gruntwork-io/pre-commit
    rev: v0.1.17
    hooks:
      - id: tflint
```

---

## Remediation Process for Non-Compliant Resources

When a resource is flagged as non-compliant:

1. **Alert fires** → SNS → email to `Owner` tag value (or team DL if missing)
2. **Grace period:** 72 hours to add missing tags
3. **Escalation:** If unresolved after 72h → automatic tagging with `CostCenter=unowned` and notification to FinOps team
4. **Final action:** If unresolved after 7 days and resource is not a production system → schedule for termination review

**Bulk tag remediation script:**
```bash
# Tag all untagged EC2 instances in a region
aws ec2 describe-instances \
  --filters "Name=tag-key,Values=!CostCenter" \
  --query 'Reservations[*].Instances[*].InstanceId' \
  --output text | xargs -I{} aws ec2 create-tags \
    --resources {} \
    --tags Key=CostCenter,Value=unowned Key=Owner,Value=finops-review@company.com
```

---

## Tagging for Sandbox / Temporary Resources

Resources with a finite lifespan **must** include the `ExpiresOn` tag. A Lambda function (not in scope for this audit) can be configured to terminate resources past their expiry date.

```bash
# Tag a sandbox instance with expiry
aws ec2 create-tags \
  --resources i-0abc123 \
  --tags Key=ExpiresOn,Value=2025-08-15 Key=CostCenter,Value=finops-sandbox
```

---

## Chargeback & Showback Model

With consistent `CostCenter` tagging, AWS Cost Explorer enables per-team cost attribution:

1. Open **Cost Explorer → Explore costs**
2. Group by **Tag: CostCenter**
3. Date range: Last month
4. Export as CSV for chargeback invoicing

Monthly chargeback report generated by: `python scripts/generate_cost_report.py --format markdown`

---

*This policy is reviewed quarterly. Submit changes via pull request to the `finops` repository.*
