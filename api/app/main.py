"""FastAPI service behind the QuickSpin dashboard.

Four read endpoints feed the dropdowns, one POST runs the playbook. Serve it on
localhost only: it executes commands on remote hosts and has no authentication.
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import re

from .config import (
    ALLOWED_USERS,
    JIT_ACTIONS,
    JIT_KEY_PREFIXES,
    JIT_PLAYBOOK,
    JIT_USERNAME_PATTERN,
    LIST_USERS_PLAYBOOK,
    STATIC_DIR,
)
from .inventory import get_groups, get_host_names, get_hosts, load_inventory
import shlex

from .runner import build_command, format_command, run_playbook

app = FastAPI(title="QuickSpin Dashboard API")


class RunRequest(BaseModel):
    """Body of POST /api/run. An empty host means the whole group."""

    group: str
    host: str = ""
    user: str


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


def validate_target(body):
    """Reject anything not present in the inventory or on the allowlist.

    This is the security boundary. Group and host must exist in the inventory we
    just read, and the user must be on the fixed allowlist, so nothing arbitrary
    can reach the command line. Both /api/preview and /api/run go through it, so
    the command shown in the UI is the command that would actually run.
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


def command_response(playbook, host, extra_vars):
    """Both preview routes return the command in the same two forms."""
    command = build_command(playbook, host, extra_vars)
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
    validate_target(body)
    validate_jit(body)
    return command_response(JIT_PLAYBOOK, body.host, jit_extra_vars(body))


@app.post("/api/jit/run")
def jit_run(body: JitRequest):
    validate_target(body)
    validate_jit(body)
    return run_playbook(JIT_PLAYBOOK, body.host, jit_extra_vars(body))


@app.post("/api/preview")
def preview(body: RunRequest):
    """Show the exact command these inputs would produce, without running it.

    Uses the same build_command() the runner uses, so the panel can never drift
    from what actually executes.
    """
    validate_target(body)
    return command_response(LIST_USERS_PLAYBOOK, body.host, list_users_extra_vars(body))


@app.post("/api/run")
def run(body: RunRequest):
    """Validate every field, then run the playbook and return its output."""
    validate_target(body)
    return run_playbook(LIST_USERS_PLAYBOOK, body.host, list_users_extra_vars(body))


# Mounted last, and at "/", so it does not shadow the /api routes above.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
