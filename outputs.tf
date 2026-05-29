output "governance_sns_topic_arn" {
  description = "ARN of the SNS topic used for budget and Config alerts"
  value       = module.governance.sns_topic_arn
}

output "governance_budget_name" {
  description = "Name of the AWS Budget created for spend monitoring"
  value       = module.governance.budget_name
}

output "governance_config_s3_bucket" {
  description = "S3 bucket where AWS Config snapshots are delivered"
  value       = module.governance.config_s3_bucket
}

output "asg_name" {
  description = "Name of the Mixed-Instance Auto Scaling Group"
  value       = module.compute_optimized.asg_name
}

output "asg_arn" {
  description = "ARN of the Mixed-Instance Auto Scaling Group"
  value       = module.compute_optimized.asg_arn
}

output "launch_template_id" {
  description = "ID of the EC2 Launch Template used by the ASG"
  value       = module.compute_optimized.launch_template_id
}

output "wasteful_ebs_volume_ids" {
  description = "IDs of the demo unattached EBS volumes (zombie assets)"
  value       = var.create_wasteful_resources ? module.wasteful_resources[0].ebs_volume_ids : []
}

output "wasteful_elastic_ip_ids" {
  description = "Allocation IDs of the demo unassociated Elastic IPs"
  value       = var.create_wasteful_resources ? module.wasteful_resources[0].elastic_ip_ids : []
}

output "wasteful_idle_instance_id" {
  description = "Instance ID of the demo idle large EC2 instance"
  value       = var.create_wasteful_resources ? module.wasteful_resources[0].idle_instance_id : null
}
