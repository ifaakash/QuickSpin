"""Paths and allowlists for the QuickSpin dashboard API.

Everything is resolved absolutely from this file's own location, so the API
behaves the same no matter which directory uvicorn was started from.
"""

import os
from pathlib import Path

# api/app/config.py -> api/app -> api -> QuickSpin
REPO_ROOT = Path(__file__).resolve().parents[2]

ANSIBLE_DIR = REPO_ROOT / "Ansible"
ANSIBLE_CFG = ANSIBLE_DIR / "ansible.cfg"
inventory_name = os.getenv("INVENTORY_FILE_NAME", "homelab.ini")
INVENTORY_FILE = ANSIBLE_DIR / "inventories" / inventory_name
LIST_USERS_PLAYBOOK = ANSIBLE_DIR / "playbook-list-users.yml"
JIT_PLAYBOOK = ANSIBLE_DIR / "playbook-jit-access.yml"

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Directories searched for private keys offered to --private-key, in order.
# Colon-separated like PATH, so one variable covers every environment: ~/.ssh on
# a laptop, /root/.ssh in a plain container, and a mounted Secret under k3s.
# Missing directories are skipped, so the default can name all of them and each
# environment simply finds the ones it has.
#
# SSH_KEY_DIR (singular) is still honoured, so a deployment that sets only that
# keeps working.
DEFAULT_SSH_KEY_DIRS = ":".join([str(Path.home() / ".ssh"), "/secrets"])

ssh_key_dirs = os.getenv(
    "SSH_KEY_DIRS", os.getenv("SSH_KEY_DIR", DEFAULT_SSH_KEY_DIRS)
)
SSH_KEY_DIRS = [
    Path(part).expanduser() for part in ssh_key_dirs.split(":") if part.strip()
]

# ---------------------------------------------------------------------------
# MySQL
#
# The jobs and grants store. It is a network service now rather than a file next
# to the code, which is the point of the move: every replica talks to one
# database instead of carrying a private copy that silently disagrees with the
# others the moment the Deployment scales past one pod.
#
# Names are unprefixed, matching INVENTORY_FILE_NAME and SSH_KEY_DIRS, so
# everything in this file is configured the same way.
# ---------------------------------------------------------------------------
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "devopshub")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "devopshub")


def _mysql_password():
    """Read the password from a file when one is named, otherwise from the env.

    MYSQL_PASSWORD_FILE exists because a mounted Secret can be mode 0400, while
    an environment variable is readable from /proc/<pid>/environ and is inherited
    by every child process — and this API spawns ansible-playbook, so the
    database password would be sitting in the environment of a process that
    connects to other machines. The file wins when both are set.
    """
    path = os.getenv("MYSQL_PASSWORD_FILE")
    if path:
        return Path(path).read_text().strip()
    return os.getenv("MYSQL_PASSWORD", "")


MYSQL_PASSWORD = _mysql_password()

# What the API reports it is pointed at, for /healthz and error text. Assembled
# without the password so neither can ever leak it.
DB_DESCRIPTION = f"{MYSQL_USER}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"

# The only values accepted for ansible_user. Anything else is rejected before
# a command is built, so this list is the entire user-input surface.
ALLOWED_USERS = ["root", "ubuntu"]

# JIT access rules. The first three mirror roles/jit/tasks/main.yml so the UI
# can reject instantly instead of after a two-second ansible run.
JIT_ACTIONS = ["provision", "revoke"]
JIT_KEY_PREFIXES = ("ssh-rsa", "ssh-ed25519")

# Stricter than the role, which only checks the jit_ prefix. jit_username is
# interpolated into task names and handed to the user module, so a value holding
# Jinja braces would be a template injection. Pin the charset here.
JIT_USERNAME_PATTERN = r"^jit_[a-z0-9_-]{1,28}$"

# Kill a playbook that hangs, rather than holding the HTTP request forever.
RUN_TIMEOUT_SECONDS = 300

# ansible-inventory only reads a file, so it gets a much shorter leash.
INVENTORY_TIMEOUT_SECONDS = 30

# Bound every stage of a database call: the TCP connect, and each read and
# write on the socket. A health check has to answer or fail fast, and an
# unreachable MySQL pod otherwise hangs connect() for the OS default of over a
# minute — long enough that the probe times out without ever reporting why.
DB_CONNECT_TIMEOUT_SECONDS = 5
DB_READ_TIMEOUT_SECONDS = 10

# init_db() runs at startup, where the app almost always wins the race against
# MySQL becoming ready — a file-backed database had nothing to race. Retry
# instead of dying on the first refused connection.
DB_INIT_RETRIES = 10
DB_INIT_RETRY_DELAY_SECONDS = 3


def ansible_env():
    """Environment for every ansible subprocess we spawn.

    ANSIBLE_CONFIG must be absolute. Ansible/README.md spells out why: the repo
    sets no roles_path, so anything calling these playbooks from outside the
    Ansible directory has to point at the config file explicitly.

    Colour is forced off so no ANSI escape codes end up in the browser output.
    """
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(ANSIBLE_CFG)
    env["ANSIBLE_FORCE_COLOR"] = "0"
    return env
