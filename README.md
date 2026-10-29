# Veyora Pro

**حمّل الفيديو. افهم الكلام.**
# Veyora Downloader 4K

`Python 3.12+` | `CustomTkinter` | `yt-dlp` | `FFmpeg` | `Windows` | `MIT License`

## Overview
**Veyora Downloader 4K** is a modern, open-source desktop application designed for downloading high-definition videos up to 4K resolution and extracting high-fidelity audio streams. Built using Python 3.12, CustomTkinter, yt-dlp, and FFmpeg, Veyora offers a fast, reliable, and user-friendly experience for managing media downloads across hundreds of web platforms.

## Key Features
- **Ultra-HD 4K & Quality Control**: Download videos seamlessly in 4K, 1080p, 720p, and other resolutions with automatic video and audio merging powered by FFmpeg.
- **Universal Platform Support**: Extract media from YouTube, Vimeo, TikTok, and hundreds of other platforms supported natively by `yt-dlp`.
- **High-Fidelity Audio Extraction**: Extract audio streams in popular formats including MP3 and M4A with customizable bitrate selection and metadata tagging via `mutagen`.
- **Playlists & Batch Downloading**: Download complete playlists, channels, and batch video queues effortlessly.
- **Subtitles & Thumbnails**: Automatically fetch and embed subtitles and high-resolution thumbnail images into downloaded files.
- **Concurrent Queue Manager**: Manage multiple ongoing downloads with real-time speed monitoring, estimated time remaining (ETA), and progress indicators.
- **Modern Flicker-Free UI**: Enjoy a sleek dark/light theme switcher built with `CustomTkinter`, complete with keyboard shortcuts, configuration persistence, and download history management.

## Tech Stack & Dependencies
The project relies on modern Python technologies and powerful open-source media engines:

| Dependency | Required Version | Description |
| :--- | :--- | :--- |
| **CustomTkinter** | `>=5.2.0` | Modern UI toolkit for Tkinter |
| **yt-dlp** | `>=2025.0.0` | Media extraction engine |
| **FFmpeg** | `Latest` | Video/audio transcoding and stream merging engine |
| **requests** | `>=2.31.0` | HTTP network communication library |
| **mutagen** | `>=1.47.0` | Audio metadata tagging library |
| **Pillow** | `>=10.0.0` | Image processing library for thumbnail rendering |
| **darkdetect** | `>=0.8.0` | OS theme detection utility |
| **certifi** | `>=2023.5.7` | SSL certificate authority bundle |

## Prerequisites & Installation

### Option 1: Standalone Windows Executable
1. Go to the Releases section of this repository.
2. Download the latest `Veyora.exe` release.
3. Launch `Veyora.exe` directly on Windows without installing Python or dependencies.

### Option 2: Running from Source Code
1. **Prerequisites**: Ensure **Python 3.12+** and **FFmpeg** are installed on your system and added to your system `PATH`.
2. **Clone Repository**:
   ```bash
   git clone <repository_url>
   cd Veyora-Downloader-4K
   ```
3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Run Application**:
   ```bash
   python main.py
   ```

## Usage & Keyboard Shortcuts
1. **Paste Link**: Copy a video or playlist URL into the input field (`Ctrl + V`).
2. **Select Format & Quality**: Choose your preferred resolution (4K, 1080p, 720p) or select Audio-only (MP3/M4A).
3. **Download**: Click the **Download** button or press `Enter` to start downloading.

### Useful Keyboard Shortcuts
- `Ctrl + V`: Paste URL from clipboard.
- `Enter`: Trigger media download.
- `Ctrl + D`: Switch between Dark and Light mode.
- `Ctrl + C`: Cancel active download queue.

## Troubleshooting / FAQ & License

### Common Issues & Troubleshooting
- **FFmpeg Not Found**: Ensure FFmpeg binary files (`ffmpeg.exe`, `ffprobe.exe`) are placed in system `PATH` or inside the application directory.
- **Download Speed Limitations**: Update `yt-dlp` to the latest version using `pip install --upgrade yt-dlp`.

### Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the Issues tab.

### License
This project is licensed under the MIT License.
تطبيق مكتبي لـ Windows لتنزيل الفيديو والصوت، وإنشاء ترجمة مكتوبة محلية بين العربية والإنجليزية في الاتجاهين، وحفظها منفصلة أو داخل الفيديو.

