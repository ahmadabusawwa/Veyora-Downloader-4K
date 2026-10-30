"""Explicit, bounded CPU/network budgets. Default preserves 1.7 behavior."""
import json
import os
from pathlib import Path
PROFILES={'economy':(2,1,1),'balanced':(4,3,2),'high':(8,5,4)}
def profile():
    name=os.environ.get('VEYORA_PERFORMANCE')
    if name is None:
        try:
            root=Path(os.environ.get('VEYORA_CONFIG_DIR',str(Path.home()/'.veyora')))
            name=json.loads((root/'settings.json').read_text(encoding='utf8')).get('performance_mode','balanced')
        except (OSError,ValueError,AttributeError):name='balanced'
    return PROFILES.get(name,PROFILES['balanced'])
def cpu_threads():return min(profile()[0],max(1,os.cpu_count() or 1))
