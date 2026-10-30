"""Run offline with an OWNER-supplied Ed25519 PEM key. Never generates a production key."""
import argparse, base64, hashlib, json, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
p=argparse.ArgumentParser()
p.add_argument('installer', type=Path)
p.add_argument('--key', type=Path, required=True)
p.add_argument('--key-id', required=True)
p.add_argument('--tag', required=True)
p.add_argument('--expires-days', type=int, default=30)
a=p.parse_args()
from updater.core import REPOSITORY, version
v=str(version(a.tag))
assert a.installer.name == f'Veyora-Pro-Setup-{v}.exe'
key=load_pem_private_key(a.key.read_bytes(), password=None)
if not isinstance(key, Ed25519PrivateKey): raise ValueError('Ed25519 key required')
m=dict(schema=1,repository=REPOSITORY,platform='windows-x64',version=v,expires=int(time.time()+a.expires_days*86400),filename=a.installer.name,size=a.installer.stat().st_size,sha256=hashlib.file_digest(a.installer.open('rb'),'sha256').hexdigest(),url=f'https://github.com/{REPOSITORY}/releases/download/{a.tag}/{a.installer.name}')
raw=json.dumps(m,sort_keys=True,separators=(',',':')).encode()
a.installer.with_name('update-manifest.json').write_bytes(raw)
a.installer.with_name('update-manifest.sig').write_text(json.dumps(dict(key_id=a.key_id,signature=base64.b64encode(key.sign(raw)).decode())),encoding='utf8')