[تحميل حزمة Windows 1.5.0](https://github.com/ahmadabusawwa/Veyora-Downloader-4K/releases/download/1.5.0/Veyora-Pro-1.5.0-Windows-x64.exe) · [الموقع](https://ahmadabusawwa.github.io/Veyora-Downloader-4K/) · [كل الإصدارات](https://github.com/ahmadabusawwa/Veyora-Downloader-4K/releases) · [الدعم](https://github.com/ahmadabusawwa/Veyora-Downloader-4K/issues)

## التنزيل والتشغيل

التحميل الرئيسي هو **ملف EXE** للإصدار 1.5.0:

[تحميل Windows EXE](https://github.com/ahmadabusawwa/Veyora-Downloader-4K/releases/download/1.5.0/Veyora-Pro-1.5.0-Windows-x64.exe) · [نسخة ZIP المحمولة](https://github.com/ahmadabusawwa/Veyora-Downloader-4K/releases/download/1.5.0/Veyora-Pro-1.5.0-Windows-x64.zip)

| الملف | الحجم | الاستخدام |
| --- | --- | --- |
| `Veyora-Pro-1.5.0-Windows-x64.exe` | 235,247,060 بايت — نحو224.3MiB | نزّل الملف وافتحه واتبع أي إرشادات تظهر. |
| `Veyora-Pro-1.5.0-Windows-x64.zip` | 302,331,801 بايت — نحو288.3MiB | فك الضغط كاملًا، وافتح التطبيق مع إبقاء `_internal` بجانبه. |

النظام المستهدف Windows10/11 بنسخة64-bit. لا تنقل EXE الخاص بحزمة ZIP وحده، ولا تشغّله من داخل الأرشيف. روابط **Source code** التلقائية ليست حزمة تشغيل Windows.

<details>
<summary>بصمتا SHA-256 للملفين المنشورين</summary>

EXE:

```text
190a0a124a71432b6a2c03b614e412825be9dbe72f2ec7eef7526e1656d9ca07
```

ZIP:

```text
cd23cacfc15744ebf99ef92d472dde7ad08d300a915369d82481f044c713b1a9
```

الحجم والبصمة من بيانات GitHub Releases. مطابقة البصمة تتحقق من هوية الملف، وليست اختبارًا مستقلًا لتشغيله أو أمانه. لم يُشغّل EXE المنشور ضمن مراجعة الموقع.
</details>

## المميزات

- تنزيل الفيديو والصوت من المواقع التي يدعمها yt-dlp ، حسب توفر المحتوى وقيود المصدر.
- اختيار دقات حتى 4K عندما يوفرها المصدر، واستخراج الصوت.
- قائمة تنزيلات مع الإيقاف المؤقت والاستئناف والإلغاء؛ الاستئناف يعتمد على دعم الخادم وصلاحية الرابط.
- ترجمة صوت إنجليزي إلى ترجمة مكتوبة بالعربية، أو صوت عربي إلى ترجمة مكتوبة بالإنجليزية.
- معالجة الكلام والنص محليًا بعد تنزيل النماذج المطلوبة.
- SRT منفصل، أو مسار ترجمة داخل MKV ، أو حرق الترجمة داخل MP4.
- عرض تقدّم الحرق والسرعة والوقت المتبقي التقديري عند توفر بيانات كافية.
- إعدادات معالجة لتخفيف ضغط الذاكرة وتشغيل مهمة معالجة ثقيلة واحدة في الوقت.

## اختيار اللغة

فعّل **Download Subtitles** ثم اختر اتجاه الترجمة:

| الاختيار | لغة الصوت | لغة الترجمة المكتوبة |
| --- | --- | --- |
| Auto-Translate: English -> Arabic | إنجليزي | عربي |
| Auto-Translate: Arabic -> English | عربي | إنجليزي |

**Arabic** و**English** دون Auto-Translate يطلبان ترجمة جاهزة من الموقع؛ لا يُنشئان ترجمة جديدة من الكلام. توفرها يعتمد على المصدر. الترجمة المحلية الحالية مخصصة للاتجاهين أعلاه وليست لجميع اللغات.

## خيارات الحفظ

| الخيار | النتيجة |
| --- | --- |
| `separate` | ملف `.srt` منفصل بجانب الفيديو. |
| `embed` | نسخة MKV بمسار ترجمة قابل للتشغيل والإخفاء. |
| `burn` | نسخة MP4 والترجمة دائمة داخل الصورة؛ تعيد ترميز الفيديو. |
| `both` | ملف SRT ونسخة MKV بمسار ترجمة. |

يبقى الفيديو الأصلي محفوظًا. قد يحفظ التطبيق أيضًا تفريغًا بلغة الكلام الأصلية لإعادة المحاولة. اختر `.ar.srt` للعربية و`.en.srt` للإنجليزية في المشغّل، أو اختر مسار اللغة المطلوبة داخل MKV. للمشاهدة استخدم مشغّلًا يدعم الفيديو والترجمة مثل VLC.

## أول ترجمة والنماذج

يحتاج تنزيل الفيديو الإنترنت. أول استخدام للترجمة قد ينزّل نماذج الكلام والنص الناقصة:

- نموذج الإنجليزية إلى العربية: نحو 84MiB.
- نموذج العربية إلى الإنجليزية: نحو 78MiB.
- نموذج كلام إضافي عند الحاجة؛ العربية تستخدم نموذجًا متعدد اللغات مختلفًا عن نموذج الإنجليزية.

بعد تنزيل النماذج تبقى محفوظة للاستخدام التالي، وتعمل معالجة الكلام وترجمة النص محليًا. ملفات الإعدادات والسجل والنماذج والتفريغ المخبأ عادة تحت `%USERPROFILE%\.veyora`.

## الأداء والجودة

حرق الترجمة يعيد ترميز الفيديو كاملًا وقد يستغرق وقتًا طويلًا، خصوصًا مع 4K. `embed` عادة أسرع لأنه ينسخ الصورة ويضيف مسار الترجمة. الوقت المتبقي تقديري ويتغير مع المشاهد وحِمل الجهاز. إعدادات تخفيف الذاكرة ليست سقفًا ثابتًا مضمونًا لاستهلاك RAM ، وقد تزيد المدة على بعض المعالجات.

جودة التعرف والترجمة تختلف مع اللهجة والضوضاء والمصطلحات. راجع النص قبل نشره أو استخدامه في عمل يحتاج دقة لغوية. الإلغاء تعاوني؛ قد ينتظر التطبيق الاستدعاء الجاري للنموذج أو حدود بعض مراحل المعالجة.

## الخصوصية والاستخدام

مسار الترجمة المحلية لا يستخدم خدمة ترجمة Google ولا يرسل إليها الصوت أو النص. تنزيل الوسائط يتصل بمواقعها وتنزيل النماذج يتصل بمستضيفيها. صفحة الموقع تستخدم خطوط النظام وملفات الشعار والتنسيق والسكريبت المحلية، وتتصل بواجهة GitHub العامة لتحديث معلومات الإصدار.

استخدم البرنامج للمحتوى الذي تملك حق تنزيله ومعالجته، والتزم بشروط المواقع وحقوق أصحاب المحتوى. لكل مكوّن ونموذج خارجي شروطه الخاصة؛ لا تمنح هذه الصفحة ترخيصًا لإعادة توزيع مكونات خارجية.

## المساعدة

[افتح بلاغًا](https://github.com/ahmadabusawwa/Veyora-Downloader-4K/issues) مع رقم الإصدار ونظام Windows والخطوات ورسالة الخطأ واتجاه الترجمة وطريقة الحفظ. لا ترفق كلمات مرور أو ملفات cookies أو بيانات شخصية غير لازمة.

## عن هذا المستودع

هذا المستودع يضم صفحة الموقع ووثائق التنزيل. وجود `requirements.txt` لا يعني أن مصدر تطبيق Windows الكامل موجود هنا. تحقق صفحة الموقع من سلامة الروابط والبيانات لا يُعد اختبارًا لتشغيل الملف التنفيذي.

اختبارات اختيار حزمة التنزيل، باستخدام Node.js18+:

```sh
node --test tests/release.test.cjs
```

[دليل تحديث الموقع وروابط الإصدارات](docs/PUBLISHING.md)
