# Ansible in QuickSpin

Two inventories live here. **They use different transports and they run in
different places.** Getting that wrong is the easiest mistake in this repo, so
it's written down first.

## The rule

| Inventory | Transport | Group | Runs where | Why |
| --- | --- | --- | --- | --- |
| `inventories/aws.aws_ec2.yml` | SSM (AWS API) | `cloud` | **CI or laptop** | Works because it never needs a network path to the host — the SSM agent dials out |
| `inventories/static.ini` | SSH over Tailscale | `homelab` | **Laptop only** | A GitHub-hosted runner is not on your tailnet. `100.76.6.76` is unroutable from it |
| `inventories/dashboard.ini` | SSH over Tailscale | `homelab` | **Laptop only** | What the FastAPI dashboard reads and runs against. Same transport caveat as `static.ini` |
| `inventories/bastions.yml` | SSH | `bastions` | **Laptop only** | Still a stub — fill in `ansible_host` and the key path before use |

Never put the Tailscale inventory in a CI job. It would need
`tailscale/github-action` plus an auth key in a **public** repo's secrets, and
you're the only operator — your laptop is already on the tailnet.

## There is no default inventory

`ansible.cfg` deliberately has no `inventory =` line. **Every command must pass
`-i`.** Forgetting it now fails loudly instead of quietly pointing an SSH
playbook at your AWS fleet.

## No playbook uses `hosts: all`

Each targets a real group. `all` would sweep in every inventory passed on the
same command line, which is how you accidentally reconfigure production while
testing a Pi.

| Playbook | Targets | Override with |
| --- | --- | --- |
| `playbook-ping.yml` | `homelab` | `-e ping_target=cloud` |
| `playbook-install-package.yml` | `cloud` | — fixed, reads the `Packages` EC2 tag |
| `playbook-jit-access.yml` | `bastions` | `-e jit_target=homelab` |
| `playbook-list-users.yml` | `homelab` | `-e list_users_target=cloud` |

---

## Connectivity check

```bash
ansible -i inventories/static.ini homelab -m ping
ansible-playbook -i inventories/static.ini playbook-ping.yml
ansible-playbook -i inventories/static.ini playbook-ping.yml --limit moo
```

## Install packages on provisioned instances

```bash
export AWS_REGION=us-east-1 QUICKSPIN_PREFIX=quickspin
ansible-playbook -i inventories/aws.aws_ec2.yml playbook-install-package.yml
```

Needs valid AWS credentials, the `session-manager-plugin`, and instances that
have finished registering with SSM (~60s after boot).

## JIT access — provision

```bash
ansible-playbook -i inventories/bastions.yml playbook-jit-access.yml \
  -e "jit_action=provision jit_username=jit_alice jit_publickey='ssh-ed25519 AAAA...'"
```

Against the Pi instead:

```bash
ansible-playbook -i inventories/static.ini playbook-jit-access.yml \
  -e "jit_target=homelab jit_action=provision jit_username=jit_alice jit_publickey='ssh-ed25519 AAAA...'"
```

## JIT access — revoke

```bash
ansible-playbook -i inventories/bastions.yml playbook-jit-access.yml \
  -e "jit_action=revoke jit_username=jit_alice"
```

`jit_username` must start with `jit_`, and `jit_publickey` must be `ssh-rsa` or
`ssh-ed25519` — see `roles/jit/tasks/main.yml` for the full validation.

## List users

Read-only. Prints every account in the target's passwd database.

```bash
ansible-playbook -i inventories/dashboard.ini playbook-list-users.yml \
  -e ansible_user=ubuntu -e list_users_target=homelab --limit moo
```

This is the playbook the FastAPI dashboard in `../api/` drives. See
`../docs/quickspin-claude-context/fastapi-dashboard-README.md`.

---

## Layout

```
Ansible/
├── ansible.cfg              no inventory default, on purpose
├── inventories/
│   ├── aws.aws_ec2.yml      dynamic, SSM, group `cloud`
│   ├── static.ini           static, SSH/Tailscale, group `homelab`
│   ├── dashboard.ini        static, SSH/Tailscale, group `homelab` (read by the API)
│   └── bastions.yml         static, SSH, group `bastions` (stub)
├── playbook-ping.yml        connectivity only
├── playbook-install-package.yml
├── playbook-jit-access.yml
├── playbook-list-users.yml  read-only user audit, driven by the dashboard
└── roles/
    ├── jit/                 create/remove a user + authorized_key
    ├── list-users/          print the passwd database
    └── packages/            install from the Packages tag
```

## If something calls these from outside this directory

`ansible.cfg` sets no `roles_path`, so roles resolve **relative to the
playbook's own directory**. Anything invoking these from elsewhere — an API, a
container — must use an **absolute playbook path** and set
`ANSIBLE_CONFIG=/abs/path/to/Ansible/ansible.cfg` explicitly.
