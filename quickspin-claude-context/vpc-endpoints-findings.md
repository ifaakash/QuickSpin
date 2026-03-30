# VPC Endpoints — Terraform Findings

**Source directory:** `/Users/aakashmac/DevOps/Github/Terraform`
**Date:** 2026-03-31

---

## Overview

Three **Interface VPC Endpoints** are defined for AWS Systems Manager (SSM). All are in the `Networking` module at:

```
Terraform/Networking/networking/vpc-endpoints.tf
```

---

## Defined VPC Endpoints

| Resource | Service | Subnet | Private DNS |
|---|---|---|---|
| `aws_vpc_endpoint.ssm` | `com.amazonaws.us-east-1.ssm` | private | true |
| `aws_vpc_endpoint.ssm_messages` | `com.amazonaws.us-east-1.ssmmessages` | private | true |
| `aws_vpc_endpoint.ec2_messages` | `com.amazonaws.us-east-1.ec2messages` | private | true |

### Purpose
- **ssm** — Parameter Store access and document retrieval
- **ssmmessages** — Session Manager communications
- **ec2messages** — EC2 command execution via SSM Agent

---

## Security Group

Resource: `aws_security_group.endpoint_sg` — `${var.prefix}-vpc-endpoints-sg`

- **Ingress:** Port 443 (TCP) from the main EC2 instance security group (`aws_security_group.main`)
- **Egress:** All traffic (0.0.0.0/0)

All three endpoints share this security group.

---

## Network Placement

- **VPC:** `aws_vpc.main`
- **Subnets:** `aws_subnet.private` only (not in public subnets)
- **Region hardcoded:** `us-east-1` in all service names

---

## Cross-Module Usage

| Module | Uses VPC endpoints? | Notes |
|---|---|---|
| `Networking/networking` | Yes — defines them | vpc-endpoints.tf |
| `EC2` | No direct reference | Implicitly benefits via private DNS |
| `Bastion` | No direct reference | Uses SSM Parameter Store data source |
| `IAM` | No direct reference | Uses SSM Parameter Store resource for key pairs |

---

## Gaps / Observations

1. **No outputs exported** — VPC endpoint IDs/ARNs are not exported from the networking module or parent module. If other modules ever need to reference them directly, outputs would need to be added.
2. **Region hardcoded** — All three service names embed `us-east-1`. Deploying to another region would require parameterizing this.
3. **Single subnet** — Endpoints are only in one private subnet. For high availability, deploying across multiple AZs (multiple subnets) is recommended.
4. **S3/ECR endpoints absent** — No Gateway endpoint for S3 or Interface endpoints for ECR. If instances pull container images or access S3 without NAT, traffic would route over the internet.
