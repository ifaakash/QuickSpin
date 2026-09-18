# FastAPI Dashboard — running Ansible from a browser

Built 2026-09-18. A local control plane for QuickSpin: a FastAPI service that
reads `Ansible/inventories/dashboard.ini`, exposes the groups and hosts it finds,
and runs `playbook-list-users.yml` against a chosen target. Plus a static page so
a run is three dropdowns and a button.

## What changed in Ansible/

`roles/list-users/` was not usable before this. `ansible-playbook --syntax-check`
failed with `ERROR! the field 'hosts' is required but was not set`, and the
directory was not a real role — it had `default.yml` at the role root and a
playbook-shaped `list-users.yml` beside it.

Restructured to match `roles/jit/` + `playbook-jit-access.yml`:

```
Ansible/
├── playbook-list-users.yml          NEW — hosts: "{{ list_users_target | default('homelab') }}"
└── roles/list-users/
    ├── tasks/main.yml               was list-users.yml
    └── defaults/main.yml            was default.yml
```

`become: false` and `gather_facts: false` on purpose. `getent` reads a
world-readable passwd database and changes nothing, so there is no reason to
escalate.

## Layout

```
api/
├── requirements.txt          fastapi==0.141.1, uvicorn[standard]==0.53.0
└── app/
    ├── config.py             absolute paths + ALLOWED_USERS + ansible_env()
    ├── inventory.py          groups and hosts via `ansible-inventory --list`
    ├── runner.py             builds the argv list, runs it, returns a result dict
    ├── main.py               routes + static mount
    └── static/               index.html, style.css, app.js — no framework, no build step
```

## Endpoints

| Route | Returns |
| --- | --- |
| `GET /api/groups` | `{"groups": ["homelab"]}` |
| `GET /api/groups/{group}/hosts` | `{"hosts": [{"name": "moo", "ip": "100.76.6.76", "label": "moo (100.76.6.76)"}]}` |
| `GET /api/users` | `{"users": ["root", "ubuntu"]}` |
| `POST /api/preview` | `{command, command_pretty}` — builds the command without running it |
| `POST /api/run` | `{ok, returncode, command, command_pretty, stdout, stderr, duration}` |

`POST /api/run` body: `{"group": "homelab", "host": "moo", "user": "ubuntu"}`.
An empty `host` means "all hosts in the group" and drops `--limit`.

The command it assembles:

```bash
ansible-playbook \
  -i <abs>/Ansible/inventories/dashboard.ini \
  <abs>/Ansible/playbook-list-users.yml \
  -e ansible_user=ubuntu \
  -e list_users_target=homelab \
  --limit moo
```

## The UI

Two real views behind the navbar, both backed by the API — no placeholder links.

- **Run** — a config panel (group / host / run-as / playbook), a **Command** panel,
  and an **Output** panel.
- **Inventory** — a table of every group, host and `ansible_host` in `dashboard.ini`.

Four stat tiles across the top: group count, host count in the selected group,
last run status, last run duration. All read from the API or the last run; none
are decorative.

Run feedback: the button shows a spinner, and a live elapsed counter ticks in
the Output panel header. `POST /api/run` blocks, so something visibly moving is
what tells you the page has not frozen. `Cmd/Ctrl+Enter` runs from anywhere.

Also: a favicon, a connection dot in the navbar (green once the inventory loads, red if
`ansible-inventory` fails) and a light/dark toggle persisted in `localStorage`.

### The Output panel

Ansible output is colourised line by line in `lineClass()` — PLAY/TASK headers in
strong ink, `ok:` green, `changed:` amber, `fatal:`/`UNREACHABLE!` red,
timestamps and `skipping:` dimmed. The PLAY RECAP line is parsed: a host with
`unreachable=` or `failed=` above zero goes red, one with `changed=` above zero
goes amber, otherwise green.

The ansible keyword stays visible in every line, so colour is a second signal,
never the only one. Output text colours are chosen for readability on the code
surface (`#006300` green on light, `#4ade80` on dark) rather than reusing the
status-chip hexes, which are tuned for chips and not for body text.

Each line is a `<span>` whose text is set with `textContent`, so ansible output
is still never treated as markup.

### The Command panel

Shows the exact command for the current dropdown values. It starts as a dimmed
**preview** badge and flips to a solid **executed** badge after a run, so you can
always tell whether you are looking at what *would* run or what *did*. A Copy
button puts the multi-line form on the clipboard, and it is runnable as-is:

```
ansible-playbook \
  -i /abs/Ansible/inventories/dashboard.ini \
  /abs/Ansible/playbook-list-users.yml \
  -e ansible_user=ubuntu \
  -e list_users_target=homelab \
  --limit moo
```

