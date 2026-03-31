# Session 1 Progress — Building the Packages Role

**Date:** 2026-03-31

---

## What the User Built

The user created the initial Ansible role structure and main playbook manually as a learning exercise.

### Files Created by User

**`Ansible/ansible-instruction.yml`** — main playbook (replaces site.yml in the plan)
```yaml
---
- name: Install packages
  hosts: all
  gather_facts: true
  roles:
    - packages
```

**`Ansible/roles/packages/default/main.yml`** — defaults file
```yaml
quickspin_packages: []
```

**Directory structure created:**
```
Ansible/
├── ansible-instruction.yml       ← main playbook (user-created)
├── roles/
│   └── packages/
│       ├── default/              ← needs rename to "defaults"
│       │   └── main.yml          ← default variable value
│       ├── handlers/             ← empty, needs main.yml
│       └── tasks/                ← empty, needs main.yml
```

---

## Review Feedback Given

### Corrections Needed

| Issue | Status | Detail |
|---|---|---|
| Folder `default` → `defaults` | Pending | Ansible convention requires the 's' — won't auto-load without it |
| Missing `become: true` in playbook | Pending | SSM connects as ssm-user, need sudo for package install |
| Missing `---` in defaults/main.yml | Pending | YAML document separator — convention |
| tasks/main.yml empty | Pending | User working on this next |
| handlers/main.yml empty | Pending | After tasks are done |

### What User Got Right

- Playbook syntax: fixed the dash (`-`) for list item and `hosts:` keyword (was `hostname:`)
- Role directory structure: created roles/packages/ with correct subdirectories
- defaults/main.yml: correct variable name and empty list default value

---

## Current Learning Focus

User is now writing `tasks/main.yml` — the core of the role. Key concepts being taught:
- `ansible.builtin.yum` and `ansible.builtin.apt` modules
- `when:` conditionals based on `ansible_os_family`
- `notify:` to trigger handlers
- Both yum and apt accept a list for `name:` — no loop needed

---

## Next Steps

1. User writes `tasks/main.yml`
2. User writes `handlers/main.yml`
3. Rename `default/` → `defaults/`
4. Add `become: true` to playbook
5. Remaining plan steps: update inventory compose, quickspin.yml, Python script, Terraform vars/tags
