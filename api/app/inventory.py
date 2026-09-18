"""Read groups and hosts out of the Ansible inventory.

We shell out to `ansible-inventory --list` instead of parsing the INI by hand.
Ansible already knows how to handle [group:vars], [group:children] and YAML
inventories, so borrowing its parser keeps this file short and keeps the API
honest if dashboard.ini ever grows beyond a flat host list.
"""

import json
import subprocess

from .config import INVENTORY_FILE, INVENTORY_TIMEOUT_SECONDS, ansible_env

# Bookkeeping keys ansible-inventory always emits. They are not real groups.
SKIP_KEYS = {"_meta", "all", "ungrouped"}


def load_inventory():
    """Return the parsed `ansible-inventory --list` JSON as a dict."""
    result = subprocess.run(
        ["ansible-inventory", "-i", str(INVENTORY_FILE), "--list"],
        capture_output=True,
        text=True,
        env=ansible_env(),
        timeout=INVENTORY_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ansible-inventory failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def get_groups(data):
    """Group names that actually contain hosts, sorted."""
    groups = []
    for key, value in data.items():
        if key in SKIP_KEYS:
            continue
        if value.get("hosts"):
            groups.append(key)
    return sorted(groups)


def get_hosts(data, group):
    """Hosts in one group as [{name, ip, label}].

    The dropdown label is built here rather than in JavaScript so there is one
    place that decides how a host is written out.
    """
    hostvars = data.get("_meta", {}).get("hostvars", {})
    hosts = []
    for name in data.get(group, {}).get("hosts", []):
        ip = hostvars.get(name, {}).get("ansible_host", "no ansible_host")
        hosts.append({"name": name, "ip": ip, "label": f"{name} ({ip})"})
    return hosts


def get_host_names(data, group):
    """Just the host names in a group, for validation."""
    return [host["name"] for host in get_hosts(data, group)]
