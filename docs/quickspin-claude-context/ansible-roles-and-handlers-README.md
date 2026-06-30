# Ansible Roles, site.yml & Handlers — Explained

**Date:** 2026-03-31

---

## What is `site.yml`?

The **main entry point playbook**. It doesn't contain logic — it orchestrates which roles run on which hosts. Think of it as the main menu, not the recipe.

```yaml
---
- name: Configure QuickSpin instances
  hosts: all
  become: true
  gather_facts: true

  roles:
    - packages
    # future roles added here:
    # - monitoring
    # - security
```

- `hosts: all` — targets every instance discovered by the dynamic inventory
- `become: true` — runs as root (needed for package installation)
- `gather_facts: true` — collects OS info so we know apt vs yum
- `roles:` — the ordered list of roles to execute

---

## How Roles Work

A role is a **folder with a fixed structure**. Ansible auto-loads each file by convention — no imports needed.

```
roles/packages/
├── defaults/main.yml    ← default variable values (lowest priority)
├── tasks/main.yml       ← the actual work
└── handlers/main.yml    ← conditional actions (only run when notified)
```

### Execution Flow (QuickSpin context)

```
site.yml says: "run role: packages"
    │
    ▼
1. Load defaults/main.yml
   quickspin_packages: []           ← fallback if no EC2 tag exists
   BUT: inventory compose already set quickspin_packages: ["nginx", "docker"]
   from the EC2 tag. Inventory vars override defaults.
    │
    ▼
2. Run tasks/main.yml
   Task 1: Gather OS facts       → learns: ansible_os_family = "RedHat"
   Task 2: apt install (Debian)  → SKIPPED (os_family != Debian)
   Task 3: yum install (RedHat)  → RUNS: yum install nginx docker
           notify: verify        → signals the handler
    │
    ▼
3. Run handlers/main.yml (only because task 3 notified)
   which nginx  ✓
   which docker ✓
```

### Variable Priority (low → high)

```
defaults/main.yml  →  group_vars  →  host_vars  →  inventory compose  →  playbook vars
     ↑ lowest                                            ↑ our packages come from here
```

---

## Handlers — Deep Dive

Handlers are tasks that **only run when notified** by another task, and only run **once at the end of the play**, even if notified multiple times.

### First Run (packages not installed yet)

```
TASK [packages : Install packages (RedHat/Amazon)] ****
changed: [quickspin-private-instance-0]     ← installed! status = "changed"
                                               triggers handler via notify

RUNNING HANDLER [packages : verify packages installed]
ok: (item=nginx)    ← which nginx ✓
ok: (item=docker)   ← which docker ✓
```

### Second Run (packages already installed)

```
TASK [packages : Install packages (RedHat/Amazon)] ****
ok: [quickspin-private-instance-0]          ← already installed, status = "ok"
                                               handler does NOT run

PLAY RECAP ********************************************
ok=3  changed=0                              ← clean, no unnecessary work
```

### Why Handlers Matter

| Without handlers | With handlers |
|---|---|
| Verification runs every time | Verification runs only when something changed |
| Noisy output on repeat runs | Clean output — only meaningful actions shown |
| Wastes time on no-op checks | Fast re-runs (idempotent) |

---

## Idempotency

This is the most important Ansible concept: **running the same playbook multiple times produces the same result**. The first run installs nginx. The second run sees nginx already installed and does nothing. Handlers reinforce this — they skip verification when nothing changed.
