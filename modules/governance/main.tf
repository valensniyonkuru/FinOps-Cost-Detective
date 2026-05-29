# ============================================================
#  Module: governance
#  Deploys:
#   • SNS topic + email subscription for all alerts
#   • AWS Budget with forecast and actual-spend alerts
#   • S3 bucket for AWS Config delivery
#   • AWS Config recorder + delivery channel
#   • Config rule: required-tags (CostCenter enforcement)
#   • Config rule: ec2-ebs-volume-attached
#   • Config rule: eip-attached
# ============================================================

# ── SNS Topic ────────────────────────────────────────────────
resource "aws_sns_topic" "finops_alerts" {
  name = "finops-cost-alerts-${var.environment}"

  tags = {
    Name = "finops-cost-alerts-${var.environment}"
  }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.finops_alerts.arn
  protocol  = "email"
  endpoint  = var.sns_subscription_email
}

# ── AWS Budget ───────────────────────────────────────────────
resource "aws_budgets_budget" "monthly" {
  name              = "finops-monthly-budget-${var.environment}"
  budget_type       = "COST"
  limit_amount      = tostring(var.budget_limit_amount)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2025-01-01_00:00"

  # Alert 1: Actual spend > 80 % of limit
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.budget_alert_threshold
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = [aws_sns_topic.finops_alerts.arn]
    subscriber_email_addresses = [var.owner_email]
  }

  # Alert 2: Forecasted spend > 100 % of limit
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_sns_topic_arns  = [aws_sns_topic.finops_alerts.arn]
    subscriber_email_addresses = [var.owner_email]
  }
}

# ── S3 Bucket for AWS Config ──────────────────────────────────
resource "aws_s3_bucket" "config" {
  bucket        = var.config_s3_bucket_name
  force_destroy = true   # Allow destroy in sandbox

  tags = {
    Name    = var.config_s3_bucket_name
    Purpose = "aws-config-delivery"
  }
}

resource "aws_s3_bucket_versioning" "config" {
  bucket = aws_s3_bucket.config.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "config" {
  bucket = aws_s3_bucket.config.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "config" {
  bucket                  = aws_s3_bucket.config.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_policy" "config" {
  bucket = aws_s3_bucket.config.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AWSConfigBucketPermissionsCheck"
        Effect = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action   = "s3:GetBucketAcl"
        Resource = "arn:aws:s3:::${var.config_s3_bucket_name}"
        Condition = {
          StringEquals = { "AWS:SourceAccount" = data.aws_caller_identity.current.account_id }
        }
      },
      {
        Sid    = "AWSConfigBucketDelivery"
        Effect = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action   = "s3:PutObject"
        Resource = "arn:aws:s3:::${var.config_s3_bucket_name}/AWSLogs/${data.aws_caller_identity.current.account_id}/Config/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"     = "bucket-owner-full-control"
            "AWS:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# ── IAM Role for AWS Config ───────────────────────────────────
resource "aws_iam_role" "config" {
  name = "aws-config-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "config.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "config_managed" {
  role       = aws_iam_role.config.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWS_ConfigRole"
}

# ── AWS Config Recorder & Delivery Channel ────────────────────
resource "aws_config_configuration_recorder" "main" {
  name     = "finops-config-recorder"
  role_arn = aws_iam_role.config.arn

  recording_group {
    all_supported                 = true
    include_global_resource_types = true
  }
}

resource "aws_config_delivery_channel" "main" {
  name           = "finops-config-delivery"
  s3_bucket_name = aws_s3_bucket.config.bucket
  sns_topic_arn  = aws_sns_topic.finops_alerts.arn

  depends_on = [aws_config_configuration_recorder.main]
}

resource "aws_config_configuration_recorder_status" "main" {
  name       = aws_config_configuration_recorder.main.name
  is_enabled = true

  depends_on = [aws_config_delivery_channel.main]
}

# ── Config Rule 1: Required Tags (CostCenter) ────────────────
resource "aws_config_config_rule" "required_tags" {
  name = "required-tags-cost-center"

  source {
    owner             = "AWS"
    source_identifier = "REQUIRED_TAGS"
  }

  input_parameters = jsonencode({
    tag1Key   = "CostCenter"
    tag2Key   = "Environment"
    tag3Key   = "Owner"
  })

  scope {
    compliance_resource_types = [
      "AWS::EC2::Instance",
      "AWS::EC2::Volume",
      "AWS::RDS::DBInstance",
      "AWS::S3::Bucket",
    ]
  }

  depends_on = [aws_config_configuration_recorder_status.main]
}

# ── Config Rule 2: Unattached EBS Volumes ────────────────────
resource "aws_config_config_rule" "ebs_attached" {
  name = "ec2-ebs-volume-attached"

  source {
    owner             = "AWS"
    source_identifier = "EC2_VOLUME_INUSE_CHECK"
  }

  depends_on = [aws_config_configuration_recorder_status.main]
}

# ── Config Rule 3: Unattached Elastic IPs ────────────────────
resource "aws_config_config_rule" "eip_attached" {
  name = "eip-attached"

  source {
    owner             = "AWS"
    source_identifier = "EIP_ATTACHED"
  }

  depends_on = [aws_config_configuration_recorder_status.main]
}

# ── Config Rule 4: Approved Instance Types ───────────────────
resource "aws_config_config_rule" "approved_instance_types" {
  name = "approved-ec2-instance-types"

  source {
    owner             = "AWS"
    source_identifier = "DESIRED_INSTANCE_TYPE"
  }

  input_parameters = jsonencode({
    instanceType = "t3.micro,t3.small,t3.medium,t3.large,m5.large,m5.xlarge,c5.large,c5.xlarge"
  })

  depends_on = [aws_config_configuration_recorder_status.main]
}
