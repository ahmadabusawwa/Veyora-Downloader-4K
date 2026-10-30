"""Safe synthetic release tests: executable fixtures are inert bytes, never executed."""
import base64, hashlib, io, json
from unittest.mock import patch
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from updater import core

@pytest.fixture
def release():
    key=Ed25519PrivateKey.generate() # TEST ONLY; never installed into production trust store
    keys={'test':base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()}
    payload=b'INERT TEST DATA - NOT AN EXECUTABLE'
    m=dict(schema=1,repository=core.REPOSITORY,platform='windows-x64',version='2.1.0',expires=4102444800,filename='Veyora-Pro-Setup-2.1.0.exe',size=len(payload),sha256=hashlib.sha256(payload).hexdigest(),url=f'https://github.com/{core.REPOSITORY}/releases/download/v2.1.0/Veyora-Pro-Setup-2.1.0.exe')
    def sign(m):
        raw=json.dumps(m).encode();sig=json.dumps(dict(key_id='test',signature=base64.b64encode(key.sign(raw)).decode())).encode()
        return dict(raw=raw,signature=sig,tag='v2.1.0',notes='Test',manifest=m)
    return keys,payload,m,sign

@pytest.mark.parametrize('a,b',[('1.7.0','2.0.0'),('2.9.0','2.10.0'),('2.0.0rc1','2.0.0')])
def test_version_order(a,b):assert core.version(a)<core.version(b)

@pytest.mark.parametrize('value',['2','latest','2.0.0;rm','../../2.0.0',None])
def test_invalid_version(value):
    with pytest.raises(core.UpdateError):core.version(value)

def test_signature_tamper_unknown_and_expired(release):
    keys,payload,m,sign=release;r=sign(m)
    assert core.verify_manifest(r['raw'],r['signature'],keys,r['tag'])==m
    with pytest.raises(core.UpdateError):core.verify_manifest(r['raw']+b' ',r['signature'],keys,r['tag'])
    with pytest.raises(core.UpdateError):core.verify_manifest(r['raw'],r['signature'],{},r['tag'])
    m['expires']=1;r=sign(m)
    with pytest.raises(core.UpdateError):core.verify_manifest(r['raw'],r['signature'],keys,r['tag'])

@pytest.mark.parametrize('field,value',[('filename','../../evil.exe'),('url','https://evil.test/a.exe'),('repository','other/repo'),('platform','linux'),('size',-1),('sha256','xx'),('version','3.0.0')])
def test_signed_invalid_manifest(release,field,value):
    keys,_,m,sign=release;m[field]=value;r=sign(m)
    with pytest.raises(core.UpdateError):core.verify_manifest(r['raw'],r['signature'],keys,r['tag'])

@pytest.mark.parametrize('url',['http://github.com/x','https://github.com.evil.test/x','https://user@github.com/x','file:///a','https://github.com/other/repo/releases/download/v2/a.exe'])
def test_url_restriction(url):
    with pytest.raises(core.UpdateError):core.trusted_url(url)

def test_verified_download_and_tamper(release,tmp_path):
    keys,payload,m,sign=release;r=sign(m);client=core.UpdateClient('1.7.0',tmp_path,keys)
    progress=[]
    with patch.object(core,'open_url',return_value=io.BytesIO(payload)):
        path=client.download(r,progress.append)
    assert path.read_bytes()==payload and progress[-1]==1
    path.write_bytes(b'x'*len(payload))
    with pytest.raises(core.UpdateError):core.verify_file(path,m)

def test_cancel_and_truncated_download(release,tmp_path):
    keys,payload,m,sign=release;r=sign(m);client=core.UpdateClient('1.7.0',tmp_path,keys)
    for data,cancel in [(payload,lambda:True),(payload[:2],lambda:False),(payload+b'extra',lambda:False)]:
        with patch.object(core,'open_url',return_value=io.BytesIO(data)):
            with pytest.raises(core.UpdateError):client.download(r,cancelled=cancel)
    assert not list(tmp_path.rglob('*.exe')) and not list(tmp_path.rglob('*.part'))

def test_release_selection_prerelease_and_offline(release,tmp_path):
    keys,_,m,sign=release;r=sign(m)
    def item(tag,pre=False):return dict(tag_name=tag,prerelease=pre,draft=False,body='Changes',assets=[dict(name='update-manifest.json',browser_download_url=m['url'].rsplit('/',1)[0]+'/update-manifest.json'),dict(name='update-manifest.sig',browser_download_url=m['url'].rsplit('/',1)[0]+'/update-manifest.sig')])
    data=json.dumps([item('v9.0.0rc1',True),item('v2.1.0')]).encode()
    with patch.object(core,'read_bounded',side_effect=[data,r['raw'],r['signature']]):
        found=core.UpdateClient('1.7.0',tmp_path,keys).check()
    assert found['tag']=='v2.1.0'
    with patch.object(core,'read_bounded',side_effect=OSError('Offline')):
        with pytest.raises(OSError):core.UpdateClient('1.7.0',tmp_path,keys).check()

def test_no_update_on_same_or_older(tmp_path):
    with patch.object(core,'read_bounded',return_value=json.dumps([dict(tag_name='v1.7.0'),dict(tag_name='v2.0.0')]).encode()):
        assert core.UpdateClient('2.0.0',tmp_path).check() is None

def test_semver_prerelease_spelling():
    assert core.version('v2.1.0-beta.1') == core.version('2.1.0b1')
    assert core.version('2.1.0-beta.1') < core.version('2.1.0')

def test_redirect_cannot_leave_asset_hosts():
    import urllib.request
    redirect=core.SafeRedirect()
    req=urllib.request.Request(f'https://github.com/{core.REPOSITORY}/releases/download/v2/a.exe')
    with pytest.raises(core.UpdateError):redirect.redirect_request(req,None,302,'',{},'http://evil.test/a.exe')
