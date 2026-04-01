# Ansible SSM Setup — Concepts & Design

**Source directory:** `/Users/aakashmac/DevOps/Github/QuickSpin/Ansible`
**Date:** 2026-03-31

---

## The Big Idea

Ansible manages EC2 instances **without SSH**. Instead of opening port 22 or using a bastion host, Ansible connects through **AWS Systems Manager (SSM)**. No key pairs, no open ports — IAM is the credential.

---

## Files

```
Ansible/
├── ansible.cfg                   # global Ansible configuration
├── inventory_aws.aws_ec2.yml     # dynamic inventory (queries AWS live)
└── ssm-playbook.yml              # smoke test playbook
```

---

## `ansible.cfg` — Global Configuration

```ini
[defaults]
inventory = inventory_aws.aws_ec2.yml   # points to the dynamic inventory file
host_key_checking = False               # silences SSH key warnings (irrelevant for SSM)
interpreter_python = auto               # Ansible auto-picks Python on the target
retry_files_enabled = False             # no .retry files on failure
callbacks_enabled = profile_tasks, timer  # prints task timing at end of each run

[inventory]
enable_plugins = amazon.aws.aws_ec2, yaml, ini  # registers the AWS EC2 inventory plugin
```

---

## `inventory_aws.aws_ec2.yml` — Dynamic Inventory

Instead of a hardcoded list of IPs, this file queries AWS live for running instances.

```yaml
plugin: amazon.aws.aws_ec2

regions:
  - us-east-1

filters:
  instance-state-name: running      # only running instances
  "tag:Project": QuickSpin          # only this project's instances

hostnames:
  - tag:Name                        # use EC2 Name tag as the Ansible hostname (stable, human-readable)

compose:
  ansible_connection: "'community.aws.aws_ssm'"        # connect via SSM, not SSH
  ansible_host: instance_id                            # target by EC2 instance ID (e.g. i-0abc123)
  ansible_python_interpreter: "'/usr/bin/python3'"
  ansible_aws_ssm_region: "'us-east-1'"
  ansible_aws_ssm_bucket_name: "'quickspin-ansible-ssm-staging'"
```

### Key Concepts

**Dynamic Inventory** — New EC2 instances tagged `Project=QuickSpin` automatically appear in inventory. No manual updates needed.

**`compose` block** — Sets per-host variables dynamically at runtime:
- `ansible_connection: community.aws.aws_ssm` — swaps the SSH transport for SSM
- `ansible_host: instance_id` — SSM identifies targets by instance ID, not IP address
- `ansible_aws_ssm_bucket_name` — SSM transport works by uploading the command payload to S3, executing it on the instance, and writing output back to S3. This is the staging bucket.

---

## `ssm-playbook.yml` — Smoke Test Playbook

```yaml
- name: Test connection to SSM managed instances
  hosts: all
  gather_facts: false

  tasks:
    - name: Run a simple command to verify connection and SSM Agent user
      ansible.builtin.command: whoami
      register: user_result

    - name: Print the user the command ran as
      ansible.builtin.debug:
        msg: "Connected to {{ inventory_hostname }} as user: {{ user_result.stdout }}"
```

Runs `whoami` on every instance and prints who it connected as (`ssm-user` or `root`). Confirms the entire chain works end-to-end.

---

## How It All Connects

```
Your Machine
    |
    | (AWS API — lists EC2 instances tagged Project=QuickSpin)
    v
Dynamic Inventory (aws_ec2 plugin)
    |
    | (for each instance: connect via SSM, not SSH)
    v
SSM VPC Endpoints  <-- defined in Terraform/Networking
(ssm, ssmmessages, ec2messages)
    |
    v
EC2 Instance (SSM Agent receives & executes command)
    |
    | (output uploaded to S3: quickspin-ansible-ssm-staging)
    v
Ansible reads result back from S3
```

The three VPC endpoints in Terraform (`ssm`, `ssmmessages`, `ec2messages`) are what make this work inside private subnets — traffic never leaves AWS.

---

## Why This Design

| Traditional SSH | This SSM Approach |
|---|---|
| Port 22 must be open | No open ports needed |
| Key pair management | IAM role is the credential |
| Static IP inventory | Dynamic inventory via tags |
| Breaks when IP changes | Uses instance ID — always stable |
| Needs bastion for private subnets | SSM reaches private instances natively |
