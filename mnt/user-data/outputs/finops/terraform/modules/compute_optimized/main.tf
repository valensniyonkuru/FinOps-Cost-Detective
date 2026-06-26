# ============================================================
#  Module: compute_optimized
#  Creates a Mixed-Instance Auto Scaling Group combining:
#   • On-Demand base capacity  (guaranteed, stable)
#   • Spot Instance scaling    (up to 70 % cheaper)
#
#  Instance family diversity across 3 types reduces Spot
#  interruption risk while maintaining compute equivalence.
# ============================================================

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── Security Group ───────────────────────────────────────────
resource "aws_security_group" "asg" {
  name        = "finops-asg-sg-${var.environment}"
  description = "Security group for the FinOps demo ASG"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP from VPC"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "finops-asg-sg-${var.environment}" }
}

# ── IAM Instance Profile ─────────────────────────────────────
resource "aws_iam_role" "asg_instance" {
  name = "finops-asg-instance-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.asg_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "asg" {
  name = "finops-asg-profile-${var.environment}"
  role = aws_iam_role.asg_instance.name
}

# ── Launch Template ──────────────────────────────────────────
resource "aws_launch_template" "main" {
  name_prefix   = "finops-asg-lt-${var.environment}-"
  image_id      = data.aws_ami.amazon_linux.id
  instance_type = "t3.medium" # Default; overridden by mixed-instances policy

  iam_instance_profile { arn = aws_iam_instance_profile.asg.arn }

  vpc_security_group_ids = [aws_security_group.asg.id]

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 — security best practice
    http_put_response_hop_limit = 1
  }

  monitoring { enabled = true }

  user_data = base64encode(<<-EOF
    #!/bin/bash
    yum update -y
    yum install -y httpd
    systemctl enable httpd
    systemctl start httpd
    INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
    LIFECYCLE=$(curl -s http://169.254.169.254/latest/meta-data/instance-life-cycle)
    AZ=$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone)
    echo "<h1>FinOps Demo — Cost-Optimized ASG</h1>
    <p>Instance ID: $INSTANCE_ID</p>
    <p>Lifecycle: <strong>$LIFECYCLE</strong></p>
    <p>AZ: $AZ</p>" > /var/www/html/index.html
  EOF
  )

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name       = "finops-asg-instance-${var.environment}"
      CostCenter = var.cost_center
      ManagedBy  = "asg-mixed-instances"
    }
  }

  tag_specifications {
    resource_type = "volume"
    tags = {
      Name       = "finops-asg-volume-${var.environment}"
      CostCenter = var.cost_center
    }
  }

  lifecycle { create_before_destroy = true }
}

# ── Auto Scaling Group (Mixed Instances Policy) ──────────────
resource "aws_autoscaling_group" "main" {
  name                      = "finops-mixed-asg-${var.environment}"
  min_size                  = var.asg_min_size
  max_size                  = var.asg_max_size
  desired_capacity          = var.asg_desired_capacity
  vpc_zone_identifier       = var.subnet_ids
  health_check_type         = "EC2"
  health_check_grace_period = 300
  default_cooldown          = 300

  mixed_instances_policy {
    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.main.id
        version            = "$Latest"
      }

      # Instance diversity reduces Spot interruption risk
      override {
        instance_type     = "t3.medium"
        weighted_capacity = "1"
      }
      override {
        instance_type     = "t3a.medium"
        weighted_capacity = "1"
      }
      override {
        instance_type     = "t2.medium"
        weighted_capacity = "1"
      }
      override {
        instance_type     = "m5.large"
        weighted_capacity = "2"
      }
      override {
        instance_type     = "m5a.large"
        weighted_capacity = "2"
      }
    }

    instances_distribution {
      # Keep N On-Demand instances as always-on base capacity
      on_demand_base_capacity = var.asg_on_demand_base

      # After the base, fill (100 - spot_percentage)% with OD, rest with Spot
      on_demand_percentage_above_base_capacity = 100 - var.asg_spot_percentage

      # Spot allocation: lowest-price across pools maximises savings
      spot_allocation_strategy = "capacity-optimized"

      # Maximum Spot price = On-Demand price (never pay more than OD)
      spot_max_price = ""
    }
  }

  # Instance refresh for zero-downtime rolling updates
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 120
    }
  }

  tag {
    key                 = "Name"
    value               = "finops-mixed-asg-${var.environment}"
    propagate_at_launch = true
  }

  tag {
    key                 = "CostCenter"
    value               = var.cost_center
    propagate_at_launch = true
  }

  lifecycle { create_before_destroy = true }
}

# ── Scale-Out Policy (CPU > 70 %) ────────────────────────────
resource "aws_autoscaling_policy" "scale_out" {
  name                   = "finops-asg-scale-out"
  autoscaling_group_name = aws_autoscaling_group.main.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = 70.0
  }
}
