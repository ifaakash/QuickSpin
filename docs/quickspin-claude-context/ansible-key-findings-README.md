# Ansible Key Findings & Gotchas

**Living document — updated as we learn things the hard way**

---

## 1. Task-Level vs Module-Level Keywords

Ansible tasks have **two indentation levels** that mean very different things:

```yaml
# Task-level keywords (belong to the TASK):
- name: Install package              # ← task-level
  ansible.builtin.apt:               # ← task-level (which module to use)
    name: "{{ quickspin_packages }}" # ← module-level (parameter OF apt)
    state: present                   # ← module-level
    update_cache: yes                # ← module-level
  when: ansible_os_family == "Debian"  # ← task-level
  notify: Verify packages              # ← task-level
  register: install_result             # ← task-level
```

**Rule of thumb:**
- **Task-level** (indented under `-`): `name`, module name, `when`, `notify`, `register`, `become`, `loop`, `tags`
- **Module-level** (indented under the module): parameters specific to that module (check `ansible-doc <module>`)

**Common mistake:** Putting `notify` inside the module block — the module doesn't know what `notify` is, so it's silently ignored or errors out.

---

## 2. Jinja2 Variable Syntax

```yaml
# WRONG — spaces between braces create a YAML dict, not a Jinja2 variable
name: { { quickspin_packages } }

# CORRECT — double braces are a single token, always quote the whole value
name: "{{ quickspin_packages }}"
```

Always wrap Jinja2 expressions in quotes when they start the value. Otherwise YAML tries to parse `{` as a dict.

---

## 3. Folder Naming Convention in Roles

```
roles/packages/default/    ← WRONG (Ansible ignores this)
roles/packages/defaults/   ← CORRECT (auto-loaded by Ansible)
```

Ansible role directories have fixed names: `tasks`, `handlers`, `defaults`, `vars`, `files`, `templates`, `meta`. Misspelling = silently ignored.

---

*Add new findings below as we encounter them.*
