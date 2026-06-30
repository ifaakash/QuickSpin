# QuickSpin & Terraform Workspace Guide

Welcome! This workspace contains two integrated subsystems designed to provision and configure AWS infrastructure:
1. **QuickSpin (`QuickSpin/`)**: An orchestrator and configuration tool that provisions custom AWS EC2 instances (based on a declarative YAML config) and configures them securely using Ansible over AWS Systems Manager (SSM).
2. **Terraform Modules (`Terraform/`)**: A collection of reusable Infrastructure-as-Code (IaC) modules (Networking, Bastion, IAM, NIC, and EC2) that serve as the foundational infrastructure source.

This file provides context on project architecture, workflows, operational commands, and coding conventions to ensure consistent development.

---

## 1. Project Overview & Architecture

### High-Level Workflow
```
[ quickspin.yml ] (Declarative user configuration)
       │
       ▼ (python/yaml-to-json.py)
[ IaC/terraform.tfvars.json ] (Flat representation of instances)
       │
       ▼ (Terraform Apply / remote modules)
[ AWS Infrastructure ] (VPC, Security Groups, IAM Profile, EC2)
       │
       ▼ (Ansible inventory_aws.aws_ec2.yml dynamically scans tag:Packages)
[ Dynamic Ansible Inventory ] (Targets specific instances with their packages)
       │
       ▼ (Ansible Playbooks via SSM Connection - no SSH keys!)
[ Target Instance Configuration ] (Packages like nginx installed securely)
```

### Subsystems Breakdown

#### A. QuickSpin (`QuickSpin/`)
* **Purpose**: Orchestrates the setup of a dynamic number of public/private instances with pre-configured software.
* **Core Technologies**: Terraform (IaC client), Python 3.13 (config flattening), Ansible (configuration management), AWS Systems Manager (SSM).
* **Connection Security**: QuickSpin uses **SSM Session Manager (over HTTPS)** rather than public SSH keypairs. Target instances run the SSM Agent and are placed securely behind VPC interface endpoints, completely avoiding exposed SSH ports.

#### B. Terraform Modules (`Terraform/`)
* **Purpose**: Houses the underlying modular blueprints used for provisioning AWS resources.
* **Key Modules**:
  * `Networking/`: Sets up the VPC, public/private subnets, Elastic IPs, route tables, security groups, and crucial SSM Interface Endpoints (`ssm`, `ssmmessages`, `ec2messages`).
  * `NIC/`: Provisions and manages Elastic Network Interfaces (ENIs).
  * `Bastion/`: Sets up a secure bastion host in the public subnet.
  * `IAM/`: Provisions the IAM role, Instance Profile containing AmazonSSMManagedInstanceCore permissions, and public keypair store.
  * `EC2/`: Core module managing instance creations.

---

## 2. Key Directories & File Reference

### `/workspace/QuickSpin/`
* `quickspin.yml`: Declarative definition of instances, types, subnet states (public/private), and target packages to install.
* `python/yaml-to-json.py`: Converts `quickspin.yml` properties to flat Terraform variables format.
* `IaC/`: Main Terraform deployment configuration. Connects to modules via remote GitHub references (`https://github.com/ifaakash/Terraform`).
* `Ansible/`: Configuration management playbooks and roles:
  * `ansible.cfg`: Sets paths, callback plugins, and enables the `amazon.aws.aws_ec2` inventory plugin.
  * `inventory_aws.aws_ec2.yml`: Dynamic AWS EC2 inventory mapping EC2 tag key-values to Ansible vars (converting the `Packages` tag list to the `quickspin_packages` list).
  * `roles/packages/`: The Ansible role mapping to RedHat (`yum`) and Debian (`apt`) package installers.

### `/workspace/Terraform/`
* `Networking/`: Configures VPC, public/private subnets, routing, and SSM endpoint SG.
* `Bastion/`: Bastion instance definition.
* `IAM/`: IAM instance profile allowing SSM connection.
* `EC2/`: AWS instance resources with optional tags mapping.

