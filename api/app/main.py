"""FastAPI service behind the QuickSpin dashboard.

Four read endpoints feed the dropdowns, one POST runs the playbook. Serve it on
localhost only: it executes commands on remote hosts and has no authentication.
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import asyncio
import re
import sys
from contextlib import asynccontextmanager

import pymysql

from .config import (
    ALLOWED_USERS,
    DB_DESCRIPTION,
    DB_INIT_RETRIES,
    DB_INIT_RETRY_DELAY_SECONDS,
    JIT_ACTIONS,
    JIT_KEY_PREFIXES,
    JIT_PLAYBOOK,
    JIT_TTL_CHOICES,
    JIT_TTL_DEFAULT_MINUTES,
    JIT_TTL_MAX_MINUTES,
    JIT_USERNAME_PATTERN,
    LIST_USERS_PLAYBOOK,
    STATIC_DIR,
)
from .db import (
    active_grants,
    create_grant,
    find_active_grant,
    get_job,
    init_db,
    list_jobs,
    mark_grant_revoked,
    ping,
    record_job,
)
from .inventory import get_groups, get_host_names, get_hosts, load_inventory
from .keys import list_directories, list_keys, resolve_key
import shlex

from .runner import build_command, format_command, jit_extra_vars, run_playbook


@asynccontextmanager
async def lifespan(app):
    """Create the schema before serving, retrying while MySQL comes up.

    A file-backed database was ready the instant the process was. A MySQL server
    is a separate pod with its own startup, and the API almost always wins that
    race, so the first connection attempt being refused is normal rather than an
    error worth dying over.

    If it never comes up we still start. Exiting here would mean the container
    restarts forever with the reason buried in a log nobody has kubectl open
    for; starting means /healthz answers 503 with the actual driver error, the
    readiness probe keeps the pod out of the Service, and the failure is one
    curl away. That is the entire reason for having a health check that can
    fail.
    """
    for attempt in range(1, DB_INIT_RETRIES + 1):
        try:
            init_db()
            break
        except (pymysql.MySQLError, OSError) as error:
            if attempt == DB_INIT_RETRIES:
                print(
                    f"init_db failed after {attempt} attempts, serving anyway "
                    f"({DB_DESCRIPTION}): {error}",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                print(
                    f"waiting for MySQL at {DB_DESCRIPTION} "
                    f"(attempt {attempt}/{DB_INIT_RETRIES}): {error}",
                    file=sys.stderr,
                    flush=True,
                )
                await asyncio.sleep(DB_INIT_RETRY_DELAY_SECONDS)
    yield


app = FastAPI(title="QuickSpin Dashboard API", lifespan=lifespan)


class RunRequest(BaseModel):
    """Body of POST /api/run. An empty host means the whole group.

    private_key identifies a key listed by GET /api/ssh-keys, normally by its
    absolute path; a bare filename also resolves if it is unambiguous. Either
    way it must match a key this service discovered, so it is a choice from a
    list rather than a path the caller invents.

    Empty means "do not pass --private-key at all", which leaves ssh to use the
    agent or whatever ansible.cfg specifies.
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
    # How long the grant may live. Defaulted rather than optional, because a
    # request that forgets to say would otherwise mean "forever".
    ttl_minutes: int = JIT_TTL_DEFAULT_MINUTES


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

    Covers every directory in SSH_KEY_DIRS, so keys on a mounted volume appear
    beside the ones in ~/.ssh. Each entry carries its directory, so two keys
    with the same filename on different mounts stay distinguishable, and
    `encrypted`, so the dropdown can show which keys cannot be used and why
    instead of offering a choice that is certain to be rejected.

    Paths are returned because the dropdown submits one back as the chosen key.
    They are still only ever paths this service found itself — key material is
    never returned.
    """
    return {"keys": list_keys(), "directories": list_directories()}


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
        available = [key["path"] for key in list_keys()]
        searched = [entry["path"] for entry in list_directories()]
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown private key: {body.private_key}. "
                f"Searched {searched}. Available: {available}"
            ),
        )

    # An encrypted key cannot work here and fails in a way that reads like a
    # connection problem. ansible-playbook has no flag for a key passphrase —
    # only ssh-agent can supply one — so refuse it now with the actual remedy
    # instead of returning "Permission denied (publickey)" three minutes later.
    if encrypted:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{path} is passphrase-protected, and ansible has no way to "
                "supply a passphrase. Load it into ssh-agent instead "
                f"(ssh-add {path}) and leave this unset."
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

    # Checked here and not only in the dropdown: the dropdown is a suggestion,
    # the API is the boundary. A caller with curl is the one that matters.
    if not 1 <= body.ttl_minutes <= JIT_TTL_MAX_MINUTES:
        raise HTTPException(
            status_code=400,
            detail=f"ttl_minutes must be between 1 and {JIT_TTL_MAX_MINUTES}",
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


def command_response(playbook, host, extra_vars, private_key=None):
    """Both preview routes return the command in the same two forms."""
    command = build_command(playbook, host, extra_vars, private_key)
    return {
        "command": shlex.join(command),
        "command_pretty": format_command(command),
    }


def record_run(result, playbook, action, body):
    """Store a finished run and return its job id, or None if the write failed.

    Called only after the playbook has already executed, which decides how a
    database failure has to be handled. The account really was created on the
    host, so turning a successful run into an HTTP error would tell the operator
    the opposite of the truth — the one lie this service must never tell. The
    run is returned either way and persistence_error carries the gap, so a
    missing audit record is visible instead of silent.
    """
    try:
        return record_job(
            playbook=playbook,
            action=action,
            group=body.group,
            host=body.host,
            run_as=body.user,
            result=result,
            triggered_by="dashboard",
        )
    except (pymysql.MySQLError, OSError) as error:
        print(f"record_job failed: {error}", file=sys.stderr)
        result["persistence_error"] = f"run not recorded: {error}"
        return None


@app.get("/api/jit/actions")
def jit_actions():
    """The dropdown reads the allowlist so the two never drift apart."""
    return {"actions": JIT_ACTIONS}


@app.get("/api/jit/ttl")
def jit_ttl():
    """The dropdown reads these so the UI and the ceiling never drift apart."""
    return {
        "choices": JIT_TTL_CHOICES,
        "default": JIT_TTL_DEFAULT_MINUTES,
        "max": JIT_TTL_MAX_MINUTES,
    }


@app.post("/api/jit/preview")
def jit_preview(body: JitRequest):
    private_key = validate_target(body)
    validate_jit(body)
    return command_response(
        JIT_PLAYBOOK, body.host, jit_extra_vars(
            run_as=body.user,
            group=body.group,
            action=body.action,
            username=body.username,
            publickey=body.publickey,
        ), private_key
    )


@app.post("/api/jit/run")
def jit_run(body: JitRequest):
    """Run the JIT playbook, record the job, and open or close the grant."""
    private_key = validate_target(body)
    validate_jit(body)

    result = run_playbook(JIT_PLAYBOOK, body.host, jit_extra_vars(
            run_as=body.user,
            group=body.group,
            action=body.action,
            username=body.username,
            publickey=body.publickey,
        ), private_key)
    job_id = record_run(result, JIT_PLAYBOOK, body.action, body)
    result["job_id"] = job_id

    # State only changes when ansible actually succeeded. A failed provision
    # must not leave a grant behind for the expire command to chase, and a
    # failed revoke must not mark one closed that is still on the host.
    #
    # job_id being None means the database is unreachable, so there is nothing
    # to hang a grant off and no point trying — the grant's provision_job_id is
    # a foreign key into the row that just failed to write.
    if not result["ok"] or job_id is None:
        return result

    try:
        if body.action == "provision":
            result["grant_id"] = create_grant(
                username=body.username,
                group=body.group,
                host=body.host,
                run_as=body.user,
                ttl_minutes=body.ttl_minutes,
                provision_job_id=job_id,
            )
        elif body.action == "revoke":
            # A revoke clicked by hand closes the same grant the schedule would
            # have, so the two paths cannot disagree about what is still open.
            grant = find_active_grant(body.username, body.group, body.host)
            if grant:
                mark_grant_revoked(grant["id"], job_id)
                result["grant_id"] = grant["id"]
    except (pymysql.MySQLError, OSError) as error:
        # Loud, because this one matters more than a missing job row: an
        # unrecorded provision is an account nothing will ever expire.
        print(f"grant write failed: {error}", file=sys.stderr)
        result["persistence_error"] = f"grant not recorded: {error}"

    return result


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

    result = run_playbook(
        LIST_USERS_PLAYBOOK, body.host, list_users_extra_vars(body), private_key
    )
    # A job with no grant. Reading the passwd file grants nobody anything, but
    # it is still someone running a command on a host, so it is still audited.
    result["job_id"] = record_run(result, LIST_USERS_PLAYBOOK, None, body)
    return result


@app.get("/api/jobs")
def jobs(limit: int = 50):
    """Recent runs, newest first. Output is left out — it can be megabytes."""
    return {"jobs": list_jobs(limit=min(limit, 200))}


@app.get("/api/jobs/{job_id}")
def job(job_id: int):
    """One run including its full stdout and stderr."""
    found = get_job(job_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No job {job_id}")
    return found


@app.get("/api/grants")
def grants():
    """Every grant still believed to be live, soonest expiry first."""
    return {"grants": active_grants()}


@app.get("/healthz")
def healthz():
    """Report ok only if the database is actually readable.

    The point of a health check is that it can fail. Returning a literal
    {"status": "ok"} proves the process accepted a socket and nothing else.

    Against SQLite this endpoint had to work to find a failure at all: opening a
    plain path CREATED the missing database and reported success, so the probe
    needed a read-only URI to avoid manufacturing the very file it was checking
    for, and a real query because connect() did no I/O on its own.

    A client-server database inverts that. Connecting is a TCP round trip and an
    authentication exchange, so a MySQL pod that is down, a wrong host, a wrong
    password or a network policy in the way all fail on their own. What
    connecting still cannot tell you is whether the schema is there, which is
    why ping() counts rows in both tables — that is what catches a healthy
    server holding an empty or drifted database.

    DB_DESCRIPTION is reported rather than any connection string, so the
    password cannot leak into a response or a log line.
    """
    try:
        jobs, grants = ping()
    except (pymysql.MySQLError, OSError) as error:
        # 503, not 500: the service is up but a dependency is not, which is
        # what tells a load balancer to stop sending traffic.
        raise HTTPException(
            status_code=503, detail=f"database unavailable: {error}"
        )

    return {
        "status": "ok",
        "database": DB_DESCRIPTION,
        "jobs": jobs,
        "grants": grants,
    }


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
