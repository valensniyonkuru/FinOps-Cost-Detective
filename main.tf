# ============================================================
#  FinOps Cost Detective — Root Orchestration
#  Deploys three child modules:
#    1. wasteful_resources  – demo zombie assets for the audit
#    2. governance          – Budgets, SNS, Config rules, S3
#    3. compute_optimized   – Mixed-Instance ASG (Spot + OD)
# ============================================================

# ── 1. Zombie Asset Baseline (demo only) ────────────────────
module "wasteful_resources" {
  count  = var.create_wasteful_resources ? 1 : 0
  source = "./modules/wasteful_resources"

  environment         = var.environment
  idle_instance_type  = var.idle_instance_type
  subnet_id           = var.subnet_ids[0]
}

# ── 2. Governance ───────────────────────────────────────────
module "governance" {
  source = "./modules/governance"

  environment            = var.environment
  owner_email            = var.owner_email
  budget_limit_amount    = var.budget_limit_amount
  budget_alert_threshold = var.budget_alert_threshold
  config_s3_bucket_name  = var.config_s3_bucket_name
  sns_subscription_email = var.sns_subscription_email
}

# ── 3. Compute-Optimized ASG ────────────────────────────────
module "compute_optimized" {
  source = "./modules/compute_optimized"

  environment          = var.environment
  vpc_id               = var.vpc_id
  subnet_ids           = var.subnet_ids
  asg_on_demand_base   = var.asg_on_demand_base
  asg_spot_percentage  = var.asg_spot_percentage
  asg_min_size         = var.asg_min_size
  asg_max_size         = var.asg_max_size
  asg_desired_capacity = var.asg_desired_capacity
  cost_center          = var.default_cost_center
}
