# Ansible Learning Journey — Concept Reference

**Living document — concepts added as we learn them throughout the project**

---

## 1. Playbook Structure

A playbook is a **YAML list of plays**. Even with one play, it must start with `-`:

```yaml
---
- name: My Play          # ← dash makes it a list item
  hosts: all             # ← which hosts to target
  become: true           # ← run as root (sudo)
  gather_facts: true     # ← collect OS info before running tasks

  roles:
    - my_role            # ← roles to execute in order
```

**Key keywords:**
- `hosts` — not `hostname` (common mistake)
- `become: true` — needed whenever tasks require root (package install, service management)
- `gather_facts: true` — populates variables like `ansible_os_family` that we use in conditionals

---

## 2. What is a Role?

A role is a **self-contained unit of automation** with a fixed folder structure. Ansible auto-loads files by convention — no imports needed.

```
roles/packages/
├── defaults/main.yml    ← default variable values (lowest priority)
├── tasks/main.yml       ← the actual work (required)
├── handlers/main.yml    ← actions that run only when notified
├── vars/main.yml        ← higher-priority variables (rarely needed)
├── files/               ← static files to copy to remote
├── templates/           ← Jinja2 templates to render and copy
└── meta/main.yml        ← role dependencies and metadata
```

You don't need all folders — only create what you use. `tasks/main.yml` is the minimum.

---

## 3. Task-Level vs Module-Level

Every task has two indentation levels:

```yaml
- name: Install package                  # task-level
  ansible.builtin.apt:                   # task-level (module choice)
    name: "{{ quickspin_packages }}"     #   module-level (parameter OF apt)
    state: present                       #   module-level
    update_cache: yes                    #   module-level
  when: ansible_os_family == "Debian"    # task-level
  notify: Verify packages                # task-level
  register: install_result               # task-level
```

**Task-level keywords:** `name`, module name, `when`, `notify`, `register`, `become`, `loop`, `tags`, `ignore_errors`
**Module-level:** whatever that specific module accepts (check `ansible-doc <module>`)

---

## 4. Jinja2 Variables in YAML

```yaml
# WRONG — spaces between braces = YAML dict
name: { { my_var } }

# CORRECT — double braces are one token, always quote
name: "{{ my_var }}"
```

Rule: if a YAML value **starts with** `{{`, wrap the entire value in quotes. Otherwise YAML parses `{` as a dictionary.

---

## 5. Handlers

Handlers are tasks that **only run when notified**, and only run **once at the end of the play**.

```yaml
# In tasks/main.yml — the task notifies a handler by name:
- name: Install packages
  ansible.builtin.yum:
    name: "{{ quickspin_packages }}"
    state: present
  notify: Verify packages            # ← "hey handler, I changed something"

# In handlers/main.yml — the handler with that exact name:
- name: Verify packages              # ← must match the notify string exactly
  ansible.builtin.command: "which {{ item }}"
  loop: "{{ quickspin_packages }}"
```

**When does the handler run?**
- Task reports `changed` → handler runs (end of play)
- Task reports `ok` (already installed) → handler does NOT run

This is the **idempotency pattern** — run the playbook 10 times, same result. Verification only happens when meaningful.

---

## 6. Dynamic Inventory (aws_ec2 plugin)

Instead of a static list of IPs, Ansible queries AWS live:

```yaml
plugin: amazon.aws.aws_ec2
filters:
  "tag:Project": QuickSpin     # ← only our instances
hostnames:
  - tag:Name                   # ← use Name tag as the Ansible host identifier
```

The `compose` block derives **host variables** from instance metadata:
```yaml
compose:
  ansible_connection: "'community.aws.aws_ssm'"    # how to connect
  ansible_host: instance_id                         # what to connect to
  quickspin_packages: tags.Packages | split(',')    # packages from EC2 tag
```

Variables set in `compose` are available in playbooks as regular variables — they override `defaults/main.yml` values.

---

## 7. Variable Priority (low → high)

```
defaults/main.yml       ← lowest (role defaults)
group_vars/all.yml      ← applies to all hosts
group_vars/<group>.yml  ← applies to specific group
host_vars/<host>.yml    ← applies to specific host
inventory compose       ← dynamic inventory variables  ← our packages come from here
playbook vars           ← vars: block in the playbook
extra vars (-e flag)    ← highest (command line override)
```

Higher priority wins. That's why `quickspin_packages: []` in defaults is safe — the inventory compose value overrides it.

---

## 8. Connection via SSM (not SSH)

Traditional Ansible uses SSH. Our setup uses **AWS Systems Manager**:

```
ansible_connection: community.aws.aws_ssm    ← transport layer
ansible_host: instance_id                    ← i-0abc123, not an IP
ansible_aws_ssm_bucket_name: ...             ← S3 bucket for command I/O
```

This works because:
- EC2 instances have SSM Agent installed
- IAM role grants SSM permissions
- VPC endpoints (`ssm`, `ssmmessages`, `ec2messages`) route traffic privately
- `private_dns_enabled = true` makes it transparent at DNS level

---

## 9. `become: true` (Privilege Escalation)

