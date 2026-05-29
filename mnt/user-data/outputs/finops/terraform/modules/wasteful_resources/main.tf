# ============================================================
#  Module: wasteful_resources
#  Creates intentionally "wasteful" resources to simulate the
#  zombie assets inherited from a reckless previous team.
#  These are used for the audit / detection demo ONLY.
#  Destroy with: terraform destroy -target=module.wasteful_resources
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

# ── 1. Unattached EBS Volumes ────────────────────────────────
resource "aws_ebs_volume" "zombie" {
  count             = 3
  availability_zone = "${var.aws_region}a"
  size              = 20 + (count.index * 10)   # 20 GB, 30 GB, 40 GB
  type              = "gp3"

  tags = {
    Name       = "zombie-ebs-${count.index + 1}"
    CostCenter = "UNTAGGED"   # Intentionally wrong — triggers Config rule
    Purpose    = "demo-waste"
  }
}

# ── 2. Unassociated Elastic IPs ──────────────────────────────
resource "aws_eip" "zombie" {
  count  = 2
  domain = "vpc"

  tags = {
    Name       = "zombie-eip-${count.index + 1}"
    Purpose    = "demo-waste"
  }
}

# ── 3. Idle Large EC2 Instance ───────────────────────────────
resource "aws_instance" "idle_large" {
  ami           = data.aws_ami.amazon_linux.id
  instance_type = var.idle_instance_type
  subnet_id     = var.subnet_id

  # No workload — CPU will sit near 0 %
  user_data = base64encode(<<-EOF
    #!/bin/bash
    echo "Idle demo instance — no workload" > /tmp/idle.txt
  EOF
  )

  tags = {
    Name       = "idle-large-instance-demo"
    CostCenter = "UNTAGGED"   # Intentionally wrong
    Purpose    = "demo-waste"
  }
}
