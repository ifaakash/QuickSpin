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
INVENTORY_FILE = ANSIBLE_DIR / "inventories" / "dashboard.ini"
PLAYBOOK_FILE = ANSIBLE_DIR / "playbook-list-users.yml"

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The only values accepted for ansible_user. Anything else is rejected before
# a command is built, so this list is the entire user-input surface.
ALLOWED_USERS = ["root", "ubuntu"]

# Kill a playbook that hangs, rather than holding the HTTP request forever.
RUN_TIMEOUT_SECONDS = 300

# ansible-inventory only reads a file, so it gets a much shorter leash.
INVENTORY_TIMEOUT_SECONDS = 30


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
