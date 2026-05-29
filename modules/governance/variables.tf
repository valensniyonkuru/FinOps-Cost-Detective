variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "owner_email" {
  description = "Email address of the resource owner"
  type        = string
}

variable "budget_limit_amount" {
  description = "Monthly budget limit in USD"
  type        = number
}

variable "budget_alert_threshold" {
  description = "Percentage of budget that triggers the first alert"
  type        = number
}

variable "config_s3_bucket_name" {
  description = "S3 bucket name for AWS Config delivery channel"
  type        = string
}

variable "sns_subscription_email" {
  description = "Email address to subscribe to SNS alerts"
  type        = string
}
