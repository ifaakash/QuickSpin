"""Revoke every grant that is past its expiry.

This is a command, not a background thread. Point cron, a systemd timer, a
Kubernetes CronJob or an AWX Schedule at it:

    python -m app.expire              revoke everything due
    python -m app.expire --dry-run    list what is due, change nothing

Keeping it out of the web process means expiry still happens when the dashboard
is not running, and it survives `uvicorn --reload` restarting the app on every
source edit. It also means the thing that grants access and the thing that takes
it back can be scaled, scheduled and failed independently.

Safe to run twice. `user: state=absent` is idempotent, and a grant already
marked revoked is not selected again.

One copy at a time. Two concurrent runs would both see the same due grants and
both try to revoke them; the second is harmless because the playbook is
idempotent, but it writes a second job row and a second revoke_attempts bump for
work that was already done. A CronJob wanting this needs
concurrencyPolicy: Forbid.
"""

import argparse
import sys

from .config import JIT_PLAYBOOK, JIT_REVOKE_KEY
from .db import (
    due_grants,
    init_db,
    mark_grant_failed,
    mark_grant_revoked,
    record_job,
)
from .keys import resolve_key
from .runner import jit_extra_vars, run_playbook


def revoke_key():
    """The private key to revoke with, or None to leave the flag off.

    Resolved through the same allowlist the API uses, so a stray environment
    variable cannot put an arbitrary path on the command line — the value has to
    name a key this service already discovered.

    Raises SystemExit rather than returning a broken value, because a scheduled
    run that cannot authenticate should fail once, loudly, at startup instead of
    failing per grant and marking every one of them revoke_failed.
    """
    if not JIT_REVOKE_KEY:
        return None

    path, encrypted = resolve_key(JIT_REVOKE_KEY)

    if path is None:
        raise SystemExit(
            f"JIT_REVOKE_KEY={JIT_REVOKE_KEY!r} does not match any discovered key. "
            f"Check the key exists and is inside a configured key directory."
        )

    if encrypted:
        # runner.py closes stdin precisely so a passphrase prompt cannot hang on
        # a descriptor nobody is watching. An encrypted key here would therefore
        # fail every single run, so say why now rather than 480 minutes from now.
        raise SystemExit(
            f"{path} is passphrase-protected. A scheduled run has no terminal to "
            f"type it into. Use an unencrypted key, or an agent."
        )

    return path


def revoke(grant, private_key=None):
    """Run the revoke playbook for one grant and record the outcome."""
    extra_vars = jit_extra_vars(
        run_as=grant["run_as"],
        group=grant["target_group"],
        action="revoke",
        username=grant["username"],
    )
    result = run_playbook(
        JIT_PLAYBOOK, grant["target_host"], extra_vars, private_key
    )

    job_id = record_job(
        playbook=JIT_PLAYBOOK,
        action="revoke",
        group=grant["target_group"],
        host=grant["target_host"],
        run_as=grant["run_as"],
        result=result,
        # This is what makes the job list show revokes nobody asked for.
        triggered_by="scheduler",
    )

    if result["ok"]:
        mark_grant_revoked(grant["id"], job_id)
    else:
        # Deliberately not marked 'revoked'. The account may still be on the
        # host, and saying otherwise would be a lie the next run acts on.
        mark_grant_failed(grant["id"], job_id, result["stderr"] or result["stdout"])

    return result["ok"], job_id


def main(argv=None):
    parser = argparse.ArgumentParser(description="Revoke expired JIT grants.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be revoked and exit without running anything",
    )
    args = parser.parse_args(argv)

    init_db()
    due = due_grants()

    if not due:
        print("Nothing due.")
        return 0

    print(f"{len(due)} grant(s) due:")
    for grant in due:
        target = grant["target_host"] or f"{grant['target_group']} (all hosts)"
        print(
            f"  #{grant['id']}  {grant['username']} on {target}"
            f"  expired {grant['expires_at']}"
            f"  attempts={grant['revoke_attempts']}"
        )

    if args.dry_run:
        print("\n--dry-run: nothing was changed.")
        return 0

    # After the listing, so --dry-run still works on a machine with no key.
    private_key = revoke_key()

    failures = 0
    for grant in due:
        ok, job_id = revoke(grant, private_key)
        state = "revoked" if ok else "FAILED"
        print(f"  #{grant['id']} {grant['username']}: {state} (job {job_id})")
        if not ok:
            failures += 1

    # Non-zero exit so cron mails you, a CronJob records a failed run, or an AWX
    # schedule shows red. A revoke that quietly fails is the worst outcome here:
    # the dashboard says the account is gone and the host disagrees.
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
