"""Verify exact deliverables and produce a non-self-referential SHA256 manifest."""
import hashlib,json,subprocess,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];dist=root/'dist'
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
files=[]
for name in ('Veyora-Pro-2.0.3-Full-Source.zip','Veyora-Pro-2.0.3-Windows-Portable.zip','Veyora-Pro-2.0.3-Setup.exe','Veyora-Pro-2.0.3-Test-Report.md'):
 path=dist/name
 with path.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
 record=dict(name=name,size=path.stat().st_size,sha256=digest)
 if path.suffix=='.zip':
  with zipfile.ZipFile(path) as archive:
   assert archive.testzip() is None,name+' failed CRC'
   record['zip_crc_ok']=True
   if 'Full-Source' in name:assert archive.comment.decode()==sha;record['source_commit_matches']=True
 files.append(record)
(dist/'Veyora-Pro-2.0.3-File-Verification.json').write_text(json.dumps(dict(version='2.0.3',build_commit=sha,files=files),indent=2),encoding='utf8')
print('Verified source commit, archive CRCs and all four SHA256 digests')