**The panel cannot drift from reality.** `POST /api/preview` calls the same
`build_command()` the runner calls, and runs the same `validate_request()`, so a
rejected input shows the rejection instead of a plausible-looking command. The
formatting lives in `runner.format_command()` next to the builder, not in
JavaScript.

**Status is never colour alone.** Success and failure use distinct glyphs (`✓` /
`✕`) plus a word, with the reserved status hexes `#0ca30c` / `#d03b3b`. Colour is
the third signal, not the only one — this is what keeps it readable for colour
vision deficiency and in print.

## Why these decisions

**`ansible-inventory --list` instead of parsing the INI.** The INI cannot be read
with `configparser` — a line like `moo ansible_host=100.76.6.76` parses as the key
`moo ansible_host`. Rather than hand-roll a parser that would break on
`[group:vars]` or `[group:children]`, we borrow Ansible's own. Three functions,
and it keeps working if the inventory ever becomes YAML.

**`ANSIBLE_CONFIG` is set to an absolute path.** `Ansible/README.md` already warned
about this: `ansible.cfg` sets no `roles_path`, so roles resolve relative to the
playbook's directory. An external caller must point at the config file explicitly.
`runner.py` also sets `cwd=ANSIBLE_DIR` for the same reason.

**`ANSIBLE_FORCE_COLOR=0`.** Keeps ANSI escape codes out of the `<pre>` block.

**Synchronous run.** `POST /api/run` blocks until ansible exits. Fine for
list-users. If a long playbook is ever added, this becomes a background job with
a `job_id` and a polling endpoint — that is the known upgrade path, not a surprise.

## The security boundary

Two layers, both needed:

1. `subprocess.run` is given a **list**, never a string, and never `shell=True`.
   No shell exists to interpret a metacharacter.
2. Before any command is built, `main.py` checks group and host against the
   inventory it just read, and user against `ALLOWED_USERS`. Arbitrary values
   cannot reach argv at all.

Layer 2 matters even with layer 1, because `-e ansible_user=<x>` sets an Ansible
variable — an unchecked value there is an Ansible-level injection, not a shell one.
This is the same rule `playbook-jit-access.yml` states in its own header comment.

Verified rejected with 400:

```bash
curl -s -X POST localhost:8000/api/run -H 'content-type: application/json' \
  -d '{"group":"homelab; rm -rf /","host":"moo","user":"ubuntu"}'
# {"detail":"Unknown group: homelab; rm -rf /"}
```

**Bind to 127.0.0.1 only.** There is no authentication. On `0.0.0.0` anyone on the
LAN or tailnet could run playbooks against your fleet. The `make api` target
hardcodes the loopback bind.

## Running it

```bash
make api-setup     # one time — creates api/.venv and installs
make api           # serves http://127.0.0.1:8000
```

Run it from a shell with your SSH agent loaded, on a machine joined to the
tailnet — `100.76.6.76` is a Tailscale CGNAT address and is unroutable otherwise.

## Gotchas

- **`root` will fail against `moo`.** Ubuntu disables root SSH login by default.
  The option exists because it was asked for; read the failure as correct.
- **The `ubuntu` key is not on `moo` yet.** As of this build, a run returns
  `UNREACHABLE! ... Permission denied (publickey,password)`. SSH connects and
  offers `~/.ssh/id_ed25519`, and the Pi rejects it — the public key is not in
  `~ubuntu/.ssh/authorized_keys` on the host. Fix with `ssh-copy-id` from a
  session that can already log in. This is a host config gap, not an API bug.
- **You cannot smoke-test this against localhost on macOS.** There is no `getent`
  binary on Darwin, so the task fails with
  `Failed to find required executable "getent"`. The role needs a Linux target.
- **Every dropdown change costs one `ansible-inventory` call** (~0.3s), because
  `/api/preview` re-validates rather than trusting the browser. Fine on loopback;
  the fix if it ever matters is a short-lived cache in `inventory.py`, not skipping
  the check.
- **`ansible.cfg` enables `profile_tasks, timer`,** so every run appends a timing
  summary to stdout. Expected output, not noise.
- **Mount order in `main.py` matters.** `app.mount("/", StaticFiles(...))` must come
  after the `/api` routes or it swallows them.

## Next steps

- Get the SSH key onto `moo` so a green run can be confirmed.
- More playbooks: the run endpoint is hardcoded to one. A playbook registry
  (name -> path + allowed extra-vars) is the natural generalisation.
- Background jobs + streaming output when a playbook gets slow enough to matter.
- Auth, if this ever leaves loopback.
