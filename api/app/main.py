"""FastAPI service behind the QuickSpin dashboard.

Four read endpoints feed the dropdowns, one POST runs the playbook. Serve it on
localhost only: it executes commands on remote hosts and has no authentication.
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from contextlib import closing
import re
import sqlite3

from .config import (
    ALLOWED_USERS,
    DB_PATH,
    HEALTH_DB_TIMEOUT_SECONDS,
    JIT_ACTIONS,
    JIT_KEY_PREFIXES,
    JIT_PLAYBOOK,
    JIT_USERNAME_PATTERN,
    LIST_USERS_PLAYBOOK,
    SSH_KEY_DIR,
    STATIC_DIR,
)
from .inventory import get_groups, get_host_names, get_hosts, load_inventory
from .keys import list_keys, resolve_key
import shlex

from .runner import build_command, format_command, run_playbook

app = FastAPI(title="QuickSpin Dashboard API")


class RunRequest(BaseModel):
    """Body of POST /api/run. An empty host means the whole group.

    private_key names a key from GET /api/ssh-keys — a bare filename, never a
    path. Empty means "do not pass --private-key at all", which leaves ssh to
    use the agent or whatever ansible.cfg specifies.
    """

    group: str
    host: str = ""
    user: str
    private_key: str = ""


class JitRequest(RunRequest):
    """Body of the JIT routes. publickey is unused when action is revoke."""

    action: str
    username: str
    publickey: str = ""


def read_inventory():
    """Load the inventory, turning a parser failure into a 500 with the reason."""
    try:
        return load_inventory()
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Cannot read inventory: {error}")


@app.get("/api/groups")
def list_groups():
    return {"groups": get_groups(read_inventory())}


@app.get("/api/groups/{group}/hosts")
def list_hosts(group: str):
    data = read_inventory()
    if group not in get_groups(data):
        raise HTTPException(status_code=404, detail=f"Unknown group: {group}")
    return {"hosts": get_hosts(data, group)}


@app.get("/api/users")
def list_users():
    """The dropdown reads the allowlist so the two never drift apart."""
    return {"users": ALLOWED_USERS}


@app.get("/api/ssh-keys")
def ssh_keys():
    """Private keys available to --private-key, read from disk on every call.

    Each entry carries `encrypted`, so the dropdown can show which keys cannot
    be used and why rather than offering a choice that is certain to be
    rejected. Only names are returned — never paths, and never key material.
    """
    return {"keys": list_keys(), "directory": str(SSH_KEY_DIR)}


def validate_target(body):
    """Reject anything not present in the inventory or on the allowlist.

    This is the security boundary. Group and host must exist in the inventory we
    just read, and the user must be on the fixed allowlist, so nothing arbitrary
    can reach the command line. Both /api/preview and /api/run go through it, so
    the command shown in the UI is the command that would actually run.

    Returns the private key path to use, or None for "leave the flag off". The
    caller passes that straight to the runner, which keeps the check and its
    result in one place instead of resolving the name a second time.
    """
    data = read_inventory()

    if body.group not in get_groups(data):
        raise HTTPException(status_code=400, detail=f"Unknown group: {body.group}")

    if body.host and body.host not in get_host_names(data, body.group):
        raise HTTPException(
            status_code=400, detail=f"Unknown host in {body.group}: {body.host}"
        )

    if body.user not in ALLOWED_USERS:
        raise HTTPException(
            status_code=400, detail=f"User must be one of {ALLOWED_USERS}"
        )

    return validate_private_key(body)


def validate_private_key(body):
    """Turn a key name into a path, or reject it.

    Returns the absolute path to use, or None to leave --private-key off.

    The name is resolved against the keys discovered on disk rather than joined
    onto a directory, so "../id_rsa" and "/etc/shadow" are not rejected by a
    pattern that has to anticipate them — they simply are not in the set of
    names that exist, which is the same reason an unknown host is rejected.
    """
    if not body.private_key:
        return None

    path, encrypted = resolve_key(body.private_key)

    if path is None:
        available = [key["name"] for key in list_keys()]
        raise HTTPException(
            status_code=400,
            detail=f"Unknown private key: {body.private_key}. Available: {available}",
        )

    # An encrypted key cannot work here and fails in a way that reads like a
    # connection problem. ansible-playbook has no flag for a key passphrase —
    # only ssh-agent can supply one — so refuse it now with the actual remedy
    # instead of returning "Permission denied (publickey)" three minutes later.
    if encrypted:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{body.private_key} is passphrase-protected, and ansible has no "
                "way to supply a passphrase. Load it into ssh-agent instead "
                f"(ssh-add ~/.ssh/{body.private_key}) and leave this unset."
            ),
        )

    return path


def validate_jit(body):
    """Check the JIT fields on top of the target check.

    The first two rules mirror roles/jit/tasks/main.yml so a bad value is caught
    here instead of two seconds later in an ansible assert. The charset and the
    newline rule are stricter than the role, for the reasons given inline.
    """
    if body.action not in JIT_ACTIONS:
        raise HTTPException(
            status_code=400, detail=f"Action must be one of {JIT_ACTIONS}"
        )

    # jit_username reaches task names and the user module. Jinja braces in it
    # would be a template injection, so pin the charset rather than only the
    # jit_ prefix the role checks.
    if not re.match(JIT_USERNAME_PATTERN, body.username):
        raise HTTPException(
            status_code=400,
            detail="Username must match jit_ followed by 1-28 lowercase letters, digits, - or _",
        )

    # revoke.yml never reads the key, so it is only required to provision.
    if body.action != "provision":
        return

    if not body.publickey.startswith(JIT_KEY_PREFIXES):
        raise HTTPException(
            status_code=400,
            detail=f"Public key must start with one of {list(JIT_KEY_PREFIXES)}",
        )

    # authorized_key treats a multi-line value as several keys, so a newline
    # could smuggle in a second, unaudited key.
    if "\n" in body.publickey or "\r" in body.publickey:
        raise HTTPException(
            status_code=400, detail="Public key must be a single line"
        )


def list_users_extra_vars(body):
    return {"ansible_user": body.user, "list_users_target": body.group}


def jit_extra_vars(body):
    extra = {
        "ansible_user": body.user,
        "jit_target": body.group,
        "jit_action": body.action,
        "jit_username": body.username,
    }
    if body.action == "provision":
        extra["jit_publickey"] = body.publickey
    return extra


def command_response(playbook, host, extra_vars, private_key=None):
    """Both preview routes return the command in the same two forms."""
    command = build_command(playbook, host, extra_vars, private_key)
    return {
        "command": shlex.join(command),
        "command_pretty": format_command(command),
    }


@app.get("/api/jit/actions")
def jit_actions():
    """The dropdown reads the allowlist so the two never drift apart."""
    return {"actions": JIT_ACTIONS}


@app.post("/api/jit/preview")
def jit_preview(body: JitRequest):
    private_key = validate_target(body)
    validate_jit(body)
    return command_response(
        JIT_PLAYBOOK, body.host, jit_extra_vars(body), private_key
    )


@app.post("/api/jit/run")
def jit_run(body: JitRequest):
    private_key = validate_target(body)
    validate_jit(body)
    return run_playbook(JIT_PLAYBOOK, body.host, jit_extra_vars(body), private_key)


@app.post("/api/preview")
def preview(body: RunRequest):
    """Show the exact command these inputs would produce, without running it.

    Uses the same build_command() the runner uses, so the panel can never drift
    from what actually executes.
    """
    private_key = validate_target(body)
    return command_response(
        LIST_USERS_PLAYBOOK, body.host, list_users_extra_vars(body), private_key
    )


@app.post("/api/run")
def run(body: RunRequest):
    """Validate every field, then run the playbook and return its output."""
    private_key = validate_target(body)
    return run_playbook(
        LIST_USERS_PLAYBOOK, body.host, list_users_extra_vars(body), private_key
    )


@app.get("/healthz")
def healthz():
    """Report ok only if the database is actually readable.

    The point of a health check is that it can fail. Returning a literal
    {"status": "ok"} proves the process accepted a socket and nothing else, so
    this opens the database and reads from both tables instead.

    Two details make the difference between a real check and a tautology:

    mode=ro
        sqlite3.connect() on a plain path CREATES a missing database and
        succeeds. A probe written that way can never report a missing file — it
        manufactures an empty one and calls it healthy. The read-only URI raises
        instead, and never mutates the file it is inspecting.

    SELECT count(*)
        connect() is lazy and does no I/O until a statement runs, so a corrupt
        file opens cleanly. Touching both tables forces the read and also
        catches schema drift, not just a missing or unreadable file.

    Known cost of mode=ro: the database is in WAL mode, and WAL readers need to
    create a -shm sidecar, so an unwritable directory fails the check even
    though the file is intact. That is reported as unhealthy on purpose — a
    directory this service cannot write is one it cannot record a job into.
    """
    try:
        with closing(
            sqlite3.connect(
                f"file:{DB_PATH}?mode=ro",
                uri=True,
                timeout=HEALTH_DB_TIMEOUT_SECONDS,
            )
        ) as connection:
            jobs = connection.execute("SELECT count(*) FROM jobs").fetchone()[0]
            grants = connection.execute("SELECT count(*) FROM grants").fetchone()[0]
    except (sqlite3.Error, OSError) as error:
        # 503, not 500: the service is up but a dependency is not, which is
        # what tells a load balancer to stop sending traffic.
        raise HTTPException(
            status_code=503, detail=f"database unavailable: {error}"
        )

    return {"status": "ok", "database": str(DB_PATH), "jobs": jobs, "grants": grants}


class NoCacheStaticFiles(StaticFiles):
    """Serve the dashboard so the browser always revalidates.

    StaticFiles sends ETag and Last-Modified but no Cache-Control, so browsers
    fall back to heuristic caching and can keep running a previous app.js after
    a redeploy — which looks exactly like the dashboard failing to update.
    "no-cache" means revalidate, not refetch: with the ETag still in place an
    unchanged file costs a 304 and no body.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Mounted last, and at "/", so it does not shadow the /api routes above.
app.mount("/", NoCacheStaticFiles(directory=str(STATIC_DIR), html=True), name="static")
