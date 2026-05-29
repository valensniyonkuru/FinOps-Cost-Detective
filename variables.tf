variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (sandbox, staging, production)"
  type        = string
  default     = "sandbox"

  validation {
    condition     = contains(["sandbox", "staging", "production"], var.environment)
    error_message = "Environment must be sandbox, staging, or production."
  }
}

variable "owner_email" {
  description = "Email address of the resource owner (for alerts and tagging)"
  type        = string
}

variable "default_cost_center" {
  description = "Default CostCenter tag value applied to all resources"
  type        = string
  default     = "finops-audit"
}

variable "budget_limit_amount" {
  description = "Monthly budget limit in USD that triggers alerts"
  type        = number
  default     = 50
}

variable "budget_alert_threshold" {
  description = "Percentage of budget that triggers the first alert"
  type        = number
  default     = 80
}

# ── Wasteful Resources (demo baseline) ─────────────────────────────────────
variable "create_wasteful_resources" {
  description = "Set to true to create demo zombie assets for the audit scenario"
  type        = bool
  default     = true
}

variable "idle_instance_type" {
  description = "EC2 instance type for the demo idle large instance"
  type        = string
  default     = "t3.large"
}

# ── Compute Optimized (ASG) ─────────────────────────────────────────────────
variable "vpc_id" {
  description = "VPC ID where the Auto Scaling Group will be deployed"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for the ASG (use at least 2 AZs)"
  type        = list(string)
}

variable "asg_on_demand_base" {
  description = "Number of On-Demand instances to maintain as base capacity"
  type        = number
  default     = 1
}

variable "asg_spot_percentage" {
  description = "Percentage of scale-out capacity fulfilled by Spot Instances (0-100)"
  type        = number
  default     = 70
}

variable "asg_min_size" {
  description = "Minimum number of instances in the ASG"
  type        = number
  default     = 1
}

variable "asg_max_size" {
  description = "Maximum number of instances in the ASG"
  type        = number
  default     = 6
}

variable "asg_desired_capacity" {
  description = "Desired number of instances in the ASG"
  type        = number
  default     = 2
}

# ── Governance ──────────────────────────────────────────────────────────────
variable "config_s3_bucket_name" {
  description = "S3 bucket name for AWS Config delivery channel (must be globally unique)"
  type        = string
}

variable "sns_subscription_email" {
  description = "Email address to subscribe to the budget and Config SNS topics"
  type        = string
}
