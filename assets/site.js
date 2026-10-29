(function () {
  'use strict';
  const api = window.VeyoraRelease;
  const notice = document.getElementById('release-notice');
  if (api && typeof fetch === 'function') {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    fetch(`https://api.github.com/repos/${api.REPO}/releases/latest`, {
      signal: controller.signal, credentials: 'omit', headers: { Accept: 'application/vnd.github+json' }
    }).then(response => {
      if (!response.ok) throw new Error('Release metadata unavailable');
      return response.json();
    }).then(data => {
      const release = api.pickRelease(data);
      if (!release) throw new Error('No matching Windows package');
      document.querySelectorAll('[data-download]').forEach(link => { link.href = release.url; });
      document.getElementById('release-link').href = release.releaseUrl;
      document.getElementById('release-status').textContent =
        `الإصدار ${release.version} · الحجم ${api.formatSize(release.size)} · ${release.format} / x64`;
      const checksum = document.getElementById('checksum');
      checksum.closest('details').hidden = !release.digest;
      if (release.digest) checksum.textContent = release.digest;
      notice.textContent = 'تم تحديث معلومات الحزمة من GitHub Releases.';
    }).catch(() => {
      // The pinned, verified release link in HTML remains usable without the API or JavaScript.
      notice.textContent = 'تعذّر تحديث معلومات أحدث إصدار. رابط الإصدار 1.5.0 المباشر ما زال متاحًا؛ يمكنك مراجعة كل الإصدارات.';
    }).finally(() => clearTimeout(timer));
  }
  document.getElementById('copy-checksum').addEventListener('click', async () => {
    const status = document.getElementById('copy-status');
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(document.getElementById('checksum').textContent.trim());
      status.textContent = 'تم نسخ البصمة';
    } catch (_) {
      status.textContent = 'تعذّر النسخ التلقائي. حدّد البصمة وانسخها يدويًا.';
    }
  });
}());
