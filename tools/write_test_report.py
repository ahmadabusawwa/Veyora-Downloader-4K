"""Build the delivery report from actual test artifacts, never assumed successes."""
from pathlib import Path
import json,subprocess,xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1];out=root/'dist';out.mkdir(exist_ok=True)
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
def read(path):
 try:return json.loads((root/path).read_text(encoding='utf-8-sig'))
 except (OSError,ValueError):return None
records={name:read(path) for name,path in {
 'navigation':'real-video-review/navigation-results.json','final_ui':'real-video-review/final-ui/final-ui-results.json',
 'recovery':'real-video-review/recovery/recovery-results.json','video':'real-video-review/real-video-results.json',
 'quality':'real-video-review/quality/media-quality-results.json','close_idle':'real-video-review/close-idle/close-results.json',
 'close_download':'real-video-review/close-download/close-results.json','close_translation':'real-video-review/close-translation/close-results.json'}.items()}
unit=None
try:
 xml=ET.parse(root/'windows-tests.xml').getroot();suites=[xml] if xml.tag=='testsuite' else list(xml)
 unit={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
 unit['passed']=unit['tests']-unit['failures']-unit['errors']-unit['skipped']
except (OSError,ET.ParseError):pass
report=f'''# Veyora Pro 2.0.3 — تقرير الإصلاح والاختبارات

معرّف Git المستخدم في البناء: `{sha}`.

النسخة Repair Review تحمل الإصدار 2.0.3 كما طُلب، وبهوية تثبيت ومجلد مستقلين عن Review السابقة. لا نشر رسمي ولا تعديل لـ main. النسخة السابقة محفوظة على فرع backup/veyora-2.0.3-before-final-fixes وبـSetup احتياطي مستقل.

## أسباب المشاكل والإصلاحات

- التحويل: لم يُعد إنتاج تعطل بدء المعالجة المطلق؛ أكدت الاختبارات السابقة عمل WAV. ثبت أن حالة انشغال ترجمة في الخلفية كانت تعطّل البدء دون شرح في صفحة التحويل. أضيف تفسير واضح، وتسميات للصيغة والترميز والدقة والجودة، وخيارات CRF حقيقية ومعدل مخصص، وفحص مدخلات وناتج FFmpeg. أضيف قسم استخراج MP3/WAV وزر فعلي له وأزرار الناتج. الصفحة قابلة للتمرير، وحجم النافذة الابتدائي يراعي الشاشة.
- Playlist: كانت ترث الجودة والترجمة من Dashboard المخفية؛ صارت لها إعدادات مستقلة افتراضيها Best Available وترجمة متوقفة، مع لغة ونوع إخراج وصيغة ومراجعة فعلية قبل البدء. الجودة المحددة تضع سقفًا ولا تقفز إلى جودة أعلى. أضيف ضمان الحاوية المطلوبة وفحص الملف النهائي بـffprobe قبل الاكتمال. يحتفظ Retry بهوية المهمة، والعنصر الفاشل لا يوقف بقية القائمة. سجلات الفشل تحمل معرف المهمة.
- السجل والاستعادة: كانت المهام المكتملة لا تعود للواجهة إلا باستدعاء الاستعادة الذي لا يُعرض عند اكتمالها كلها. أصبحت النتائج النهائية تُحمّل بعد إعادة التشغيل دون إعادة تنزيل. تظهر نتائج الترجمة المحلية في Downloads أيضًا، مع المسار النهائي وSRT وإجراءات الفتح.
- المعاينة: تحقّقنا من أن زر المعاينة السابق كان يرندر إطارًا فعليًا؛ حافظنا على renderer، وأضفنا شاشة واضحة وتحديثًا مؤجلًا 350ms وطابورًا محدودًا وعاملًا واحدًا. تتغير الصورة مع حجم الخط واللون والحد والهامش والموضع. يستخدم نص SRT الفعلي إن توفر، وخلفية تجريبية عند عدم توفر فيديو، وبنفس libass المستخدم في التصدير.
- التعريب: تستخدم DropdownMenu في CustomTkinter قائمة Windows أصلية؛ تمرير أشكال العرض العربية إليها أفسد ترتيب بعض الحروف واللام ألف. فُصل النص المنطقي للقائمة الأصلية عن نص الرسم، مع بقاء رمز اللغة مستقلًا. لم تُستبدل دالة إصلاح عناوين الفيديوهات. استُبدلت نافذة تأكيد الإغلاق بنعم/لا داخل CustomTkinter، مع حفظ الاستعادة خارج UI thread وانتظار إلغاء العامل المحلي قبل الإغلاق.
- التعرف والسياق: كان مسار الإعادة بلا VAD يستخدم no_speech_threshold=1.0 وlog_prob_threshold=None، أي يخفف رفض الكلام غير الواثق. أُعيدت حدود الرفض وأضيف رفض المقاطع الضعيفة في الإعادة. صار السياق التلقائي يربط أجزاء الجملة والضمير مع سابقه ضمن حدود، ويترك الجمل المكتملة المستقلة منفصلة. تحسين الحوار التلقائي محافظ: لا تُفرض معالجة فصل غير مثبتة الفائدة على كل فيديو؛ يظل التشغيل اليدوي والإيقاف في الإعدادات المتقدمة. الصوت المعالج مخصص للتعرف، وصوت الفيديو النهائي يأتي من الأصل.

## الملفات الأساسية المعدلة

main.py، desktop_ui.py، local_tasks.py، conversion_page.py، media_conversion.py، playlist_page.py، playlist_options.py، output_actions.py، confirmation.py، ui_controls.py، ui_text.py، media_options_ui.py، runtime_support.py، translator/pipeline.py وtranscription.py وvideo_renderer.py وrecognition_policy.py، مع اختبارات ومرجع التعرف السابق وإعدادات PyInstaller/Inno Setup وGitHub Actions.

## الاختبارات الفعلية

أرقام Python: `{unit}`. المتجاوزة ليست ناجحة. الاختبارات داخل EXE المثبت منفصلة عن اختبارات الوحدات والمحاكاة.

| الحالة | نتيجة التقرير الفعلي |
|---|---|
'''
for name,record in records.items():
 status='غير منفذ / لا تقرير' if record is None else 'نجح' if record.get('ok') else 'فشل'
 report+=f'| {name} | {status} |\n'
 if record and record.get('errors'):report+='\nتفاصيل '+name+':\n```\n'+'\n'.join(record['errors'])+'\n```\n'
video=records.get('video') or {};nav=records.get('navigation') or {};quality=records.get('quality') or {}
report+=f'''\nالترجمة الفعلية: عدد مقاطع SRT={video.get('cue_count','غير متحقق')}، مدة الفيديو={video.get('duration_seconds','غير متحقق')} ثانية، زمن الإلغاء={video.get('cancellation_seconds','غير متحقق')} ثانية. التنقل أثناء الكلام={video.get('navigation_during_speech_steps','غير متحقق')}، ودورات التصغير والاستعادة={video.get('minimize_restore_cycles','غير متحقق')}. قياسات UI: `{video.get('ui_timer','غير متحقق')}`.

صفحات التنقل: `{nav.get('build_counts','غير متحقق')}`، تغير الذاكرة={nav.get('memory_growth_bytes','غير متحقق')} بايت. لا يُعد ذلك ضمانًا لعدم وجود تسرب على كل الأجهزة والفترات.

اختبار القائمة المحلي داخل النسخة المثبتة يتضمن ملفين صالحين ورابطًا يفشل 404، ثم إصلاح المصدر وإعادة المحاولة. فُحص عدم إعادة تنزيل المكتملين وحاوية MKV. اختبار التحويل يستدعي الأزرار الفعلية للصيغ الأربع. اختبارات الإغلاق تضغط لا ثم نعم أثناء التنزيل والترجمة وتفحص حفظ المهام.

## مقارنة التعرف على عينات ثابتة

المرجع السابق هو كود التعرف عند ffd9c5960afc732bf1502352c1e29a5870176dbd، محفوظ في benchmark_reference.py للمقارنة فقط. المقاطع نفسها تُمرر للمسارين. العينات صوت SAPI معلوم النص وموسيقى أصلية مؤلفة برمجيًا؛ ليست غناءً بشريًا. الذاكرة التالية Working Set لحظة القياس وليست قمة الاستهلاك. الأزمنة تتأثر بتسخين الأوزان ولا تثبت تسريعًا عامًا.

| العينة | WER سابق | WER حالي | الزمن السابق/الحالي (ث) | Working Set سابق/حالي (بايت) |
|---|---:|---:|---|---|
'''
for row in quality.get('asr_before_after',[]):
 report+=f"| {row['sample']} | {row['before_wer']:.3f} | {row['after_wer']:.3f} | {row['before_seconds']}/{row['after_seconds']} | {row.get('working_set_before_bytes')}/{row.get('working_set_after_bytes')} |\n"
report+=f'''\nانحدار WER مكتشف: `{quality.get('asr_regression_detected','غير منفذ')}`. كلمات في عينة الموسيقى وحدها: `{quality.get('music_only_text','غير منفذ')}`. تجريب VAD أكثر حساسية محفوظ في JSON، ولم يُجعل افتراضيًا دون دليل. فائدة معالجة الحوار في عينة الموسيقى: `{quality.get('speech_improvement_verified_on_fixture','غير منفذ')}`.

## القيود والحالات غير المتحققة

- لا تتوفر سجلات فشل فيديوهَي Playlist الأصليين، ولا مقطع المستخدم الذي يفقد الكلام؛ لذلك لا نثبت سبب فشلهما أو إصلاح تلك المقاطع نفسها. الاختبار المحلي لا يضمن تنزيل كل فيديو من YouTube أو كل موقع خارجي.
- لا يمكن استعادة كلمات غطتها الموسيقى بالكامل. مقارنة SAPI لا تُعد اعتمادًا لدقة الغناء البشري أو اللهجات أو كل اللغات. نتائج الترجمة الآلية قد تتضمن ضمائر ومعاني غير دقيقة؛ لا تغيير لمحرك النصوص دون قياس.
- التحسين التلقائي لا يفرض فصل الموسيقى غير المثبت فائدته. اليدوي متاح للحوار المركزي في stereo؛ ليس فصلًا عصبيًا عامًا.
- فتح الملفات يعتمد على تطبيقات Windows المثبتة. تُختبر طلبات الفتح في CI؛ ذلك لا يثبت توفر كل مشغّل وكل codec على جهاز المستخدم. يوجد fallback إلى Notepad لملف SRT دون ارتباط افتراضي.
- استعادة التنزيل اختُبرت بقتل العملية وHTTP Range. لم تُقطع الكهرباء فعليًا؛ بعض المصادر لا تدعم الاستئناف من نفس النسبة، والروابط قد تنتهي.
- نوافذ اختيار الملفات واللون تستخدم خدمات النظام. تُفحص تعديلات اللون والمعاينة والتصدير؛ أي تفاعل نظام غير موثق في JSON يبقى غير متحقق.

## ملاحظات التطوير والحماية

كشف التحقق الجديد أن اختبار resume القديم كان يحمّل بايتات عشوائية باسم MP4؛ استُبدل بوسائط فعلية، لأن ملفًا غير قابل للقراءة لا يصح اعتباره تنزيل فيديو ناجحًا. عُزل اختبار الفلتر الذي افترض قائمة فارغة؛ تحميل النتائج المكتملة تلقائيًا سلوك مقصود ويحفظ الاستعادة.

التسليم يحتوي على المصدر الكامل من commit البناء نفسه، وPortable، وSetup، وهذا التقرير وملف File-Verification.json. لا تضمين للنماذج أو venv أو ملفات build في المصدر. تُنزّل النماذج مرة أولى، ثم يمكن التشغيل دون إنترنت. تحفظ artifacts لمدة 90 يومًا، ولا نشر Release تلقائي.
'''
(out/'Veyora-Pro-2.0.3-Test-Report.md').write_text(report,encoding='utf8')
(out/'actual-test-results.json').write_text(json.dumps(dict(commit=sha,unit=unit,reports=records),ensure_ascii=False,indent=2),encoding='utf8')
print('Wrote actual results report for',sha)
