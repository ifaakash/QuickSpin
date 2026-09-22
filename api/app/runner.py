"""Build and execute the ansible-playbook command.

The command is always a list, never a string, and subprocess is never given
shell=True. No shell is involved at any point, so nothing in the input can be
interpreted as a shell metacharacter. Validation still happens in main.py
before we get here, because the values also have to be real inventory entries.
"""

import json
import shlex
import subprocess
import time

from .config import (
    ANSIBLE_DIR,
    INVENTORY_FILE,
    RUN_TIMEOUT_SECONDS,
    ansible_env,
)


def build_command(playbook, host, extra_vars, private_key=None):
    """Assemble the ansible-playbook argument list.

    Extra vars go as ONE JSON object. This is not a style choice: `-e "a=1 b=2"`
    defines two variables, so a value containing spaces — an SSH public key, say —
    is silently shredded into junk. json.dumps cannot be split that way.

    An empty host means "every host in the group", so --limit is left off.

    private_key is likewise omitted when absent rather than passed empty. There
    is no neutral value for --private-key: given "" ssh treats it as a real
    filename, fails to read it, and stops trying the keys it would otherwise
    have used. Leaving the flag off is what preserves the normal behaviour of
    falling back to the agent and to ansible.cfg.
    """
    command = [
        "ansible-playbook",
        "-i", str(INVENTORY_FILE),
        str(playbook),
        "-e", json.dumps(extra_vars),
    ]
    if host:
        command += ["--limit", host]
    if private_key:
        command += ["--private-key", str(private_key)]
    return command


def format_command(command):
    """Pretty-print the argv list as a runnable multi-line shell command.

    Pairs each flag with its value on one line so the panel reads like something
    you would type. Safe because every value is validated first and none of them
    can start with a dash.
    """
    parts = [shlex.quote(arg) for arg in command]
    lines = [parts[0]]
    index = 1
    while index < len(parts):
        is_flag = parts[index].startswith("-")
        has_value = index + 1 < len(parts) and not parts[index + 1].startswith("-")
        if is_flag and has_value:
            lines.append(f"{parts[index]} {parts[index + 1]}")
            index += 2
        else:
            lines.append(parts[index])
            index += 1
    return " \\\n  ".join(lines)


def run_playbook(playbook, host, extra_vars, private_key=None):
    """Run the playbook and return a result dict for the dashboard.

    cwd is the Ansible directory so the playbook's roles/ resolve normally.
    """
    command = build_command(playbook, host, extra_vars, private_key)
    started = time.monotonic()

    try:
        result = subprocess.run(
            command,
            cwd=str(ANSIBLE_DIR),
            capture_output=True,
            text=True,
            env=ansible_env(),
            timeout=RUN_TIMEOUT_SECONDS,
            # No stdin. ssh asks for a key passphrase interactively, and an
            # inherited terminal would leave that prompt waiting on a descriptor
            # nobody is watching until RUN_TIMEOUT_SECONDS expires. Closed stdin
            # turns that hang into an immediate, readable failure.
            stdin=subprocess.DEVNULL,
        )
        stdout = result.stdout
        stderr = result.stderr
        returncode = result.returncode
    except subprocess.TimeoutExpired as expired:
        # Surface whatever ansible managed to print before we killed it.
        stdout = expired.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        stderr = f"Timed out after {RUN_TIMEOUT_SECONDS}s and was killed."
        returncode = -1

    return {
        "ok": returncode == 0,
        "returncode": returncode,
        "command": shlex.join(command),
        "command_pretty": format_command(command),
        "stdout": stdout,
        "stderr": stderr,
        "duration": round(time.monotonic() - started, 1),
    }
