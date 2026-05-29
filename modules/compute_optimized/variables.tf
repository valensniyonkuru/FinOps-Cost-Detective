variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where the ASG will be deployed"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for the ASG"
  type        = list(string)
}

variable "asg_on_demand_base" {
  description = "Number of On-Demand instances to maintain as base capacity"
  type        = number
  default     = 1
}

variable "asg_spot_percentage" {
  description = "Percentage of scale-out capacity fulfilled by Spot Instances"
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

variable "cost_center" {
  description = "CostCenter tag value"
  type        = string
}
