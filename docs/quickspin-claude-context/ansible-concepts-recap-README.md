# Ansible Recap: Concepts, Connections & Jinja2 On-Ramp

**Date:** 2026-09-13

> This builds on [`ansible-roles-and-handlers-README.md`](./ansible-roles-and-handlers-README.md)
> and [`package-install-plan-README.md`](./package-install-plan-README.md) — read those for the
> deep dive on roles/handlers/idempotency and the tag-bridge design decision. One correction
> first: those docs refer to the entry playbook as `site.yml` — it's since been renamed to
> **`Ansible/ansible-instruction.yml`** (same content, same role list). This doc fills the gap
> those don't cover: how every piece actually wires together end-to-end, and Jinja2 templates,
> which this project hasn't used yet.

---

## 1. The full picture, one diagram

```
quickspin.yml                         you write: packages: [nginx]
      │  python/yaml-to-json.py
      ▼
IaC/terraform.tfvars.json             "packages": "nginx"
      │  IaC/main.tf → ec2_stack module
      ▼
EC2 instance tag                      Packages = "nginx"
      │  (live, read at run time — nothing checked into git)
      ▼
Ansible/inventory_aws.aws_ec2.yml     compose block:
                                       quickspin_packages =
                                         tags.Packages | split(',') | reject('equalto','') | list
      │  inventory var (outranks role defaults)
      ▼
Ansible/ansible-instruction.yml       hosts: all, become: true, gather_facts: true
                                       roles: [packages]
      │
      ▼
roles/packages/tasks/main.yml         apt/yum install "{{ quickspin_packages }}"
                                       gated by ansible_os_family (a gathered fact)
      │  notify: Verify packages   (only fires if the install task reports "changed")
      ▼
roles/packages/handlers/main.yml      which <pkg>   ← diagnostic only, never restarts anything
```

Nothing in this chain is hardcoded — the package name only ever exists as data (in your YAML, in
a tfvars file, in an EC2 tag, in a Jinja2-computed inventory variable). That's the single most
important thing to internalize before writing more Ansible here: **you're not editing Ansible to
add a package, you're editing `quickspin.yml`** — Ansible just reacts to whatever tag it finds.

---

## 2. Concept map — what connects to what

| Concept | File | Connects to |
|---|---|---|
| **Playbook** | `Ansible/ansible-instruction.yml` | Points at an inventory (via `ansible.cfg` or `-i`) and a list of roles. It's the only thing you invoke directly (`ansible-playbook ...`). |
| **Inventory** | `Ansible/inventory_aws.aws_ec2.yml` | Not a static host list — a live AWS query (`amazon.aws.aws_ec2` plugin, enabled in `ansible.cfg`). Its `compose` block is where **host variables get computed**, including `quickspin_packages`. This is upstream of every role. |
| **Facts** | gathered by `gather_facts: true` in the playbook | Produces `ansible_os_family`, consumed by `when:` conditions inside the role's tasks. Facts are per-host, discovered at run time — different from inventory vars, which are set by the inventory plugin. |
| **Role** | `roles/packages/` | A folder-name convention, not an import. `role: packages` in the playbook auto-loads `defaults/main.yml`, `tasks/main.yml`, `handlers/main.yml` from that folder — nothing else needed. |
| **Variable precedence** | `defaults/main.yml` (`quickspin_packages: []`) | Lowest priority — exists only as a safety fallback. The inventory's `compose` value always wins in this project, since nothing sets `group_vars`/`host_vars`/extra-vars here. |
| **Tasks** | `roles/packages/tasks/main.yml` | Uses `{{ quickspin_packages }}` (from inventory) + `ansible_os_family` (from facts) to decide *what* to install and *how*. Ends in `notify:`, which is a one-way link to a handler by name. |
| **Handlers** | `roles/packages/handlers/main.yml` | Only run if notified, only run once, only at the end of the play. The handler name (`Verify packages`) is just a string match against `notify:` — no folder-structure magic there, just string identity. |

The one thing *not* present anywhere in this repo: **templates**. That's next.

---

## 3. Jinja2 templates — what they are, and how hard they really are

You've already used Jinja2 without necessarily calling it that:

