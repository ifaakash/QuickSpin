"""MySQL storage for jobs and grants.

Two tables, because they are two different kinds of thing:

  jobs    an event. It happened, it had an exit code, it is immutable after.
  grants  state. It exists over a period and changes: active -> revoked.

One grant produces two jobs — the provision that opened it and the revoke that
closed it — and some jobs (list-users) produce no grant at all. Keeping them in
one table would mean parsing playbook output to answer "who has access now?".


Notes on the move from SQLite, where the reasoning genuinely changed:

Timestamps are DATETIME(6) columns, not ISO8601 text. SQLite has no date type,
so text was the only honest option there; MySQL does, and a real type means the
server can compare and index the values rather than relying on the happy
accident that UTC ISO8601 sorts correctly as a string.

DATETIME, not TIMESTAMP. TIMESTAMP silently converts to and from the session's
time zone, so the same row reads back differently depending on who connects.
DATETIME stores exactly what it is given, so everything is written as UTC at the
boundary in to_db() and given its tzinfo back in from_db(). Connections also pin
the session to +00:00, so NOW() and any hand-written query agree with that.

stdout and stderr are MEDIUMTEXT. TEXT holds 64KB, and a verbose ansible run
passes that easily — MySQL in strict mode then rejects the whole INSERT, which
would lose the audit record for exactly the runs most worth having one.

The index is declared inside CREATE TABLE. MySQL has no
CREATE INDEX IF NOT EXISTS, so a separate statement would fail on every start
after the first; declared inline it inherits the table's IF NOT EXISTS.
"""

import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pymysql
import pymysql.cursors

from .config import (
    DB_CONNECT_TIMEOUT_SECONDS,
    DB_READ_TIMEOUT_SECONDS,
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)

# A database name cannot be passed as a parameter — placeholders only work for
# values — so it is interpolated into CREATE DATABASE. It comes from the
# environment rather than from a request, but this codebase validates everything
# that reaches a command or a statement, and the same rule applies here.
DATABASE_NAME_PATTERN = r"^[A-Za-z0-9_]{1,64}$"

