# QuickSpin DevOpsHub — current state

Last updated 2026-09-19. Branch `feat/devopshub-dashboard`.
Committed through `fc00174`; two UI fixes below are applied but **uncommitted**
(`api/app/main.py`, `api/app/static/style.css`), as is this file.

A local web control plane for QuickSpin: a FastAPI service that reads the Ansible
inventory and runs playbooks against a chosen target, plus a dashboard UI.
Detailed design notes live in
`docs/quickspin-claude-context/fastapi-dashboard-README.md`.

---

## Built

### Ansible

| Item | State |
| --- | --- |
| `playbook-list-users.yml` + `roles/list-users/` | Done. Was a broken non-role (`--syntax-check` failed, no `hosts:` key); restructured to match `roles/jit/`. |
| `roles/jit/` publickey assert | Fixed. Was asserted unconditionally, which made `revoke` impossible. Now `when: jit_action == 'provision'`. |
| `Ansible/README.md` | Updated — inventory table, playbook target table, layout tree, and the extra-vars quoting hazard. |

### API (`api/app/`)

| File | Role |
| --- | --- |
| `config.py` | Absolute paths, `ALLOWED_USERS`, JIT rules, `ansible_env()` |
| `inventory.py` | Groups and hosts via `ansible-inventory --list` |
| `runner.py` | `build_command(playbook, host, extra_vars)`, `format_command()`, `run_playbook()` |
| `main.py` | Routes, `validate_target()`, `validate_jit()` |

| Route | Purpose |
| --- | --- |
| `GET /api/groups` | group names |
| `GET /api/groups/{group}/hosts` | `{name, ip, label}` per host |
| `GET /api/users` | run-as allowlist (`root`, `ubuntu`) |
| `POST /api/preview` · `POST /api/run` | list-users |
| `GET /api/jit/actions` | `provision` / `revoke` |
| `POST /api/jit/preview` · `POST /api/jit/run` | JIT access |

### Dashboard (`api/app/static/`)

Navbar with three tabs (Run, JIT Access, Inventory), four stat tiles, a shared
Command panel (live preview → `executed` badge, copy button) and Output panel
with colourised ansible output. Light/dark toggle, favicon, run spinner, live
elapsed counter, `⌘↵` to run, `confirm()` before a revoke.

`[hidden] { display: none !important; }` makes the attribute reliable against
author `display` rules, and `NoCacheStaticFiles` in `main.py` stops the browser
serving a stale `app.js`. Both are explained under Recently fixed.

### Verified working

- Both playbooks run green against `moo` — list-users `rc=0`, JIT provision
  `ok=6 changed=2 unreachable=0`.
- The JSON extra-vars fix proven on the host: after a provision,
  `/home/jit_alice/.ssh/authorized_keys` held the key complete with its spaces,
  `+`, `/`, `=` padding and comment. Under `-e key=value` that file would have
  contained only the string `ssh-ed25519`.
- Revoke works with no key supplied (`skipping:` on the publickey assert).
- All validation rejections return 400 on both `/preview` and `/run`: unknown
  group/host/user, username without the `jit_` prefix, Jinja braces in the
  username, shell metacharacters, multi-line public key, unknown action, wrong
  key algorithm.
- Test account `jit_alice` was created during verification and **has been
  revoked**; `moo` is back to 38 accounts with no `jit_*` users.

---

## Recently fixed

### Inventory tab did not hide the Run/JIT layout

`switchView()` set `el("layout").hidden = true`, but `.layout` declares
`display: grid`, and an author `display` rule beats the user-agent
`[hidden] { display: none }` rule — so the attribute did nothing and the config,
Command and Output panels stayed on screen under the inventory table.

Fixed with one rule near the top of `style.css`:

```css
[hidden] { display: none !important; }
```

Author `!important` beats normal author declarations regardless of specificity
or order, so this is reliable. An audit of all six elements toggled via
`.hidden` found `#layout` was the **only** one with a conflicting `display`
rule — the other five (`#config-run`, `#config-jit`, `#view-inventory`,
`#jit-key-field`, `#jit-warn`) were working by luck. The blanket rule makes the
pattern safe rather than accidentally-correct.

### Stale assets served after a redeploy

`StaticFiles` sent `ETag` and `Last-Modified` but no `Cache-Control`, so
browsers applied heuristic caching and could keep running a previous `app.js`
after a redeploy — indistinguishable from "the dashboard did not update".

`NoCacheStaticFiles` in `api/app/main.py` now overrides `file_response()` to add
`Cache-Control: no-cache`. That means *revalidate*, not *refetch*: the ETag is
still sent, so an unchanged file costs a 304 with no body. Verified on both
paths — a plain request and an `If-None-Match` request each return the header.

---

## Pending

### 1. Never visually confirmed — highest risk

No browser tooling has been available in any session, so the rendered UI has
never actually been looked at. Structure, data flow and every API path are
verified; **layout, spacing, dark mode and tab switching are not**. This is
exactly how the `[hidden]` bug survived — it was invisible to every check that
does not paint pixels.

Worth confirming by eye on the next reload (hard reload once, `⌘⇧R`):

- Inventory tab actually hides the config / Command / Output panels
- JIT tab swaps only the left panel, Command and Output persist
- selecting `revoke` hides the key field and shows the warning note
- two-column layout and dark mode look right

### 2. Known limitations (by design, not bugs)

- `POST /api/run` is **synchronous** — it blocks until ansible exits. Fine for
  these two playbooks; a slow one needs a job id and a polling endpoint.
- **No authentication.** The service must stay bound to `127.0.0.1`; `make api`
  hardcodes that.
- Every dropdown change costs one `ansible-inventory` call (~0.3s) because
  `/preview` re-validates rather than trusting the browser. Text fields are
  debounced 300ms. A short-lived cache in `inventory.py` is the fix if it ever
  matters.
- Adding a third playbook still means a new route pair. A playbook registry
  (name → path, target var, extra-var schema) is the natural generalisation.

### 3. Environment notes

- `playbook-jit-access.yml` sets `become: true`, so the run-as user needs
  passwordless sudo on the target. `dashboard.ini` sets no `ansible_become`,
  unlike `static.ini`.
- `root` as run-as will fail on `moo` — Ubuntu disables root SSH by default.
- There is no `getent` on macOS, so list-users cannot be smoke-tested against
  localhost. It needs a Linux target.

---

## Running it

```bash
make api-setup   # once: creates api/.venv and installs
make api         # serves http://127.0.0.1:8000
```

Run from a shell with your SSH agent loaded, on a machine joined to the tailnet.
