output "sns_topic_arn" {
  description = "ARN of the SNS topic for alerts"
  value       = aws_sns_topic.finops_alerts.arn
}

output "budget_name" {
  description = "Name of the AWS Budget"
  value       = aws_budgets_budget.monthly.name
}

output "config_s3_bucket" {
  description = "S3 bucket for AWS Config delivery"
  value       = aws_s3_bucket.config.bucket
}
