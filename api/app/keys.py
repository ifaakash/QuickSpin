"""Discover the SSH private keys the API is allowed to hand to ansible.

Everything else that reaches the ansible-playbook argv in this service is
checked against an allowlist first — ALLOWED_USERS for the remote user, the
parsed inventory for group and host. A private key path is no different, so it
gets the same treatment: the directory is fixed by config, the keys in it are
discovered by reading them, and a request may only name one that is already
there. A caller never supplies a path.

That distinction is the whole point. Accepting a path from the browser would let
any file on the host be fed to --private-key, and ansible echoes the paths it
was given back into its error output.
"""

import base64
import struct

from .config import SSH_KEY_DIR

# Private keys are identified by reading them, not by their filename. Keys get
# named anything (id_ed25519, homelab, deploy_key), while known_hosts, config
# and *.pub all sit in the same directory and must never be offered.
PEM_START = "-----BEGIN "
PEM_PRIVATE = "PRIVATE KEY"

# Keys are a few KB at most. Cap the read so a stray large file in ~/.ssh cannot
# be slurped into memory just to answer a dropdown.
MAX_KEY_BYTES = 64 * 1024


def _first_line_and_body(text):
    """Split a PEM file into its BEGIN line and base64 body."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", ""
    body = "".join(line for line in lines[1:] if not line.startswith("-----"))
    return lines[0], body


def _openssh_cipher(body):
    """Read the cipher name out of an OpenSSH v1 key body.

    The format is the literal "openssh-key-v1\\0" followed by a length-prefixed
    cipher name. That name is "none" on an unencrypted key and the actual cipher
    (aes256-ctr, and so on) on a protected one, which is a far more reliable
    signal than looking for a header comment.
    """
    try:
        blob = base64.b64decode(body, validate=False)
    except Exception:
        return None

    marker = b"openssh-key-v1\x00"
    if not blob.startswith(marker):
        return None

    rest = blob[len(marker):]
    if len(rest) < 4:
        return None
    (length,) = struct.unpack(">I", rest[:4])
    if length > len(rest) - 4:
        return None
    return rest[4:4 + length].decode("ascii", errors="replace")


def _inspect(path):
    """Return {"name", "encrypted"} for a private key, or None if it is not one."""
    try:
        if not path.is_file():
            return None
        with path.open("r", errors="replace") as handle:
            text = handle.read(MAX_KEY_BYTES)
    except OSError:
        # An unreadable file is not an error worth failing the whole listing
        # over; it simply is not a key this service can offer.
        return None

    header, body = _first_line_and_body(text)
    if not header.startswith(PEM_START) or PEM_PRIVATE not in header:
        return None

    cipher = _openssh_cipher(body)
    if cipher is not None:
        encrypted = cipher != "none"
    else:
        # Legacy PEM keys (-----BEGIN RSA PRIVATE KEY-----) announce encryption
        # with a Proc-Type header instead of an inner cipher name.
        encrypted = "ENCRYPTED" in text[:400]

    return {"name": path.name, "encrypted": encrypted}


def list_keys():
    """Every usable private key in SSH_KEY_DIR, sorted by name.

    Reads the directory on each call rather than caching, for the same reason
    the inventory is re-read on each request: a key added or removed on disk
    must show up without restarting the service.
    """
    if not SSH_KEY_DIR.is_dir():
        return []

    keys = []
    for path in sorted(SSH_KEY_DIR.iterdir()):
        found = _inspect(path)
        if found:
            keys.append(found)
    return keys


def resolve_key(name):
    """Map a key name to its absolute path, or None if it is not on offer.

    Returning None rather than a path for anything unrecognised is what keeps
    "../../etc/passwd" and an absolute path alike from reaching the argv: the
    name has to match a key that list_keys() already found.
    """
    for key in list_keys():
        if key["name"] == name:
            return SSH_KEY_DIR / key["name"], key["encrypted"]
    return None, False
