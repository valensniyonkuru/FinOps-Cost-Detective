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

output "iam_deny_policy_arn" {
  description = "ARN of the IAM policy that denies EC2 launches without required tags"
  value       = aws_iam_policy.deny_ec2_without_cost_center.arn
}

output "iam_restricted_group_name" {
  description = "IAM group name that has the deny policy attached"
  value       = aws_iam_group.finops_restricted.name
}
