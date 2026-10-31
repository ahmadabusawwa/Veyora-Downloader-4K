"""Translate worker stage identifiers once at the UI boundary; keep raw paths separate."""
import re

def stage_text(stage,arabic,shaped=True):
    if not arabic:return stage
    from main import fix_arabic_text
    def display(text):return fix_arabic_text(text) if shaped else text
    exact={'Splitting completed video into parts':'جارٍ تقسيم الفيديو المكتمل إلى مقاطع','Comparing original audio with dialogue enhancement':'جارٍ مقارنة الصوت الأصلي بتحسين الحوار','Full download finished; clipping selected interval locally':'اكتمل التنزيل الكامل؛ جارٍ قص المقطع محليًا','Clipping downloaded video':'جارٍ قص الفيديو المحمّل','Checking final media file':'جارٍ التحقق من الملف النهائي','Checking input media':'جارٍ التحقق من ملف الوسائط','Task started, preparing…':'بدأت المهمة، جارٍ التجهيز…','Task cancelled.':'أُلغيت المهمة.','Cancelling task…':'جارٍ إلغاء المهمة…','Converting media':'جارٍ تحويل الوسائط','Extracting audio':'جارٍ استخراج الصوت','Waiting for speech recognizer':'بانتظار محرك التعرف على الكلام','Resolving...':'جارٍ قراءة بيانات الفيديو…','Task failed.':'فشلت المهمة.'}
    if stage in exact:return display(exact[stage])
    pairs=[('Checking saved','جارٍ فحص النص المحفوظ'),('Using saved','جارٍ استخدام النص المحفوظ'),('Loading','جارٍ تحميل النموذج'),('Downloading missing','جارٍ تنزيل النموذج الناقص'),('Recognizing','جارٍ التعرف على الكلام'),('Translating','جارٍ ترجمة النص'),('Burning','جارٍ حرق الترجمة'),('Embedding','جارٍ دمج الترجمة'),('Waiting for another processing job','بانتظار مهمة المعالجة الحالية'),('Saving completed video','جارٍ حفظ الفيديو النهائي'),('Enhancing speech recognition','جارٍ تحسين التعرف على الكلام')]
    for prefix,target in pairs:
        if stage.startswith(prefix):
            nums=re.findall(r'\d+(?:\.\d+)?%?|\d+:\d+',stage)
            return display(target)+('  '+' / '.join(nums) if nums else '')
    if stage.startswith('Saved:'):return display('حُفظت الملفات الناتجة.')
    return stage
