"""Synthetic speech fixtures + actual Whisper recognition + all 12 text translations.
Requires espeak-ng locally. This is an integration test, not human speech accuracy validation.
"""
import json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from translator.transcription import Transcriber,release_speech_model
from translator.translation_provider import TranslatorProvider,release_translation_models
SAMPLES={'en':'Hello. Today the weather is beautiful.','ar':'مرحبا. الطقس جميل اليوم.','tr':'Merhaba. Bugün hava güzel.','ko':'안녕하세요. 오늘 날씨가 좋습니다.'}
root=Path('tests/fixtures/synthetic-speech');root.mkdir(parents=True,exist_ok=True)
report={'scope':'Actual recognition and translation of espeak-ng synthetic speech; not representative human audio or a quality certification','sources':[]}
for source,text in SAMPLES.items():
 item={'source':source,'expected_text':text};start=time.monotonic()
 try:
  audio=root/(source+'.wav')
  subprocess.run(['espeak-ng','-v',source,'-s','135','-w',str(audio),text],check=True,capture_output=True,timeout=30)
  segments,info=Transcriber(model_size='base',language=source).transcribe(str(audio))
  transcript=' '.join(x.text.strip() for x in segments)
  item.update(transcript=transcript,segments=len(segments),recognized_language=info.language,translations=[])
  if not transcript:raise ValueError('No speech recognized')
  for target in SAMPLES:
   if source==target:continue
   provider=TranslatorProvider(source,target);provider.prepare()
   translated=provider.translate(transcript)
   item['translations'].append({'target':target,'output':translated})
   release_translation_models()
  item['status']='completed'
 except Exception as exc:item.update(status='failed',error=type(exc).__name__+': '+str(exc))
 item['seconds']=time.monotonic()-start;report['sources'].append(item)
 Path('speech-matrix-2.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print(source,item['status'],flush=True)
release_speech_model()
