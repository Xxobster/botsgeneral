"""Generate OpenSSH Ed25519 keys + native PuTTY PPK3 for named VPS hosts.

PPK files are created by importing the OpenSSH key into PuTTYgen (GUI) so the
private blob/MAC match PuTTY 0.83 exactly. Falls back to writing OpenSSH only
if GUI conversion fails.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

SSH_DIR = Path.home() / ".ssh"
HOSTS = {
    "ln1": "ln1@94.156.189.76",
    "ln2": "ln2@212.73.150.178",
    "ln3": "ln3@185.203.119.52",
    "sm": "sm@212.73.150.149",
}


def ensure_openssh(name: str, comment: str) -> Path:
    priv = SSH_DIR / name
    pub = SSH_DIR / f"{name}.pub"
    if priv.exists() and pub.exists():
        print(f"openssh exists {name}")
        return priv

    key = Ed25519PrivateKey.generate()
    priv.write_bytes(
        key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    )
    pub_line = key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    alg, blob, *_ = pub_line.split()
    pub.write_text(f"{alg} {blob} {comment}\n", encoding="ascii")
    print(f"generated openssh {name}")
    return priv


def main() -> int:
    SSH_DIR.mkdir(parents=True, exist_ok=True)
    for name, comment in HOSTS.items():
        ensure_openssh(name, comment)

    gui = Path(__file__).with_name("_openssh_to_ppk_gui.py")
    print("Converting to native PuTTY PPK3 via PuTTYgen GUI...")
    rc = subprocess.call([sys.executable, str(gui)])
    if rc != 0:
        print("GUI conversion failed; OpenSSH keys are ready under ~/.ssh/{ln1,ln2,ln3,sm}")
        return rc
    for name in HOSTS:
        ppk = SSH_DIR / f"{name}.ppk"
        print(f"  {ppk} ({ppk.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
