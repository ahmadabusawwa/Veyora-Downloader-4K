"""Worker-safe progress delivery and user-facing errors; no Tk calls here."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading


class LatestProgress:
    """At most one queued callback, regardless of the producer's event rate."""
    def __init__(self, callbacks, render):
        self.callbacks, self.render = callbacks, render
        self.lock = threading.Lock()
        self.pending = False
        self.latest = None

    def __call__(self, *values):
        with self.lock:
            self.latest = values
            if self.pending:
                return
            self.pending = True
        self.callbacks.put(self._deliver)

    def _deliver(self):
        with self.lock:
            values = self.latest
            self.pending = False
        self.render(*values)


class _PrivateFormatter(logging.Formatter):
    def format(self, record):
        from privacy import redact
        return redact(super().format(record))


_log_lock = threading.Lock()


def log_failure(exc, context='processing'):
    logger = logging.getLogger('veyora.errors')
    with _log_lock:
        if not logger.handlers:
            root = Path(os.environ.get('VEYORA_CONFIG_DIR', str(Path.home() / '.veyora')))
            try:
                (root / 'logs').mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(root / 'logs' / 'errors.log', maxBytes=2_000_000,
                                             backupCount=3, encoding='utf-8')
            except OSError:
                handler = logging.StreamHandler()
            handler.setFormatter(_PrivateFormatter('%(asctime)s %(levelname)s %(message)s'))
            logger.addHandler(handler)
            logger.setLevel(logging.ERROR)
            logger.propagate = False
    logger.error('%s failed', context, exc_info=(type(exc), exc, exc.__traceback__))


def friendly_error(exc, arabic=False, cancelled=False, record=True):
    """Keep diagnostics in logs; never display an arbitrary exception string."""
    if cancelled:
        return 'تم إلغاء المهمة.' if arabic else 'Task cancelled.'
    if record:
        log_failure(exc)
    text = str(exc).lower()
    if any(x in text for x in ('connect', 'getaddrinfo', 'network', 'timed out', 'timeout',
                               'internet', 'download translation model', 'offline')):
        return ('تعذر الاتصال. تحقق من الإنترنت، وجهّز النماذج المطلوبة مرة واحدة ثم أعد المحاولة.'
                if arabic else 'Connection failed. Check your internet and prepare the required models once, then retry.')
    if '429' in text or 'rate limit' in text:
        return 'الموقع يقيّد الطلبات مؤقتًا. حاول لاحقًا.' if arabic else 'The website is limiting requests. Try again later.'
    if any(x in text for x in ('login', 'sign in', 'cookies', 'private video')):
        return 'هذا المحتوى يحتاج تسجيل الدخول أو صلاحية الوصول.' if arabic else 'This content requires sign-in or access permission.'
    if 'drm' in text:
        return 'لا يمكن تنزيل المحتوى المحمي بـDRM.' if arabic else 'DRM-protected content cannot be downloaded.'
    if isinstance(exc, PermissionError):
        return 'لا توجد صلاحية لحفظ الملف. اختر مجلدًا آخر.' if arabic else 'Cannot save here. Choose another output folder.'
    if 'model' in text:
        return ('نموذج الذكاء الاصطناعي ناقص أو تعذر تحميله. أعد تجهيزه من إعدادات النماذج.'
                if arabic else 'An AI model is missing or could not load. Prepare it again in model settings.')
    if 'ffmpeg' in text or 'ffprobe' in text:
        return 'تعذرت معالجة الوسائط. تحقق من FFmpeg والملف المحدد.' if arabic else 'Media processing failed. Check FFmpeg and the selected file.'
    if 'no ' in text and 'speech' in text:
        return 'لم يتم اكتشاف كلام في الملف. تحقق من لغة المصدر والصوت.' if arabic else 'No speech detected. Check the source language and audio.'
    return ('لم تكتمل المهمة. راجع سجل الأخطاء للتفاصيل.' if arabic
            else 'The task failed. See the error log for details.')
