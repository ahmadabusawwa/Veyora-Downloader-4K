"""Sign or verify an installer release manifest using an owner-supplied Ed25519 key."""
import argparse
import base64
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import load_pem_private_key  # noqa: E402
from updater.core import REPOSITORY, load_trusted_keys, verify_file, verify_manifest, version  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("installer", type=Path, help="Path to Veyora-Pro-Setup-<version>.exe")
    p.add_argument("--key", type=Path, help="Path to offline Ed25519 private PEM key (required for signing)")
    p.add_argument("--key-id", help="Key ID matching trusted_keys.json (required for signing)")
    p.add_argument("--tag", required=True, help="Release tag, e.g. v2.0.0")
    p.add_argument("--expires-days", type=int, default=30)
    p.add_argument("--verify", action="store_true", help="Verify existing manifest and signature against trusted_keys.json")
    a = p.parse_args(argv)

    v = str(version(a.tag))
    if a.installer.name != f"Veyora-Pro-Setup-{v}.exe":
        raise ValueError(f"Expected installer named Veyora-Pro-Setup-{v}.exe")

    manifest_path = a.installer.with_name("update-manifest.json")
    sig_path = a.installer.with_name("update-manifest.sig")

    if a.verify:
        keys = load_trusted_keys()
        m = verify_manifest(manifest_path.read_bytes(), sig_path.read_bytes(), keys, a.tag)
        verify_file(a.installer, m)
        print(f"Verified {a.installer.name} against enrolled key ({json.loads(sig_path.read_text(encoding='utf8'))['key_id']})")
        return 0

    if not a.key or not a.key_id:
        raise SystemExit("--key and --key-id are required when signing")
    key = load_pem_private_key(a.key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Ed25519 key required")
    m = dict(
        schema=1,
        repository=REPOSITORY,
        platform="windows-x64",
        version=v,
        expires=int(time.time() + a.expires_days * 86400),
        filename=a.installer.name,
        size=a.installer.stat().st_size,
        sha256=hashlib.file_digest(a.installer.open("rb"), "sha256").hexdigest(),
        url=f"https://github.com/{REPOSITORY}/releases/download/{a.tag}/{a.installer.name}",
    )
    raw = json.dumps(m, sort_keys=True, separators=(",", ":")).encode()
    manifest_path.write_bytes(raw)
    sig_path.write_text(
        json.dumps(dict(key_id=a.key_id, signature=base64.b64encode(key.sign(raw)).decode())),
        encoding="utf8",
    )
    keys = load_trusted_keys()
    if a.key_id in keys:
        verify_manifest(raw, sig_path.read_bytes(), keys, a.tag)
        verify_file(a.installer, m)
    print(f"Signed {manifest_path.name} and {sig_path.name} for {a.installer.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