# jobs is created first: grants carries foreign keys pointing at it, and InnoDB
# enforces them at creation time rather than ignoring them like SQLite did
# without PRAGMA foreign_keys.
SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id            BIGINT       NOT NULL AUTO_INCREMENT,
        playbook      VARCHAR(255) NOT NULL,
        action        VARCHAR(32),
        target_group  VARCHAR(255) NOT NULL,
        target_host   VARCHAR(255),
        run_as        VARCHAR(64)  NOT NULL,
        command       TEXT         NOT NULL,
        returncode    INT,
        stdout        MEDIUMTEXT,
        stderr        MEDIUMTEXT,
        started_at    DATETIME(6)  NOT NULL,
        duration      DOUBLE,
        triggered_by  VARCHAR(64)  NOT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS grants (
        id                BIGINT       NOT NULL AUTO_INCREMENT,
        username          VARCHAR(64)  NOT NULL,
        target_group      VARCHAR(255) NOT NULL,
        target_host       VARCHAR(255),
        run_as            VARCHAR(64)  NOT NULL,
        granted_at        DATETIME(6)  NOT NULL,
        expires_at        DATETIME(6)  NOT NULL,
        status            VARCHAR(32)  NOT NULL,
        provision_job_id  BIGINT,
        revoke_job_id     BIGINT,
        revoke_attempts   INT          NOT NULL DEFAULT 0,
        last_error        TEXT,
        PRIMARY KEY (id),
        -- The expire command's only query: active grants that are already due.
        KEY idx_grants_due (status, expires_at),
        CONSTRAINT fk_grants_provision_job
            FOREIGN KEY (provision_job_id) REFERENCES jobs (id),
        CONSTRAINT fk_grants_revoke_job
            FOREIGN KEY (revoke_job_id) REFERENCES jobs (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

# Columns read back as datetimes, so from_db() knows what to re-tag as UTC.
DATETIME_COLUMNS = ("started_at", "granted_at", "expires_at")


def utcnow():
    """One place that decides what 'now' means. Always UTC."""
    return datetime.now(timezone.utc)


def to_db(moment):
    """Convert an aware datetime to what a DATETIME column should hold.

    DATETIME keeps no offset, so the only way a stored value means anything is
    if every writer agrees on the zone. Convert to UTC and drop the tzinfo, so
    a caller that hands over an IST timestamp still stores the right instant.
    """
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def from_db(value):
    """Re-attach UTC to a value the driver handed back naive.

    Without this, a row's expires_at could not be compared with utcnow() at all
    — Python raises on naive vs aware — and any code that got away with it would
    be reading a UTC number as if it were local time.
    """
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc)


def _row(row):
    """Normalise one result row, or None."""
    if row is None:
        return None
    return {
        key: from_db(value) if key in DATETIME_COLUMNS else value
        for key, value in row.items()
    }


def _connect_kwargs(database):
    return {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "database": database,
        "charset": "utf8mb4",
        # Rows come back as dicts, which is what sqlite3.Row gave the old code,
        # so callers still index by column name instead of by position.
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": DB_CONNECT_TIMEOUT_SECONDS,
        "read_timeout": DB_READ_TIMEOUT_SECONDS,
        "write_timeout": DB_READ_TIMEOUT_SECONDS,
        # Explicit transactions, so a failed multi-statement operation leaves
        # nothing half-applied.
        "autocommit": False,
        # Pin the session to UTC so NOW(), CURDATE() and any query written by
        # hand agree with the values to_db() writes.
        "init_command": "SET time_zone = '+00:00'",
    }


@contextmanager
def connect():
    """A connection per operation, committed on success, rolled back on error.

    SQLite connections were essentially free, so opening one per call cost
    nothing. A MySQL connection is a TCP handshake plus authentication — a few
    milliseconds on a cluster network. That is still the right trade for a
    dashboard at human pace, and it keeps the failure model simple: nothing
    holds a connection across requests, so a MySQL restart cannot leave the app
    wedged on a socket that is no longer alive. Add pooling when a real
    throughput number says to, not before.
    """
    connection = pymysql.connect(**_connect_kwargs(MYSQL_DATABASE))
    try:
        yield connection
        connection.commit()
    except Exception:
        # SQLite's close() discarded an open transaction for us. Being explicit
        # costs one line and does not depend on driver behaviour.
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    """Create the database and tables if they are not there.

    Safe to call on every start, and safe to call from several replicas at once:
    every statement is IF NOT EXISTS, and MySQL serialises concurrent DDL on the
    same object rather than letting two of them interleave.

    The database itself is created too, not just the tables. A SQLite file
    appeared the moment something opened it; a MySQL schema does not, so without
    this the API would need whoever deployed it to have run a CREATE DATABASE by
    hand first, and would report nothing more useful than "Unknown database".
    """
    if not re.match(DATABASE_NAME_PATTERN, MYSQL_DATABASE):
        raise ValueError(
            f"MYSQL_DATABASE must match {DATABASE_NAME_PATTERN}, got {MYSQL_DATABASE!r}"
        )

    # No database selected: the point is that it may not exist yet.
    server = pymysql.connect(**_connect_kwargs(None))
    try:
        with server.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
                "CHARACTER SET utf8mb4"
            )
        server.commit()
    finally:
        server.close()

    with connect() as connection:
        with connection.cursor() as cursor:
            for statement in SCHEMA:
                cursor.execute(statement)


def ping():
    """Read both tables and return their row counts, or raise.

    This is what /healthz calls. Connecting already proves more than it did with
    SQLite — it is a real TCP and authentication round trip, which a wrong host,
    a wrong password or a pod that is not up all fail. Counting rows in both
    tables is still worth doing on top of that: it is what catches connecting
    successfully to a database whose schema is missing or has drifted.
    """
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) AS total FROM jobs")
            jobs = cursor.fetchone()["total"]
            cursor.execute("SELECT count(*) AS total FROM grants")
            grants = cursor.fetchone()["total"]
    return jobs, grants


