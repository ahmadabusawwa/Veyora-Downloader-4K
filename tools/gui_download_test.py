"""Exercise the actual Download button with a generated local video and HTTP server."""
import functools,http.server,json,os,sys,tempfile,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
root=Path(tempfile.mkdtemp(prefix='veyora-gui-download-'))
os.environ['VEYORA_CONFIG_DIR']=str(root/'config')
import main
main.DEFAULT_SETTINGS.update(auto_update_check=False,download_subs=False,save_thumbnail=False,download_dir=str(root/'downloads'))
from translator.video_renderer import run_ffmpeg
run_ffmpeg(['-f','lavfi','-i','color=c=0x0088ff:s=320x180:d=1','-c:v','libx264','-pix_fmt','yuv420p',root/'local-test.mp4'])
class Quiet(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*a):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root)))
threading.Thread(target=server.serve_forever,daemon=True).start()
from desktop_ui import DesktopApp
from PIL import ImageGrab
app=DesktopApp();started=time.monotonic();outcome=[]
def start():
 app.smart_mode=True;app.sub_var.set(False);app.thumb_var.set(False)
 app.url_entry.insert(0,f'http://127.0.0.1:{server.server_port}/local-test.mp4')
 app.start_download_action();app.after(100,poll)
def poll():
 tasks=app.queue_manager.get_tasks_by_status()
 if tasks and tasks[0]['status'] in app.queue_manager.TERMINAL:
  task=tasks[0];outcome.append(task['status'])
  app.show_tab('Dashboard');app.update()
  x,y=app.winfo_rootx(),app.winfo_rooty()
  ImageGrab.grab().crop((x,y,x+app.winfo_width(),y+app.winfo_height())).save('gui-download-actual.png')
  Path('gui-download-result.json').write_text(json.dumps(dict(status=task['status'],source='FFmpeg-generated local video over HTTP',downloaded_file_exists=Path(task.get('downloaded_file','')).is_file(),error=task.get('error')),indent=2))
  app._on_close()
 elif time.monotonic()-started>30:
  outcome.append('Timeout');app._on_close()
 else:app.after(100,poll)
app.after(400,start)
try:app.mainloop()
finally:server.shutdown();server.server_close()
assert outcome==['Completed'],outcome
print('Real GUI download button: Completed')