SSM connects as `ssm-user`. Package installation needs `root`. `become: true` tells Ansible to `sudo` before running tasks.

Can be set at:
- **Play level** — applies to all tasks in the play
- **Task level** — applies to just that one task
- **Role level** — in the role's `meta/main.yml`

---

## 10. Idempotency

The core Ansible principle: **running the same playbook multiple times produces the same end state**.

- `apt`/`yum` with `state: present` → installs if missing, does nothing if present
- Handlers only fire on `changed`, not on `ok`
- Second run = `changed=0` = clean, fast, no side effects

This is what makes Ansible safe to run repeatedly — unlike a shell script that might reinstall or break things.

---

## 11. `changed_when` and `failed_when`

Override Ansible's default behaviour for determining if a task "changed" something or "failed":

```yaml
- name: Verify packages
  ansible.builtin.command: "which {{ item }}"
  changed_when: false    # ← "which" is read-only, never counts as a change
  failed_when: false     # ← don't fail the play if binary isn't in PATH
```

- `command` module always reports `changed` by default (it can't know if the command modified state)
- `changed_when: false` says "this task never changes anything" — keeps the play report clean
- `failed_when: false` says "even if the command returns non-zero, don't fail" — useful for soft checks

---

## 12. Jinja2 Filter Chains in Inventory Compose

The `compose` block in dynamic inventory uses Jinja2 filters chained with `|` (like Unix pipes):

```yaml
quickspin_packages: tags.Packages | default('', true) | split(',') | reject('equalto', '') | list
```

Each filter transforms the output and passes it to the next:

```
tags.Packages         → "nginx,docker"      # read EC2 tag
default('', true)     → "nginx,docker"      # fallback if tag missing/empty
split(',')            → ["nginx", "docker"]  # string → list
reject('equalto', '') → ["nginx", "docker"]  # remove empty strings
list                  → ["nginx", "docker"]  # materialize generator into list
```

**Key filters to remember:**
- `default(value, true)` — the `true` param means "also replace empty/None values", not just undefined
- `split(',')` — reverse of Python's `",".join()`
- `reject('equalto', '')` — guards against `"".split(",")` producing `[""]`
- `list` — `reject()` returns a lazy generator, `list` materializes it

---

## 13. The Full Data Round-Trip

```
quickspin.yml         Python .join()        Terraform tag        Ansible split()
["nginx","docker"]  →  "nginx,docker"   →  "nginx,docker"   →  ["nginx","docker"]
```

Data starts as a list, becomes a string (because EC2 tags are strings), and becomes a list again in Ansible. Each tool handles the conversion at its boundary.

---

## 14. Ansible Variables — The Pizza Shop Analogy

Think of variables like a pizza shop with 3 stores. Each level can set `default_topping`, and the **more specific source wins**:

```
Priority (low → high):

1. Role defaults/main.yml     → cheese       "menu default"
2. group_vars/all.yml         → pepperoni    "all stores get this"
3. host_vars/store.yml        → paneer       "this one store gets this"
   (compose lives here too)   → from EC2 tag "auto-generated per host"
4. Playbook vars:             → mushroom     "override in playbook"
5. -e extra vars              → olive        "command line always wins"
```

**The rule: same variable name, multiple sources, highest priority wins.**

### In QuickSpin:
- `defaults/main.yml` sets `quickspin_packages: []` (priority 1 — fallback)
- `compose` reads EC2 tag and sets `quickspin_packages: ["nginx"]` (priority 3 — host-level)
- Host-level beats defaults → `["nginx"]` wins over `[]`
- No explicit "passing" needed — same variable name connects them automatically

---

## 15. Inventory Plugin `compose` Block (Needs Deeper Dive Later)

`compose` is a built-in feature of dynamic inventory plugins (like `aws_ec2`). It lets you **derive new host variables** from the metadata the plugin already fetched about each host.

```yaml
compose:
  <variable_name>: <jinja2 expression using EC2 metadata>
```

Available data includes: `instance_id`, `tags.*`, `private_ip_address`, `instance_type`, `placement.region`, `state.name`, etc.

Every key defined in `compose` becomes a host variable available in playbooks — same as if it were in `host_vars/`.

**Still unclear — revisit in a future session with hands-on examples.**

---

## 16. GitHub Actions — `GITHUB_OUTPUT` (Passing Data Between Steps/Jobs)

### Between Steps

```yaml
- name: Set a value
  id: my_step                    # ← required to reference later
  run: echo "key=value" >> $GITHUB_OUTPUT

- name: Use the value
  run: echo "${{ steps.my_step.outputs.key }}"
```

### Between Jobs

```yaml
jobs:
  job1:
    outputs:
      my_key: ${{ steps.my_step.outputs.my_key }}   # ← expose to other jobs
    steps:
      - id: my_step
        run: echo "my_key=hello" >> $GITHUB_OUTPUT

  job2:
    needs: job1
    steps:
      - run: echo "${{ needs.job1.outputs.my_key }}"
```

**Pattern:** `steps.<id>.outputs.<key>` within a job, `needs.<job>.outputs.<key>` across jobs.

---

*New concepts will be added as we encounter them throughout the project.*
