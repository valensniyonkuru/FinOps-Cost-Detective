# FinOps Cost Detective

> **Audit, govern, and optimise an inherited AWS account with measurable, documented savings.**

This repository contains the complete deliverable for the "Cost Detective" FinOps audit challenge: Terraform infrastructure, Python automation scripts, and full documentation covering zombie asset detection, cost governance, and Spot-based compute optimisation.

---

## Project Structure

```
finops/
├── terraform/
│   ├── providers.tf                   # AWS provider + default tags
│   ├── variables.tf                   # Root input variables
│   ├── main.tf                        # Root module orchestration
│   ├── outputs.tf                     # Key resource IDs and ARNs
│   ├── terraform.tfvars.example       # Variable template
│   └── modules/
│       ├── wasteful_resources/        # Zombie asset baseline (demo)
│       ├── governance/                # Budgets, SNS, Config rules, S3
│       └── compute_optimized/         # Mixed-Instance ASG (Spot + On-Demand)
├── scripts/
│   ├── requirements.txt
│   ├── find_zombie_assets.py          # Full zombie asset scanner
│   ├── gc_ebs_volumes.py              # Unattached EBS garbage collector
│   └── generate_cost_report.py        # Cost Explorer FinOps report
├── docs/
│   ├── AUDIT_REPORT.md                # Findings, remediation log, evidence
│   ├── TAGGING_POLICY.md              # Mandatory tags, SCP, enforcement
│   └── COST_OPTIMIZATION_GUIDE.md    # End-to-end FinOps playbook
├── audit-evidence/                    # Raw evidence collected during audit
└── screenshots/                       # AWS Console screenshots
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
cd scripts/
pip install -r requirements.txt
```

### 2. Scan for zombie assets (read-only, safe)

```bash
python scripts/find_zombie_assets.py --region us-east-1
```

### 3. Deploy governance controls

```bash
cd terraform/
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars

terraform init
terraform plan
terraform apply -target=module.governance
```

### 4. Deploy the demo zombie resources (optional)

```bash
terraform apply -target=module.wasteful_resources
# Then scan again to see them appear in results
python scripts/find_zombie_assets.py
```

### 5. Clean up unattached EBS volumes

```bash
# Dry-run (no changes)
python scripts/gc_ebs_volumes.py

# Execute (snapshot + delete)
python scripts/gc_ebs_volumes.py --execute --audit-log gc_audit.json
```

### 6. Generate cost report

```bash
python scripts/generate_cost_report.py --format markdown --output docs/cost_report.md
```

### 7. Deploy cost-optimised ASG

```bash
cd terraform/
terraform apply -target=module.compute_optimized
```

---

## Key Findings (Audit Summary)

| Category | Monthly Waste Found | Status |
|----------|--------------------|---------| 
| Unattached EBS volumes | $8.00 | ✅ Deleted |
| Unassociated Elastic IPs | $7.20 | ✅ Released |
| Idle large EC2 instance | $60.74 | 🔄 Rightsizing |
| Unused Load Balancer | $16.20 | ✅ Deleted |
| Stopped RDS instance | $2.30 | ✅ Deleted |
| Orphaned snapshots | $21.50 | ✅ Cleaned |
| On-Demand-only ASG | $60.48 | ✅ Migrated to Spot mix |
| **Total** | **$176.42** | **$146.86/mo saved** |

---

## Documentation

| Document | Description |
|----------|-------------|
| [AUDIT_REPORT.md](docs/AUDIT_REPORT.md) | Full audit findings with evidence references |
| [TAGGING_POLICY.md](docs/TAGGING_POLICY.md) | Tag taxonomy, SCP, Config enforcement |
| [COST_OPTIMIZATION_GUIDE.md](docs/COST_OPTIMIZATION_GUIDE.md) | End-to-end FinOps playbook |

---

## Teardown

```bash
# Remove demo zombie assets
cd terraform/
terraform destroy -target=module.wasteful_resources

# Remove everything
terraform destroy
```

---

## License

MIT — use freely, attribute appreciated.
