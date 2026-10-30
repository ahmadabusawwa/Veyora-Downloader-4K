"""Real text model inference for all 12 pairs; output is evidence, not a quality score."""
import sys,json,time,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from translator.translation_provider import TranslatorProvider,release_translation_models
SAMPLES={'en':'Hello. Today the weather is beautiful.','ar':'مرحبا. الطقس جميل اليوم.','tr':'Merhaba. Bugün hava güzel.','ko':'안녕하세요. 오늘 날씨가 좋습니다.'}
results=[]
for source,text in SAMPLES.items():
 for target in SAMPLES:
  if source==target:continue
  start=time.monotonic();item=dict(source=source,target=target,input=text)
  try:
   provider=TranslatorProvider(source,target);provider.prepare();value=provider.translate(text)
   if not value.strip():raise ValueError('Empty translation')
   item.update(status='inference_completed',output=value)
  except Exception as exc:item.update(status='failed',error=str(exc))
  finally:release_translation_models()
  item['seconds']=time.monotonic()-start;results.append(item)
  print(source,'->',target,item['status'],flush=True)
  Path('inference-matrix-2.json').write_text(json.dumps(dict(scope='Real text inference; no speech recognition or human accuracy evaluation',results=results),ensure_ascii=False,indent=2),encoding='utf8')
