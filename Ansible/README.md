# Running the JIT access playbook

Fill in `inventory_bastions.yml` with the real `ansible_host` (IP) and
`ansible_ssh_private_key_file` for the bastion(s) before running.

## Provision a lab user

```
ansible-playbook -i inventory_bastions.yml playbook-jit-access.yml \
  --limit bastions \
  -e "jit_action=provision jit_username=jit_alice jit_publickey='ssh-ed25519 AAAA...'"
```

## Revoke a lab user

```
ansible-playbook -i inventory_bastions.yml playbook-jit-access.yml \
  --limit bastions \
  -e "jit_action=revoke jit_username=jit_alice"
```

- `-i inventory_bastions.yml` points at the static bastion inventory instead of the default AWS dynamic inventory.
- `--limit bastions` restricts the run to the `bastions` group (the playbook's `hosts: all` would otherwise also match the dynamic AWS inventory).
- `jit_username` must start with `jit_`, and `jit_publickey` must be an `ssh-rsa` or `ssh-ed25519` key — see `roles/jit/tasks/main.yml` for the full validation.
