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

# The jobs and grants database. Nothing else in this API reads or writes it yet
# — the persistence layer that does lives on feat/devopshub-dashboard — but
# /healthz probes it so the check has a real dependency that can actually fail.
DB_PATH = REPO_ROOT / "api" / "devopshub.db"

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

# A health check must answer or fail fast, never queue behind a writer holding
# the database lock. Two seconds is long enough to ride out a normal commit.
HEALTH_DB_TIMEOUT_SECONDS = 2


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