- Every `{{ quickspin_packages }}` in a task is Jinja2 variable substitution.
- The inventory's `compose` line is a full Jinja2 **expression** with filters chained together:
  ```jinja2
  tags.Packages | default('', true) | split(',') | reject('equalto', '') | list
  ```
  (`default`, `split`, `reject`, `list` are all Jinja2 filters — same filter syntax works inside a
  `.j2` file.)

**A template file (`.j2`) is just that same substitution, applied to an entire file instead of one
line.** You write a normal config/HTML/text file, drop `{{ variable }}` or `{% if/for %}` where you
want dynamic content, and the `ansible.builtin.template` module renders it to the target host
(vs. `ansible.builtin.copy`, which copies a file byte-for-byte with zero substitution).

**Difficulty: genuinely low if the above already makes sense.** There's no new mental model — it's
"the substitution you're already doing, just multi-line." The only new syntax is control
structures:

```jinja2
{# comment #}
{{ inventory_hostname }}                         {# a fact, always available #}
{{ quickspin_packages | join(', ') }}            {# filters work exactly like in the inventory #}

{% if 'nginx' in quickspin_packages %}
nginx is installed on this host
{% endif %}

{% for pkg in quickspin_packages %}
- {{ pkg }}
{% endfor %}
```

What to actually go learn (in order, ~30–45 min total if you're comfortable with the inventory
file already):
1. Ansible docs: [Templating (Jinja2)](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_templating.html) — skim, you already know the substitution part.
2. Ansible docs: [`template` module](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/template_module.html) — note `src`/`dest`/`mode`, and that it's almost always paired with `notify:`.
3. Jinja2 built-in filters list (bookmark, don't memorize) — you'll reach for `join`, `default`, `length` most often here.

---

## 4. Exercises — build up the one pattern this repo hasn't shown you yet

Do these directly in this repo, in order. Each has a self-check so you don't need anyone to
validate it for you.

**Exercise 1 — variable precedence, warm-up.**
Add a second variable to `roles/packages/defaults/main.yml` (e.g. `quickspin_verify_enabled:
true`), and wrap the existing handler's task with `when: quickspin_verify_enabled`.
*Self-check:* nothing changes in behavior yet (default is `true`) — proves you understand that
defaults are just a fallback source, not the value actually used.

**Exercise 2 — first real template.**
Create a new role `roles/webserver/` with `templates/index.html.j2` containing something like:
```jinja2
<h1>{{ inventory_hostname }}</h1>
<p>{{ quickspin_packages | join(', ') }}</p>
```
Add `tasks/main.yml` using `ansible.builtin.template` to deploy it to `/var/www/html/index.html`,
with `notify: Restart nginx`.
*Self-check:* `ansible-playbook --syntax-check -i Ansible/inventory_aws.aws_ec2.yml
Ansible/ansible-instruction.yml` passes once you add the role to the playbook's `roles:` list.

**Exercise 3 — a handler that actually does something.**
Write `roles/webserver/handlers/main.yml`:
```yaml
- name: Restart nginx
  ansible.builtin.service:
    name: nginx
    state: restarted
```
*Self-check:* run the playbook twice against a real host with nginx installed. First run:
`template` task shows `changed`, handler fires. Second run: `template` shows `ok`, handler does
**not** fire. That contrast is the entire point of the handler pattern.

**Exercise 4 (stretch) — connect it to the existing inventory plumbing.**
Gate the new role so it's a no-op on hosts that didn't request nginx, reusing the variable the
dynamic inventory already computes for you:
```yaml
roles:
  - role: packages
  - role: webserver
    when: "'nginx' in quickspin_packages"
```
*Self-check:* a host whose `Packages` tag doesn't include `nginx` should skip the `webserver` role
entirely in the play output (`skipping` per task), not fail.

**Exercise 5 (stretch, ties to an existing TODO in `package-install-plan-README.md`).**
That doc already floats a "V2: per-category roles" design (`{webserver: nginx, container:
docker}` instead of a flat list). Once Exercise 4 works, sketch — in a scratch file, no need to
implement — what tag format and inventory `compose` change that split would require.

---

## 5. Where AWX fits (for later, not now)

Decided this round: **skip AWX for now.** It adds a UI, RBAC, scheduling, and centralized
inventory/credential management on top of Ansible — none of which this project currently needs,
since Ansible here runs from one manually-triggered GitHub Actions job against tag-discovered
hosts. Revisit if/when this grows multiple playbooks, multiple environments, or a need to run jobs
outside of CI.
