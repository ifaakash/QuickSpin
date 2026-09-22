"""Discover the SSH private keys the API is allowed to hand to ansible.

Everything else that reaches the ansible-playbook argv in this service is
checked against an allowlist first — ALLOWED_USERS for the remote user, the
parsed inventory for group and host. A private key is no different: the
directories are fixed by config, the keys in them are discovered by reading
them, and a request may only name a key that is already there.

Several directories are searched, in order, so a laptop's ~/.ssh and a mounted
Secret can both feed the same dropdown. Keys are identified to the API by their
absolute path rather than their bare filename, because two mounts can easily
hold a key of the same name and silently shadowing one of them would be worse
than making the caller say which it means.
"""

import base64
import struct

from .config import SSH_KEY_DIRS

# Private keys are identified by reading them, not by their filename. Keys get
# named anything (id_ed25519, homelab, deploy_key), while known_hosts, config
# and *.pub all sit in the same directories and must never be offered.
PEM_START = "-----BEGIN "
PEM_PRIVATE = "PRIVATE KEY"

# Keys are a few KB at most. Cap the read so a stray large file in a mounted
# directory cannot be slurped into memory just to answer a dropdown.
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
    """Return a key entry for a private key file, or None if it is not one."""
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

    return {
        "name": path.name,
        "path": str(path),
        "directory": str(path.parent),
        "encrypted": encrypted,
    }


def list_keys():
    """Every usable private key across SSH_KEY_DIRS, in directory order.

    The directories are re-read on each call rather than cached, for the same
    reason the inventory is re-read on each request: a key added, removed or
    remounted must show up without restarting the service. That matters more
    here than for the inventory, since a Secret can be rotated under a running
    pod.

    A directory that does not exist is skipped, not an error. One list of
    candidate locations is meant to cover a laptop and a pod alike, so most of
    the entries are expected to be absent in any given environment.
    """
    keys = []
    seen = set()
    for directory in SSH_KEY_DIRS:
        try:
            if not directory.is_dir():
                continue
            entries = sorted(directory.iterdir())
        except OSError:
            continue

        for path in entries:
            found = _inspect(path)
            # The same directory can be named twice in the env var, or reached
            # through a symlink; list each real key once.
            if found and found["path"] not in seen:
                seen.add(found["path"])
                keys.append(found)
    return keys


def list_directories():
    """The configured search paths, with whether each is actually present."""
    return [
        {"path": str(directory), "exists": directory.is_dir()}
        for directory in SSH_KEY_DIRS
    ]


def resolve_key(identifier):
    """Map a key identifier to its path, or (None, False) if it is not on offer.

    The identifier is normally the absolute path from GET /api/ssh-keys. A bare
    filename is also accepted and resolves to the first match in directory
    order, which keeps short names working for the common case of one key
    directory.

    Either way the value is matched against keys that list_keys() already
    found, never joined onto a directory. That is what keeps "../id_rsa" and
    "/etc/shadow" out of the argv: they are not rejected by a pattern that has
    to anticipate them, they simply are not in the set of keys that exist.
    """
    if not identifier:
        return None, False

    candidates = list_keys()

    for key in candidates:
        if key["path"] == identifier:
            return key["path"], key["encrypted"]

    for key in candidates:
        if key["name"] == identifier:
            return key["path"], key["encrypted"]

    return None, False
