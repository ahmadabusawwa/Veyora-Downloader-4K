"""Repeatable synthetic queue snapshot benchmark; no network or media-quality claim."""
import argparse,json,sys,threading,time,tracemalloc,resource
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
sys.path.insert(0,str(Path(a.source).resolve()))
import main
manager=main.DownloadQueueManager(lambda:None,1)
manager._process_queue=lambda:None
tracemalloc.start();begin=time.perf_counter()
for i in range(300):manager.add_task('https://example.com/test.mp4',dict(main.DEFAULT_SETTINGS),title='Test '+str(i))
for i in range(100):manager.get_tasks_by_status()
elapsed=time.perf_counter()-begin
current,peak=tracemalloc.get_traced_memory()
manager.shutdown()
Path(a.output).write_text(json.dumps(dict(tasks=300,snapshots=100,seconds=elapsed,python_heap_peak_bytes=peak,rss_max_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,scope='Synthetic queue only; single Linux run, not a Windows or inference benchmark'),indent=2))
