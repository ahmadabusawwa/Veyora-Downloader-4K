"""Arabic reports derived from current-run evidence; critical missing media stays BLOCKED."""
from pathlib import Path
import json,subprocess,xml.etree.ElementTree as ET
from audit_inventory import inventory
root=Path(__file__).resolve().parents[1];out=root/'dist';out.mkdir(exist_ok=True)
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
def read(path):
 try:return json.loads((root/path).read_text(encoding='utf-8-sig'))
 except (OSError,ValueError):return None
paths={'navigation':'navigation-results.json','final_ui':'final-ui/final-ui-results.json','recovery':'recovery/recovery-results.json','video':'real-video-results.json','quality':'quality/media-quality-results.json','close_idle':'close-idle/close-results.json','close_download':'close-download/close-results.json','close_translation':'close-translation/close-results.json','regression_installed':'regression-installed/regression-results.json','regression_portable':'regression-portable/regression-results.json'}
for stage in ('first','restart','disabled','empty'):paths['session_'+stage]='features/gui-features-'+stage+'.json'
records={name:read('real-video-review/'+path) for name,path in paths.items()}
lifecycle=read('dist/confirmation-lifecycle-results.json')
if lifecycle:records['confirmation_lifecycle']=dict(ok=all(r['exit']==0 and r['result']==dict(round=10,callbacks=10) for r in lifecycle if r['mode']=='after'),trials=lifecycle)
unit=None
try:
 xml=ET.parse(root/'windows-tests.xml').getroot();suites=[xml] if xml.tag=='testsuite' else list(xml)
 unit={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')};unit['passed']=unit['tests']-unit['failures']-unit['errors']-unit['skipped']
except (OSError,ET.ParseError):pass
passed=lambda name:bool(records.get(name) and records[name].get('ok'))
reg=records.get('regression_installed') or {};quality=records.get('quality') or {};video=records.get('video') or {}
issues=[
(1,'توقف الترجمة قرب 02:21','السبب غير متحقق؛ الفيديو وSRT المطابق غير متوفرين','pipeline، subtitle_generator','حواجز فقد المقاطع وتنبيه تغطية لا يثبت إصلاح الأغنية','اختبار الحالة الأصلية غير منفذ','BLOCKED'),
(2,'فقد الكلام مع الموسيقى','محددات ASR والمزج تحتاج عينة بشرية مرجعية','automatic_audio، pipeline، media_validation','مقارنة أصل/مرشح محافظة مع رجوع للأصل؛ لا تبديل VAD أو النموذج','عينات SAPI وموسيقى ومؤثرات فقط','PARTIALLY FIXED'),
(3,'تراجع جودة العربية','HTML وخرج فارغ مؤكدان؛ الدلالة وأسماء الألعاب غير محلولة عمومًا','translation_provider، recognition_policy','فك HTML ورفض الخرج الفارغ وسياق تلقائي','نتائج فعلية قابلة للمراجعة في quality JSON؛ لا درجة جودة مخترعة','PARTIALLY FIXED'),
(4,'تحسين الحوار تلقائي','auto السابق لا ينفذ مقارنة معالجة','automatic_audio، pipeline، desktop_ui','سياسة تلقائية مشتركة، حفظ القيم القديمة وإزالة التحكم اليدوي من UI','اختبارات منطق + مقارنة صوت فعلية؛ فائدة الغناء غير متحققة','PARTIALLY FIXED'),
(5,'السياق تلقائي','إعدادات قديمة قد توقفه وتختلف بين المدخلين','recognition_policy، desktop_ui، main','توحيد السياسة التلقائية وتجميع الجمل بحدود زمنية','Native shared engine' if passed('regression_installed') else 'Windows NOT TESTED','FIXED' if passed('regression_installed') else 'NOT TESTED'),
(6,'اتجاه العربية والنص المختلط','مزج نص Canvas مشكّل مع Label/Menu أصليين','ui_controls، ui_text','فصل النص المنطقي الأصلي عن تشكيل Canvas، وتعريب مراحل جديدة','لقطات Windows للمنتقى والقائمة؛ لا فحص لكل نص مختلط','PARTIALLY FIXED'),
(7,'أزرار النتائج المحلية','لم توجد إجراءات نتائج في الصفحة المحلية','desktop_ui، output_actions','SRT ومجلده والأصل أو الناتج الصحيح؛ انتظار اكتمال المهمة ومعالجة المحذوف','نتائج regression-installed/portable','FIXED' if passed('regression_installed') and str(reg.get('open_video','')).startswith('PASS') else 'PARTIALLY FIXED'),
(8,'SRT ناقص/غير صالح يُقبل','الكاتب يسمح بخرج فارغ أو زمن صفري؛ decode فارغ','subtitle_generator، translation_provider، pipeline','كتابة ذرية، تحقق العدد والنص والتوقيت والترتيب والترميز؛ تنبيه تغطية مستقل','اختبارات إخفاق تحافظ على الملف السابق، SRT حقيقي وMP4','FIXED' if passed('regression_installed') else 'PARTIALLY FIXED'),
(9,'اختلاط الصوت والفيديو','قائمة عليا تعرض MP3/WAV بجوار خيارات فيديو','conversion_page، media_conversion، local_tasks','قائمة فيديو مستقلة واستخراج صوت مستقل لا يغير وضع الفيديو','FFmpeg فعلي؛ GUI four formats في final_ui','FIXED' if passed('final_ui') else 'NOT TESTED'),
(10,'زر قصّ المقطع لا ينفذ','عامل التنزيل لا يقرأ clip_enabled','media_clipping، main','قص دقيق بعد تنزيل كامل، حفظ الأصل وفحص الزمن، ترجمة المقطع','HTTP/yt-dlp/FFmpeg فعلي؛ clip+translation في Windows','FIXED' if reg.get('actual_download_clip_translation') else 'PARTIALLY FIXED'),
(11,'اختلاف محركَي الترجمة','سياسات إعدادات منفصلة','recognition_policy، main، desktop_ui','دالة إعداد واحدة ومحرك واحد ومفتاح التنزيل باقٍ','مقارنة SRT المحلي والتنزيل على الملف نفسه','FIXED' if reg.get('shared_local_download_engine') else 'NOT TESTED'),
(12,'عدم التحقق من كل اللغات','الاختبارات الإنجليزية لا تثبت ASR متعدد اللغات','اختبارات اللغات والتقرير','جرد فعلي لأربع لغات وبيان المسارات المحورية، نتائج نصية منفصلة','ASR عربي/تركي/كوري غير منفذ في هذه الجولة','PARTIALLY FIXED'),
(13,'معلومات قديمة مع رابط فارغ','بيانات تجريبية ثابتة ونتائج تحليل متأخرة بلا هوية رابط','desktop_ui','حالة فارغة وربط المعاينة والصورة بمراجعة الرابط؛ حفظ السجل','عمليات إعادة تشغيل first/restart/disabled/empty','FIXED' if all(passed('session_'+x) for x in ('first','restart','disabled','empty')) else 'PARTIALLY FIXED'),
(14,'اكتشاف تلقائي معكوس','المنتقى tk.Label والقائمة tk.Menu يتلقيان نصًا مشكّلًا','ui_controls','إصلاح selected Label في init/set/configure/variable/dropdown دون تغيير الرمز','Windows لقطات selected/expanded في صفحة Video Download','FIXED' if passed('regression_installed') else 'NOT TESTED')]
report=f'''# Veyora Pro 2.0.3 — تقرير الإصلاح والتحقق

**القبول النهائي: INCOMPLETE.** حالة الأغنية الأصلية والغناء البشري والتحقق الصوتي لكل لغة ليست مكتملة. هذه Regression Review للمراجعة وليست نسخة معتمدة للإنتاج، ولا نشر رسمي ولا تغيير لـmain.

فرع التطوير: development/veyora-2.0.3-regression-recovery.
Commit المصدر والبناء: `{sha}`. تُنشأ حزمة المصدر من HEAD نفسه، ويُفحص ZIP وSHA-256 في File-Verification.json.

## A — المشاكل الـ14

| # | المشكلة | السبب | الملفات | التصحيح | الدليل | الحالة |
|---|---|---|---|---|---|---|
'''
for row in issues:report+='| '+' | '.join(map(str,row))+' |\n'
report+='\n## B — تدقيق التطبيق والعيوب الإضافية\n\n'+(root/'docs/REPAIR_14_AUDIT.md').read_text(encoding='utf8')+'\n'
report+='\n## C — جودة التعرف والترجمة\n\nالصوت المرجعي SAPI اصطناعي معلوم النص؛ الموسيقى والمؤثرات مولدة محليًا، وليست أغاني بشرية. WER لا يقيس جودة العربية. لم يُغيّر محرك Argos أو نموذج Whisper لادعاء تحسن غير مقاس.\n\n| عينة | WER سابق | WER حالي أصلي |\n|---|---:|---:|\n'
for row in quality.get('asr_before_after',[]):report+=f"| {row['sample']} | {row['before_wer']:.3f} | {row['after_wer']:.3f} |\n"
report+='\nالسياسة التلقائية على العينات نفسها:\n```json\n'+json.dumps(quality.get('automatic_policy','NOT TESTED'),ensure_ascii=False,indent=2)+'\n```\n'
report+='\nمقارنة النص قبل السياق وبعده، والنص المرجعي، دون ادعاء أن كل ترجمة أدق:\n```json\n'+json.dumps(quality.get('translation','NOT TESTED'),ensure_ascii=False,indent=2)+'\n```\n'
report+='\n## D — مصفوفة اللغات الفعلية\n\nالجرد مستمد من Transcriber والتحقق في TranslationPipeline وقائمة لغات UI: الإنجليزية والعربية والتركية والكورية فقط. auto وضع كشف وليس لغة. الإسبانية/الفرنسية/الألمانية/اليابانية/الصينية/الروسية/الهندية غير معلنة في هذه الواجهة: UNSUPPORTED في المسار الحالي، رغم أن Whisper العام قد يعرف بعضها. لا نضيفها شكليًا إلى القائمة.\n\n| اللغة | دعم ASR بالكود | مسار العربية | اختبار محلي | اختبار تنزيل | الجودة | الحالة |\n|---|---|---|---|---|---|---|\n'
for code,name,route in [('en','الإنجليزية','en→ar مباشر'),('ar','العربية','نسخ النص عند تطابق المصدر والهدف'),('tr','التركية','tr→en→ar محوري'),('ko','الكورية','ko→en→ar محوري')]:
 native=next((x for x in reg.get('multilingual',[]) if x['language']==code),{})
 local='صوت فعلي + SRT' if code=='en' and passed('regression_installed') else 'SRT نصي فقط؛ ASR NOT TESTED' if native else 'NOT TESTED'
 downloaded='صوت فعلي على الملف نفسه' if code=='en' and reg.get('shared_local_download_engine') else 'NOT TESTED'
 report+=f'| {name} | base/small/medium؛ en يستخدم base.en مع base | {route} | {local} | {downloaded} | مخرجات قابلة للمراجعة؛ لا اعتماد بشري شامل | PARTIAL |\n'
report+='\nمخرجات العربية لكل لغة SRT، وهي ليست دليل اختبار التعرف على صوت تلك اللغات:\n```json\n'+json.dumps(reg.get('multilingual','NOT TESTED'),ensure_ascii=False,indent=2)+'\n```\n'
report+=f'\n## E — Windows والاختبارات\n\nPython: `{unit}`. المتجاوزة ليست ناجحة. نجاحات الوحدات المحاكية لا تعوّض الاختبارات الفعلية أدناه.\n\n| الاختبار | النتيجة الفعلية |\n|---|---|\n'
for name,record in records.items():
 report+=f"| {name} | {'NOT TESTED' if record is None else 'PASS' if record.get('ok') else 'FAIL'} |\n"
 if record and record.get('errors'):report+='\n```\n'+'\n'.join(record['errors'])+'\n```\n'
report+=f"\nSRT الفعلي={video.get('cue_count','NOT TESTED')} مقطع، مدة={video.get('duration_seconds','NOT TESTED')} ثانية، إلغاء={video.get('cancellation_seconds','NOT TESTED')} ثانية، تصغير/استعادة={video.get('minimize_restore_cycles','NOT TESTED')}. مؤشرات UI: `{video.get('ui_timer','NOT TESTED')}`.\n"
report+='\n## F — التسليم والتتبع\n\nالمصدر الكامل ZIP وPortable وSetup تُبنى من commit المذكور نفسه، مع هوية تثبيت مستقلة عن النسختين السابقتين. الحجم والبصمة النهائيان في Veyora-Pro-2.0.3-File-Verification.json؛ لا تُكتب أرقام تقديرية قبل إنتاج الملفات. الروابط هي Artifacts للبناء الحالي وليست روابط المستودع بدل المصدر. لم يُنفذ تحديث إنتاجي موقّع؛ يلزم مفتاح المالك. توجد اختبارات مثبت ومحمول منفصلة، وأي إخفاق فيها يبقي الحالة FAIL. لا شهادة شاملة لكل موقع أو codec أو مشغّل أو كل نص عربي.\n'
(out/'Veyora-Pro-2.0.3-Test-Report.md').write_text(report,encoding='utf8')
(out/'Veyora-Pro-2.0.3-Translation-Regression-Report.md').write_text(report,encoding='utf8')
(out/'Veyora-Pro-2.0.3-Control-Inventory.json').write_text(json.dumps(inventory(),ensure_ascii=False,indent=2),encoding='utf8')
(out/'actual-test-results.json').write_text(json.dumps(dict(commit=sha,acceptance_complete=False,unit=unit,reports=records),ensure_ascii=False,indent=2),encoding='utf8')
print('Wrote Arabic evidence reports for',sha,'acceptance INCOMPLETE')
