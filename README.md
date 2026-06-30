# QuickSpin

[![QuickSpin Deployment](https://github.com/ifaakash/QuickSpin/actions/workflows/deployment.yml/badge.svg)](https://github.com/ifaakash/QuickSpin/actions/workflows/deployment.yml)
[![Built with Gemini](https://img.shields.io/badge/Built%20with-Gemini-blue.svg)](https://gemini.google.com)

QuickSpin is a lightweight infrastructure orchestration tool designed to abstract the complexities of provisioning and configuring secure AWS EC2 environments. It bridges the gap between simple declarative configuration and robust infrastructure-as-code by translating a user-friendly `quickspin.yml` file into Terraform configurations and Ansible playbooks.

## Project Summary
QuickSpin automatically provisions AWS virtual machines and configures them via Ansible. By leveraging AWS Systems Manager (SSM) Session Manager, QuickSpin ensures that all instances are configured securely through VPC interface endpoints without ever exposing SSH (port 22) to the public internet.

## Use Cases
- **Developer Environments**: Quickly spin up fully configured temporary environments for testing and development.
- **Infrastructure Vending**: Provide a self-service pipeline for developers to request AWS instances via GitHub Pull Requests.
- **Secure Automation**: Automate VM spin-ups with pre-installed software packages across different OS distributions (Debian/RedHat) using a secure, zero-open-port security posture.

## How to Use

### 1. Configure
Define your desired infrastructure in the `quickspin.yml` file located at the root of the project:
```yaml
instances:
  - ami: "ami-0360c520857e3138f"
    instance_type: "t2.micro"
    is_public: false
    packages:
      - nginx
```

### 2. Deployment via CI/CD (Recommended)
The easiest way to deploy is using the included GitHub Actions pipeline.

**Prerequisites for CI/CD:**
Before running the pipeline, you must configure OpenID Connect (OIDC) authentication between AWS and GitHub:
1. **Identity Provider:** Set up a GitHub OIDC Identity Provider in your AWS IAM console.
2. **IAM Role:** Create an AWS IAM role with the necessary permissions for Terraform to provision infrastructure. Configure its trust relationship to allow the GitHub OIDC provider to assume it.
3. **GitHub Secrets:** Fetch the ARN of the newly created IAM role and add it as a Repository Secret in your GitHub settings named `AWS_ROLE_ARN`. The workflow automatically consumes this secret to securely authenticate without using long-lived access keys.

**Deployment Steps:**
1. Push your changes to the `main` branch.
2. The pipeline will automatically:
   - Parse `quickspin.yml`.
   - Provision the AWS infrastructure via Terraform.
   - Configure the instances with the specified packages using Ansible over SSM.
3. To tear down the infrastructure, trigger the GitHub Actions workflow manually and select **"Destroy the infra created"**.

### 3. Local Deployment
If you prefer to deploy from your local terminal:

**Prerequisites:** Python 3.13+, Terraform, Ansible (with `amazon.aws` collection), and AWS CLI configured.

```bash
# 1. Compile Configuration
cd QuickSpin/python
pip install -r requirements.txt
python yaml-to-json.py
mv terraform.tfvars.json ../IaC/

# 2. Deploy Infrastructure
cd ../IaC
terraform init
terraform apply

# 3. Configure via Ansible
cd ../Ansible
ansible-inventory -i inventory_aws.aws_ec2.yml --list
ansible-playbook -i inventory_aws.aws_ec2.yml ansible-instruction.yml

# 4. Clean Up
cd ../IaC
terraform destroy
```