# ---------- jobs ----------

def record_job(playbook, action, group, host, run_as, result, triggered_by):
    """Store one playbook run and return its id.

    `result` is whatever run_playbook() returned, so the stored command is the
    exact one that executed rather than a reconstruction of it.
    """
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO jobs (playbook, action, target_group, target_host,
                                     run_as, command, returncode, stdout, stderr,
                                     started_at, duration, triggered_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(playbook).rsplit("/", 1)[-1],
                    action,
                    group,
                    host or None,
                    run_as,
                    result["command"],
                    result["returncode"],
                    result["stdout"],
                    result["stderr"],
                    to_db(utcnow()),
                    result["duration"],
                    triggered_by,
                ),
            )
            return cursor.lastrowid


def list_jobs(limit=50):
    """Recent jobs, newest first. Output is left out — it can be megabytes."""
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, playbook, action, target_group, target_host, run_as,
                          returncode, started_at, duration, triggered_by
                   FROM jobs ORDER BY id DESC LIMIT %s""",
                (limit,),
            )
            return [_row(row) for row in cursor.fetchall()]


def get_job(job_id):
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            return _row(cursor.fetchone())


# ---------- grants ----------

def create_grant(username, group, host, run_as, ttl_minutes, provision_job_id):
    """Open a grant. Called only after a provision playbook returned rc=0."""
    granted = utcnow()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO grants (username, target_group, target_host, run_as,
                                       granted_at, expires_at, status,
                                       provision_job_id)
                   VALUES (%s,%s,%s,%s,%s,%s,'active',%s)""",
                (
                    username,
                    group,
                    host or None,
                    run_as,
                    to_db(granted),
                    to_db(granted + timedelta(minutes=ttl_minutes)),
                    provision_job_id,
                ),
            )
            return cursor.lastrowid


def active_grants():
    """Every grant still believed to be live, soonest expiry first."""
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT * FROM grants
                   WHERE status IN ('active', 'revoke_failed')
                   ORDER BY expires_at ASC"""
            )
            return [_row(row) for row in cursor.fetchall()]


def due_grants(now=None):
    """Grants that should already be gone.

    revoke_failed is included on purpose: a failed revoke must be retried, and
    `user: state=absent` is idempotent so retrying costs nothing.
    """
    moment = to_db(now or utcnow())
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT * FROM grants
                   WHERE status IN ('active', 'revoke_failed') AND expires_at <= %s
                   ORDER BY expires_at ASC""",
                (moment,),
            )
            return [_row(row) for row in cursor.fetchall()]


def find_active_grant(username, group, host):
    """The open grant a manual revoke should close, if there is one.

    target_host is compared with <=>, the NULL-safe equality operator. A plain
    `= NULL` is never true, so a group-wide grant — which stores NULL — could
    never be found again; SQLite needed `IS ? OR = ?` to cover both cases, and
    MySQL has one operator that does it.
    """
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT * FROM grants
                   WHERE username = %s AND target_group = %s
                     AND target_host <=> %s
                     AND status IN ('active', 'revoke_failed')
                   ORDER BY id DESC LIMIT 1""",
                (username, group, host or None),
            )
            return _row(cursor.fetchone())


def mark_grant_revoked(grant_id, revoke_job_id):
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE grants
                   SET status = 'revoked', revoke_job_id = %s, last_error = NULL
                   WHERE id = %s""",
                (revoke_job_id, grant_id),
            )


def mark_grant_failed(grant_id, revoke_job_id, error):
    """Record that revoke ran and did not work.

    The status stays 'revoke_failed', never 'revoked'. A grant marked revoked
    that was not is worse than one still marked active — it tells you the
    account is gone when it is still on the host.
    """
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE grants
                   SET status = 'revoke_failed',
                       revoke_job_id = %s,
                       revoke_attempts = revoke_attempts + 1,
                       last_error = %s
                   WHERE id = %s""",
                (revoke_job_id, (error or "")[-2000:], grant_id),
            )
