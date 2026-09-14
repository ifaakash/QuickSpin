# Ansible learnings — from building the `jit` role

Quick-recap notes from building the JIT lab-user role. Skim the TL;DR, dig into a
section only when you need the "why" again.

## TL;DR checklist for the next role

- [ ] `defaults/main.yml` (not `default.yml`) for variables
- [ ] Use FQCN for every module (`ansible.builtin.xxx`, `ansible.posix.xxx`)
- [ ] Validate inputs with `assert`, one task per variable, specific `fail_msg`
- [ ] Trust idempotent modules — don't hand-roll "does X exist" checks
- [ ] Branch behavior with `include_tasks` + `when`, not `if/else` logic in one file
- [ ] Let security-sensitive modules manage their own permissions
- [ ] Static inventory = plain YAML groups/hosts; `--limit` picks the group at run time

---

## 1. Role file layout is a convention, not a guess

Ansible auto-loads specific paths — get the name wrong and it silently loads nothing:

```
roles/<role>/defaults/main.yml   # default variable values
roles/<role>/tasks/main.yml      # entry point, runs first
roles/<role>/tasks/<name>.yml    # included conditionally from main.yml
```

`default.yml` (no `s`, no folder) is just a random file to Ansible — it won't be
auto-loaded as role defaults.

## 2. Fully Qualified Collection Names (FQCN)

Write `ansible.builtin.assert`, `ansible.builtin.user`, `ansible.posix.authorized_key`
instead of the short `assert`, `user`, `authorized_key`. Short names still work today,
but FQCN removes ambiguity when multiple collections ship a module with the same
name, and it's the modern convention.

## 3. `assert` for validating inputs — one task per variable

```yaml
- name: Validate jit_username
  ansible.builtin.assert:
    that:
      - jit_username is defined
      - jit_username | length > 0
      - jit_username.startswith('jit_')
    fail_msg: "jit_username must be set and start with 'jit_'"
    success_msg: "jit_username is valid"
```

One assert per variable > one giant assert with 7 conditions. When it fails, you
immediately know *which* variable was the problem instead of guessing across a
generic message.

Bonus: `that:` entries are Jinja expressions, so plain Python string methods work
directly — `x.startswith('jit_')`, or `x.startswith(('ssh-rsa', 'ssh-ed25519'))`
using a tuple to match any of several prefixes.

## 4. Idempotent modules already do the "check first" for you

`ansible.builtin.user` with `state: present` creates the user if missing and does
nothing if it already exists. Writing a manual "check if user exists, then create"
step duplicates logic the module already guarantees. Rule of thumb: before adding a
manual existence/guard check, ask whether the module's `state:` already covers it.

## 5. Branch action logic with `include_tasks` + `when`, not inline conditionals

```yaml
- name: Provision lab user
  ansible.builtin.include_tasks: provision.yml
  when: jit_action == 'provision'

- name: Revoke lab user
  ansible.builtin.include_tasks: revoke.yml
  when: jit_action == 'revoke'
```

Keeps `provision.yml` / `revoke.yml` independently readable, and `main.yml` reads as
"validate, then dispatch" rather than a wall of tasks with scattered `when` clauses.

## 6. Let security-sensitive modules manage their own permissions

`sshd` refuses to trust `authorized_keys` (or the `.ssh` dir) if it's writable by
anyone but the owner — otherwise any other local user could inject their own key and
log in as your account. `ansible.posix.authorized_key` already creates `.ssh` as
`0700` and `authorized_keys` as `0600` when it adds a key — no manual `file`/`chmod`
task needed. General pattern: check what a module already guarantees before adding a
task to enforce it yourself.

## 7. Static inventory basics

```yaml
bastions:
  hosts:
    ibm-prod-proxy:
      ansible_host: ""                    # IP to connect to
      ansible_ssh_private_key_file: ""    # key Ansible uses to SSH in
```

- `ansible_host` / `ansible_ssh_private_key_file` are *connection* vars — how
  Ansible reaches the box. Not to be confused with `jit_publickey`, which is the
  *lab user's* key that gets authorized once Ansible is already connected.
- A playbook can keep `hosts: all` and still be scoped to one group at run time with
  `--limit bastions` — no need to hardcode the group into the playbook.

## 8. Running the playbook

```
ansible-playbook -i inventory_bastions.yml playbook-jit-access.yml --limit bastions \
  -e "jit_action=provision jit_username=jit_alice jit_publickey='ssh-ed25519 AAAA...'"
```

- `-i` overrides the default inventory set in `ansible.cfg`.
- `--limit <group>` scopes a `hosts: all` playbook to one inventory group.
- `-e "k=v k2=v2"` passes extra vars — this is how `jit_action`/`jit_username`/
  `jit_publickey` get supplied without hardcoding them in `defaults/main.yml`.
