# k3s: App → MySQL Connectivity Debugging (2026-09-24)

Three app replicas reported `1/1 Running` while being completely unable to
reach the database. Six separate defects stacked on top of each other, each one
hidden behind the one in front of it.

Starting symptom:

```
waiting for MySQL at devopshub@127.0.0.1:3306/devopshub (attempt 9/10):
  (2003, "Can't connect to MySQL server on '127.0.0.1' ([Errno 111] Connection refused)")
init_db failed after 10 attempts, serving anyway
INFO:     Application startup complete.
```

Final state: `/healthz` → `{"status":"ok","database":"devopshub@devopshub-db-svc:3306/devopshub","jobs":0,"grants":0}`

## The six defects, in the order they surfaced

Each fix revealed the next one. The error message moved *down* the stack each
time, which is the signal you're making progress rather than going in circles.

| # | Defect | Symptom it produced |
|---|---|---|
| 1 | No Service for the db Pod | Nothing to point `MYSQL_HOST` at |
| 2 | db Pod had no `labels` | Any Service selector would match nothing |
| 3 | `MYSQL_HOST` unset → `config.py:50` defaults to `127.0.0.1` | App dialled its **own** pod's loopback → connection refused |
| 4 | Service port `5432` (PostgreSQL) instead of `3306` | Endpoint populated, still refused — one hop further along |
| 5 | `MYSQL_HOST` added to `db-pod.yml` instead of the ConfigMap | App env still had no `MYSQL_HOST` |
| 6 | Deployment had `envFrom: configMapRef` only, no Secret | `Access denied ... (using password: NO)` |

Plus one that wasn't in any YAML at all — see *Stale datadir* below.

Also removed: a stray `pod.yml` carrying `app: devopshub`, which **matched
`devopshub-svc`'s selector**. Applying it would have put a fourth, unmanaged pod
behind the production Service. It was also invalid (a `volumeMounts` entry with
no matching `volumes:` block), which is the only reason it never got applied.

## Root cause worth remembering

**`127.0.0.1` inside a pod is that pod's own network namespace.** It can never
reach another pod, ever. Docker Compose hides this — shared networks and service
aliasing make loopback-ish addressing appear to work. Kubernetes makes the
boundary real. A default of `127.0.0.1` for a DB host is a Compose-era
assumption that produces a *correct-looking* config which cannot work.

## Stale datadir: env vars are seed data, not configuration

The Secret keys were originally wired backwards:

| key | value | originally wired to |
|---|---|---|
| `password` | `devopshub` | `MYSQL_ROOT_PASSWORD` |
| `root-password` | `devopshub-root` | `MYSQL_PASSWORD` (app user) |

Fixing the YAML and restarting the pod **changed nothing.** Verified live:

```
mysql -udevopshub -pdevopshub       → ERROR 1045 Access denied
mysql -udevopshub -pdevopshub-root  → works
```

`MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_ROOT_PASSWORD` / `MYSQL_DATABASE` are
read by the entrypoint **only when it initializes an empty datadir.** The pod log
gives it away — no `Initializing database` line, straight to
`ready for connections`. The PVC survived, so the old credential did too.

**The YAML said one thing, the volume said another, and the volume won.**

Same trap on Postgres and MongoDB. Fix is either `ALTER USER` in place, or
delete the PVC and let it re-seed. Deleting is better in dev — it proves the
manifests actually produce a working DB from scratch.

## `MYSQL_HOST` in the MySQL container is a landmine

Adding `MYSQL_HOST: devopshub-db-svc` to `db-pod.yml` wasn't just useless — the
`mysql` **client** reads that variable. The entrypoint shells out to the client
during first-time init, so on a fresh volume it would have dialled the Service
over TCP instead of the local unix socket, and seeding could fail. Inert on an
already-initialized datadir, which is exactly why it would have detonated later,
on the fresh-PVC path, long after the change was forgotten.

## Where config actually has to live

`MYSQL_USER` reached the app but `MYSQL_HOST` (sitting in `db-pod.yml`) did not.
Why: the ConfigMap is consumed by the Deployment via `envFrom: configMapRef`.

