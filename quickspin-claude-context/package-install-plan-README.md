# Package Installation Architecture — Design Decision

**Date:** 2026-03-31

---

## Problem

QuickSpin provisions EC2 instances via Terraform but does zero configuration on them. Need a way for users to define packages per instance and have them installed automatically.

---

## Design Decision: EC2 Tags as the Bridge

Packages are defined in `quickspin.yml` but Ansible discovers hosts via AWS tags. The bridge: **Terraform writes the package list as an EC2 tag, and Ansible reads it back.**

### Why EC2 Tags (over alternatives)?

| Option | Verdict |
|---|---|
| **A. EC2 tags** | Chosen. Flows through the existing pipeline (YAML → Python → tfvars → Terraform → Tags → Ansible compose). Zero new infrastructure. |
| B. Ansible reads quickspin.yml directly | Rejected. Mapping "which YAML instance = which discovered host" is fragile. |
| C. Generate host_vars from YAML | Rejected. Adds a build step and file generation complexity. |

### Tag format
```
Key: Packages
Value: "nginx,docker"    ← comma-separated, 256-char AWS limit
```

Ansible splits this back into a list via Jinja2 in the inventory `compose` block.

---

## Data Flow

```
quickspin.yml          →  packages: [nginx, docker]
yaml-to-json.py        →  "packages": "nginx,docker"
terraform.tfvars.json  →  packages = "nginx,docker"
Terraform EC2 tag      →  Packages = "nginx,docker"
Ansible compose        →  quickspin_packages = ["nginx", "docker"]
Ansible role           →  apt/yum install nginx docker
```

---

## Ansible Structure (Roles-based)

```
Ansible/
├── site.yml                  ← main entry point playbook
└── roles/
    └── packages/             ← generic package installer
        ├── tasks/main.yml    ← apt (Debian) + yum (RedHat) tasks
        ├── defaults/main.yml ← default empty list
        └── handlers/main.yml ← post-install verification
```

Single generic `packages` role (not per-package roles). Rationale: user specifies standard package names, role installs them. Per-package roles are a v2 concern (category-based design).

---

## V1 vs V2

| Aspect | V1 (now) | V2 (future) |
|---|---|---|
| Package format | Flat list: `[nginx, docker]` | Categories: `{webserver: nginx, container: docker}` |
| Tag format | `"nginx,docker"` | `"webserver:nginx,container:docker"` or multiple tags |
| Ansible roles | Single `packages` role | Per-category roles dispatched by orchestrator |

V1 does not block V2 — it's strictly additive to evolve.

---

## Key Concepts Learned

- **Ansible Roles**: Reusable units of automation with standard directory structure (tasks/, handlers/, defaults/)
- **Dynamic Inventory compose**: Jinja2 expressions that derive host variables from AWS metadata/tags at runtime
- **become: true**: Ansible equivalent of `sudo` — needed for package installation
- **apt vs yum**: Package manager differs by OS family. Use `ansible_os_family` fact to dispatch.
- **Handler pattern**: Tasks `notify` handlers. Handlers only run when the notifying task actually changed something.
