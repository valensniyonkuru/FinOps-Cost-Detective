variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "idle_instance_type" {
  description = "EC2 instance type for the demo idle large instance"
  type        = string
  default     = "t3.large"
}

variable "subnet_id" {
  description = "Subnet ID where the idle EC2 instance will be launched"
  type        = string
}
