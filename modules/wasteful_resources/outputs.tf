output "ebs_volume_ids" {
  description = "IDs of the demo unattached EBS volumes"
  value       = aws_ebs_volume.zombie[*].id
}

output "elastic_ip_ids" {
  description = "Allocation IDs of the demo unassociated Elastic IPs"
  value       = aws_eip.zombie[*].allocation_id
}

output "idle_instance_id" {
  description = "Instance ID of the demo idle large EC2 instance"
  value       = aws_instance.idle_large.id
}
