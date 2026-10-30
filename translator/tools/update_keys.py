"""Inspect, enroll, or generate the owner-controlled Ed25519 update public key.

Only public keys are stored in the repository. Private keys must stay outside
the repository on an offline/owner-controlled path and are used with
``tools/sign_update.py`` to sign ``update-manifest.json``.

Examples::

    python tools/update_keys.py list
    python tools/update_keys.py generate --key-id release-2026 --private-key ~/.veyora/keys/release-2026.pem
    python tools/update_keys.py add --key-id release-2026 --public-key owner-public.pem
    python tools/update_keys.py remove --key-id release-2026
"""
import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import (  # noqa: E402
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_public_key,
)
import updater.core as _core
from updater.core import load_trusted_keys  # noqa: E402


def _read_public_key(path):
    data = Path(path).read_bytes()
    text = data.decode("ascii", "ignore").strip()
    if "BEGIN PUBLIC KEY" in text:
        key = load_pem_public_key(data)
        if not isinstance(key, Ed25519PublicKey):
            raise SystemExit("The supplied key is not an Ed25519 public key")
        return base64.b64encode(key.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    try:
        raw = base64.b64decode(text, validate=True)
    except ValueError as exc:
        raise SystemExit("Public key must be Ed25519 PEM or base64 raw bytes") from exc
    if len(raw) != 32:
        raise SystemExit("Ed25519 raw public keys are exactly 32 bytes")
    return base64.b64encode(raw).decode()


def _fingerprint(value):
    return hashlib.sha256(base64.b64decode(value)).hexdigest()[:16]


def _save(keys):
    target = Path(_core.TRUSTED_KEYS_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(keys, indent=2, sort_keys=True) + "\n", encoding="utf8")
    print(f"Wrote {target} ({len(keys)} key(s)). Rebuild the application to ship it.")


def _generate_keypair(key_id, private_key_path):
    priv_path = Path(private_key_path).expanduser().resolve()
    if priv_path.is_relative_to(REPO_ROOT):
        raise SystemExit("Refusing to write private signing key inside the Git repository. Choose a path outside the repo.")
    if priv_path.exists():
        raise SystemExit(f"Private key path already exists: {priv_path}")
    priv_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    pem_bytes = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    priv_path.write_bytes(pem_bytes)
    try:
        os.chmod(priv_path, 0o600)
    except OSError:
        pass
    pub_raw = base64.b64encode(private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    pub_pem_path = priv_path.with_suffix(".pub.pem")
    pub_pem_path.write_bytes(private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    keys = load_trusted_keys()
    keys[key_id] = pub_raw
    _save(keys)
    print(f"Private key saved OUTSIDE repo: {priv_path}")
    print(f"Public key enrolled: {key_id} (sha256:{_fingerprint(pub_raw)})")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list enrolled public key ids and fingerprints")
    gen = sub.add_parser("generate", help="generate an Ed25519 private key outside the repo and enroll its public key")
    gen.add_argument("--key-id", required=True)
    gen.add_argument("--private-key", required=True, help="Output path OUTSIDE the repository for the private PEM key")
    add = sub.add_parser("add", help="enroll a public key")
    add.add_argument("--key-id", required=True)
    add.add_argument("--public-key", required=True, help="Ed25519 PEM or base64 raw public key file")
    remove = sub.add_parser("remove", help="remove an enrolled key id")
    remove.add_argument("--key-id", required=True)
    args = parser.parse_args(argv)

    keys = load_trusted_keys()
    if args.command == "list":
        if not keys:
            print("No trusted update keys are enrolled. Production updates fail closed.")
            return 0
        for key_id, value in sorted(keys.items()):
            print(f"{key_id}: sha256:{_fingerprint(value)}")
        return 0
    if args.command == "generate":
        if not args.key_id.strip():
            raise SystemExit("key id cannot be empty")
        return _generate_keypair(args.key_id.strip(), args.private_key)
    if args.command == "add":
        if not args.key_id.strip():
            raise SystemExit("key id cannot be empty")
        keys[args.key_id.strip()] = _read_public_key(args.public_key)
        _save(keys)
        print(f"Enrolled {args.key_id.strip()} (sha256:{_fingerprint(keys[args.key_id.strip()])})")
        return 0
    keys.pop(args.key_id, None)
    _save(keys)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
