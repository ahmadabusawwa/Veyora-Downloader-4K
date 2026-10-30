"""Keep credentials and signed URL queries out of diagnostics."""
import re
from urllib.parse import urlsplit,urlunsplit

def redact(value):
    def clean(match):
        try:
            p=urlsplit(match.group())
            host=p.hostname or ''
            if p.port:host+=':'+str(p.port)
            return urlunsplit((p.scheme,host,p.path,'[redacted]' if p.query else '', ''))
        except ValueError:return '[redacted URL]'
    text=re.sub(r'https?://[^\s<>\"]+',clean,str(value))
    return re.sub(r'(?i)(authorization|cookie|password|token)\s*[:=]\s*[^\s,;]+',r'\1=[redacted]',text)

class QuietLogger:
    def debug(self,message):pass
    def warning(self,message):pass
    def error(self,message):pass
