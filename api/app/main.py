"""FastAPI service behind the QuickSpin dashboard.

Four read endpoints feed the dropdowns, one POST runs the playbook. Serve it on
localhost only: it executes commands on remote hosts and has no authentication.
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ALLOWED_USERS, STATIC_DIR
from .inventory import get_groups, get_host_names, get_hosts, load_inventory
import shlex

from .runner import build_command, format_command, run_playbook

app = FastAPI(title="QuickSpin Dashboard API")


class RunRequest(BaseModel):
    """Body of POST /api/run. An empty host means the whole group."""

    group: str
    host: str = ""
    user: str


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


def validate_request(body):
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


@app.post("/api/preview")
def preview(body: RunRequest):
    """Show the exact command these inputs would produce, without running it.

    Uses the same build_command() the runner uses, so the panel can never drift
    from what actually executes.
    """
    validate_request(body)
    command = build_command(body.group, body.host, body.user)
    return {
        "command": shlex.join(command),
        "command_pretty": format_command(command),
    }


@app.post("/api/run")
def run(body: RunRequest):
    """Validate every field, then run the playbook and return its output."""
    validate_request(body)
    return run_playbook(body.group, body.host, body.user)


# Mounted last, and at "/", so it does not shadow the /api routes above.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