---

## 3. Building, Running, and Deploying

### Prerequisites
* Python 3.13+ with PyYAML.
* Terraform v1.5+.
* Ansible with `amazon.aws` and `community.aws` collections installed.
* AWS CLI and AWS Session Manager Plugin (for local Ansible/SSM verification).

### Step-by-Step Operations

#### 1. Configuration Compilation
Compile the declarative user configurations (`quickspin.yml`) into Terraform variables:
```bash
cd QuickSpin/python
python yaml-to-json.py
# This generates QuickSpin/python/terraform.tfvars.json
# Move it to the IaC directory:
mv terraform.tfvars.json ../IaC/
```

#### 2. Infrastructure Deployment
Apply the generated configurations to deploy the AWS cloud resources:
```bash
cd QuickSpin/IaC
terraform init
terraform plan
terraform apply --auto-approve
```

#### 3. Configuration Management (Ansible)
Run Ansible via AWS SSM to configure packages on the running EC2 instances:
```bash
cd QuickSpin/Ansible
# Export path to local ansible.cfg if necessary
export ANSIBLE_CONFIG=$(pwd)/ansible.cfg

# Test dynamic inventory retrieval
ansible-inventory -i inventory_aws.aws_ec2.yml --list

# Execute the playbook
ansible-playbook -i inventory_aws.aws_ec2.yml ansible-instruction.yml
```

#### 4. Infrastructure Cleanup
Tear down the deployed AWS resources to prevent extra costs:
```bash
cd QuickSpin/IaC
terraform destroy --auto-approve
```

---

## 4. Development & Coding Conventions

### A. Infrastructure-as-Code (Terraform)
* **Modular Composition**: Prefer composing infrastructure through explicit variables and inputs.
* **Tagging Strategy**: All resources MUST inherit `default_tags` and include the `"Project" = "QuickSpin"` tag. This is how the dynamic Ansible inventory filters targets.
* **Instance Tags**: When creating instances, specify the package tag in the following format:
  ```hcl
  default_tags = merge(
    { "Name"     = "${var.prefix}-private-instance" },
    { "Packages" = "${each.value.packages}" },
    var.default_tags
  )
  ```
* **Dependency Explicitly**: Use `depends_on` when resources rely on sub-networking components (like NICs or security rules) being fully provisioned.

### B. Configuration Management (Ansible)
* **OS Portability**: Multi-distro compatibility is mandatory. Playbooks and roles must query `ansible_os_family` and support both RedHat (`yum`) and Debian (`apt`) package managers:
  ```yaml
  - name: Install package ( Debian )
    ansible.builtin.apt:
      name: "{{ quickspin_packages }}"
      state: present
      update_cache: yes
    when: ansible_os_family == "Debian"
  ```
* **Post-Install Verification**: Always invoke handlers or assertions to verify the presence of newly installed applications:
  ```yaml
  # roles/packages/handlers/main.yml
  - name: Verify packages
    ansible.builtin.command: "which {{ item }}"
    loop: "{{ quickspin_packages }}"
    changed_when: false
    failed_when: false
  ```
* **Namespace Isolation**: Prefix custom Ansible variables with `quickspin_` to avoid conflicts.
* **Secure Connections**: Do NOT write standard SSH configuration blocks. All dynamic inventories must compose the SSM connector variables:
  ```yaml
  compose:
    ansible_connection: "'community.aws.aws_ssm'"
    ansible_host: instance_id
    ansible_python_interpreter: "'/usr/bin/python3'"
  ```

### C. Python Scripting
* Use `yaml.safe_load` for parsing config inputs.
* Maintain flat JSON outputs matching the strict schema defined in `IaC/variables.tf`.
* When list variables are passed, join them into comma-separated strings inside the JSON file.

---

## 5. Gemini CLI Commands
Use these commands inside your terminal session to inspect and refresh this workspace context:
* `/memory show` — See all loaded instructions and workspace configs.
* `/memory reload` — Reload memory context after editing files.
