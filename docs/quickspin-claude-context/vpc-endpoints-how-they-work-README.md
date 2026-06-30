# VPC Endpoints — How They Work Without Explicit References

**Date:** 2026-03-31

---

## Question

The SSM VPC endpoints were defined in Terraform but not exported in `outputs.tf`.
When Ansible connected to EC2 via SSM, were those endpoints actually used?

---

## Answer: Yes — Automatically

VPC endpoints are **transparent at the DNS/routing layer**. No application, playbook, or Terraform output needs to reference them by ID for traffic to flow through them.

---

## How It Works (Interface Endpoints with Private DNS)

```
EC2 Instance calls ssm.us-east-1.amazonaws.com
    |
    | DNS lookup inside VPC
    | (private_dns_enabled = true on the endpoint)
    v
Hostname resolves to the endpoint's private ENI IP
— NOT the public AWS IP
    |
    v
Traffic routes through the VPC endpoint
Never touches the internet or NAT gateway
```

The `private_dns_enabled = true` set on all three endpoints (`ssm`, `ssmmessages`, `ec2messages`) is the key.
It overrides the DNS resolution for those service hostnames **inside the VPC**, so any service — SSM Agent, Ansible, SDK calls — automatically uses the endpoint without any awareness of it.

---

## When Would You Actually Need Endpoint IDs in outputs.tf?

| Use Case | Needs endpoint ID? |
|---|---|
| Traffic routing through endpoint (our case) | **No** — DNS handles it |
| Attaching a resource policy to the endpoint | Yes |
| Referencing the endpoint in another Terraform root module | Yes |
| Gateway-type endpoints (S3, DynamoDB) needing route table entries | Yes — for the route resource |

---

## Summary

For our setup — interface endpoints with `private_dns_enabled = true`, used implicitly by the SSM Agent on EC2 — the `outputs.tf` omission is fine. The endpoints became active the moment Terraform provisioned them.
