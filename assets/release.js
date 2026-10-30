(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.VeyoraRelease = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const REPO = 'ahmadabusawwa/Veyora-Downloader-4K';
  function pickRelease(release) {
    if (!release || release.draft || release.prerelease || !Array.isArray(release.assets)) return null;
    const tag = release.tag_name;
    if (typeof tag !== 'string' || !/^v?\d+\.\d+\.\d+$/.test(tag)) return null;
    const version = tag.replace(/^v/, '');
    // Prefer the explicitly named Windows EXE; retain ZIP for portable-only releases.
    for (const name of [`Veyora-Pro-Setup-${version}.exe`, `Veyora-Pro-${version}-Windows-x64.exe`, `Veyora-Pro-${version}-Windows-x64.zip`]) {
      const extension = name.split('.').pop();
      const expectedPath = `/${REPO}/releases/download/${encodeURIComponent(tag)}/${name}`;
      const asset = release.assets.find(candidate => {
        if (!candidate || candidate.name !== name || candidate.state !== 'uploaded' ||
            !Number.isSafeInteger(candidate.size) || candidate.size <= 0) return false;
        try {
          const url = new URL(candidate.browser_download_url);
          return url.origin === 'https://github.com' && url.pathname === expectedPath &&
            !url.username && !url.password && !url.search && !url.hash;
        } catch (_) { return false; }
      });
      if (!asset) continue;
      const digest = typeof asset.digest === 'string' && /^sha256:[a-f0-9]{64}$/i.test(asset.digest)
        ? asset.digest.slice(7).toLowerCase() : null;
      return { version, name, size: asset.size, url: asset.browser_download_url, digest,
        format: extension.toUpperCase(),
        releaseUrl: `https://github.com/${REPO}/releases/tag/${encodeURIComponent(tag)}` };
    }
    return null;
  }

  function formatSize(bytes) {
    return `${(bytes / 1048576).toFixed(1)} MiB`;
  }
  return Object.freeze({ REPO, pickRelease, formatSize });
}));
