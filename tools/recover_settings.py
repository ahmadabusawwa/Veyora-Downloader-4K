"""Recover a backup into a NEW directory; never overwrite current user data."""
import argparse,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('backup',type=Path);p.add_argument('destination',type=Path);a=p.parse_args()
if not a.backup.is_dir():raise ValueError('Backup directory does not exist')
a.destination.mkdir(parents=True,exist_ok=False)
for name in ('settings.json','history.json','config.json'):
 if (a.backup/name).is_file():shutil.copy2(a.backup/name,a.destination/name)
print('Recovered settings copy:',a.destination)