> **`env:` in a Pod spec is scoped to that one container and is invisible to
> everything else in the cluster.** Shared values belong in a ConfigMap; the
> Service name is shared config, not a property of the database.

`env:` and `envFrom:` coexist fine on the same container — `env:` wins when a
key appears in both.

## What triggers a rollout

Two config changes in this session behaved oppositely, and the distinction is
the point:

| Change | Rolls pods? | Why |
|---|---|---|
| Edit `deployment.yml` (add `env:`) | **Yes**, on `apply` | Pod template changed → new ReplicaSet |
| Edit `configm.yml` (add `MYSQL_HOST`) | **No** | Template byte-identical; needs `kubectl rollout restart` |

**Kubernetes rolls pods when the *spec* changes, not when the *data a pod reads*
changes.** Env vars are injected at container start and frozen there. Same class
of mistake as the stale PVC — a source changed, the consumer never re-read it.

## Reading MySQL auth errors

`using password: NO` is not "wrong password" — it's "the client sent an empty
string." That pointed straight at `_mysql_password()` (`config.py:68`) falling
through to `os.getenv("MYSQL_PASSWORD", "")`. `using password: YES` would have
meant a genuine credential mismatch, i.e. the stale-datadir problem instead.

Also: reaching a MySQL *protocol-level* error at all proves DNS resolved, the
Service routed, TCP connected, and the handshake completed. The error moving
from `Errno 111` (transport) to `1045` (auth) was the real progress signal.

## Decision: password delivery

Chose `secretKeyRef` env var over `MYSQL_PASSWORD_FILE` + mounted Secret.

Accepted tradeoff: the password is readable from `/proc/<pid>/environ` and is
**inherited by every `ansible-playbook` process this API forks** — which is the
reason `config.py:56-68` supports the file variant at all. Simplicity won for
homelab; the code path already exists if that changes.

A collision was also lurking: `SSH_KEY_DIRS: "/secrets:/root/.ssh"` means the
app **scans `/secrets` for private keys**, and `ssh-key-volume` already mounts
there. A db-password mount at `/secrets` would shadow the SSH key *and* offer the
password file up as an SSH key candidate. `/run/secrets/db/` if it's ever done.

## Debugging commands worth keeping

```bash
# Does the Service actually have backends? Empty = selector/label mismatch.
kubectl get endpoints devopshub-db-svc

# What the container ACTUALLY has — not what you think the YAML says.
kubectl exec deploy/devopshub-deployment -- env | grep MYSQL

# Isolate transport from auth. If this fails it is never a password problem.
kubectl exec deploy/devopshub-deployment -- python3 -c \
  "import socket; s=socket.create_connection(('devopshub-db-svc',3306),3); print('TCP OK', s.getpeername())"

# Did the entrypoint seed, or find an existing volume and skip?
kubectl logs db | grep -iE "initializing|ready for connections"

# Ground truth on credentials, bypassing the app entirely.
kubectl exec db -- mysql -udevopshub -pdevopshub -e "SELECT 1;"

# End-to-end.
kubectl exec deploy/devopshub-deployment -- python3 -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/healthz').read().decode())"
```

The pattern: **verify each layer independently — labels → endpoints → TCP →
auth → app.** Reading the app's error alone kept pointing at the wrong layer.

## Still outstanding

None of this blocks the app today.

1. **No readiness probe** — highest value. This is *why* three pods reported
   `1/1 Running` while serving nothing: `init_db` is deliberately non-fatal
   (`serving anyway`), so the container stayed up. A probe on `/healthz` turns
   "app lies about being healthy" into `0/3 NotReady` and no traffic routed.
   ~6 lines.
2. **`db` is a bare Pod** — no controller. Node reboot or eviction loses it
   permanently. Wants a StatefulSet.
3. **No resource requests/limits** — MySQL is first to the OOM killer under
   node pressure.
4. **`replicas: 3` + `imagePullPolicy: Never`** — single-node only. A second
   node gets `ErrImageNeverPull` without `k3s ctr images import` on each.
5. **`deployment.yml:32-33`** still carries a comment describing the
   `volumeMounts` placement bug fixed in `c5acd53`. A comment documenting a bug
   that no longer exists will mislead later.
