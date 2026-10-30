const test = require('node:test');
const assert = require('node:assert/strict');
const { pickRelease, formatSize, REPO } = require('../assets/release.js');
const hash = 'cd23cacfc15744ebf99ef92d472dde7ad08d300a915369d82481f044c713b1a9';
function fixture(tag = '1.5.0') {
  const version = tag.replace(/^v/, '');
  return { tag_name: tag, draft: false, prerelease: false, assets: [
    { name: 'Source-code.zip', size: 2000, state: 'uploaded', browser_download_url: 'https://example.com/source.zip' },
    { name: `Veyora-Pro-${version}-Windows-x64.zip`, size: 302331801, state: 'uploaded',
      browser_download_url: `https://github.com/${REPO}/releases/download/${tag}/Veyora-Pro-${version}-Windows-x64.zip`, digest: `sha256:${hash}` }
  ] };
}
test('selects the exact Windows runtime package rather than the first/source asset', () => {
  const result = pickRelease(fixture());
  assert.equal(result.name, 'Veyora-Pro-1.5.0-Windows-x64.zip');
  assert.equal(result.digest, hash);
  assert.equal(formatSize(result.size), '288.3 MiB');
});
test('supports both numbered and v-prefixed release tags', () => {
  assert.equal(pickRelease(fixture('v1.6.0')).version, '1.6.0');
});
test('does not silently select an EXE or a source zip when the runtime package is missing', () => {
  const data = fixture(); data.assets.pop();
  data.assets.push({ name: 'Veyora_Pro.exe', size: 10, state: 'uploaded', browser_download_url: 'https://github.com/test.exe' });
  assert.equal(pickRelease(data), null);
});
test('rejects draft/prerelease/incomplete upload and mismatched versions', () => {
  for (const property of ['draft', 'prerelease']) { const data = fixture(); data[property] = true; assert.equal(pickRelease(data), null); }
  const data = fixture(); data.assets[1].state = 'new'; assert.equal(pickRelease(data), null);
  const mismatch = fixture(); mismatch.assets[1].name = 'Veyora-Pro-1.4.0-Windows-x64.zip'; assert.equal(pickRelease(mismatch), null);
});
test('rejects downloads outside the expected repository and credentials/query redirects', () => {
  for (const url of ['https://evil.example/download.zip', `https://github.com/other/repo/releases/download/1.5.0/Veyora-Pro-1.5.0-Windows-x64.zip`,
    `https://user:password@github.com/${REPO}/releases/download/1.5.0/Veyora-Pro-1.5.0-Windows-x64.zip`,
    `https://github.com/${REPO}/releases/download/1.5.0/Veyora-Pro-1.5.0-Windows-x64.zip?redirect=evil`]) {
    const data = fixture(); data.assets[1].browser_download_url = url; assert.equal(pickRelease(data), null);
  }
});
test('unknown digests are hidden rather than retaining the checksum for an older asset', () => {
  const data = fixture(); data.assets[1].digest = 'not-a-sha256'; assert.equal(pickRelease(data).digest, null);
});
test('malformed API payloads do not throw or fabricate a release', () => {
  for (const value of [null, {}, [], { tag_name: '<script>', assets: [] }, { tag_name: '1.5.0', assets: [null] }]) assert.equal(pickRelease(value), null);
});

test('prefers the correctly named EXE even when ZIP is listed first', () => {
  const data = fixture();
  data.assets.push({name:'Veyora-Pro-1.5.0-Windows-x64.exe',size:235247060,state:'uploaded',
    browser_download_url:`https://github.com/${REPO}/releases/download/1.5.0/Veyora-Pro-1.5.0-Windows-x64.exe`,
    digest:'sha256:190a0a124a71432b6a2c03b614e412825be9dbe72f2ec7eef7526e1656d9ca07'});
  const selected=pickRelease(data);
  assert.equal(selected.format,'EXE');
  assert.equal(formatSize(selected.size),'224.3 MiB');
  assert.ok(selected.url.endsWith('.exe'));
});
test('falls back to the matching ZIP when the EXE URL is invalid', () => {
  const data=fixture();
  data.assets.push({name:'Veyora-Pro-1.5.0-Windows-x64.exe',size:235247060,state:'uploaded',browser_download_url:'https://evil.example/app.exe'});
  assert.equal(pickRelease(data).format,'ZIP');
});

test('prefers the new per-user Setup package', () => {
  const data=fixture('v2.0.0');
  data.assets.push({name:'Veyora-Pro-Setup-2.0.0.exe',size:1000,state:'uploaded',browser_download_url:`https://github.com/${REPO}/releases/download/v2.0.0/Veyora-Pro-Setup-2.0.0.exe`});
  assert.equal(pickRelease(data).name,'Veyora-Pro-Setup-2.0.0.exe');
});
