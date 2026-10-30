"""Veyora Pro 2.0 native desktop shell.

The 1.7 download/translation engine in :mod:`main` is reused unchanged.  This
module replaces the shell with the panel layout from the 2.0 reference design:
a branded top bar, a task sidebar, a URL/preview/options dashboard, a queue with
filters and a live status strip.  Arabic and English are first-class UI
languages and every primary action remains reachable without a mouse-only
dialog.
"""
from __future__ import annotations

import io
import os
import re
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw

from main import (
    APP_VERSION,
    CONFIG_DIR,
    LANGUAGES,
    SUBTITLE_CHOICES,
    TRANSLATION_DIRECTIONS,
    DownloadEngine,
    HistoryManager,
    SettingsManager,
    VeyoraApp,
    fix_arabic_text,
    is_valid_url,
    normalize_url,
    open_file_in_explorer,
    open_folder_in_explorer,
    selected_subtitle_language,
)
from ui_icons import icon
from runtime_support import LatestProgress, friendly_error


# ---------------------------------------------------------------------------
# Design tokens matching the Veyora Pro 2.0 reference interface
# ---------------------------------------------------------------------------
DARK = dict(
    bg="#080d14",
    bg_soft="#0b131c",
    panel="#101b27",
    panel2="#152636",
    edge="#22384d",
    blue="#0084ff",
    blue_soft="#143654",
    blue_hover="#1b6ec2",
    text="#eaf3fc",
    muted="#9bb2c7",
    faint="#69839b",
    good="#24d582",
    bad="#f13d49",
    warn="#f5b82e",
    warn_bg="#33260b",
    chip="#122130",
)
LIGHT = dict(
    bg="#eef4f9",
    bg_soft="#f7fafc",
    panel="#ffffff",
    panel2="#e8f1f8",
    edge="#c7d8e5",
    blue="#0077e6",
    blue_soft="#dcebfa",
    blue_hover="#005fbb",
    text="#0b2233",
    muted="#4b6477",
    faint="#7990a2",
    good="#128a55",
    bad="#c62f3a",
    warn="#9a6b00",
    warn_bg="#fff3d1",
    chip="#e4eef7",
)

STATUS_LABELS = {
    "Queued": ("في الانتظار", "Queued"),
    "Downloading": ("جاري التحميل", "Downloading"),
    "Paused": ("متوقف مؤقتًا", "Paused"),
    "Processing / Muxing": ("معالجة ودمج", "Processing / muxing"),
    "Merging & Processing (FFmpeg)...": ("معالجة ودمج", "Processing / muxing"),
    "Translating": ("جارٍ الترجمة", "Translating"),
    "Completed": ("مكتمل", "Completed"),
    "Failed": ("فشل التحميل", "Failed"),
    "Cancelled": ("ملغى", "Cancelled"),
}

FILTERS = (
    ("all", "الكل", "All"),
    ("downloading", "جاري", "Downloading"),
    ("completed", "مكتمل", "Completed"),
    ("failed", "فاشل", "Failed"),
)

LANGUAGE_NAMES_AR = {
    "ar": "العربية",
    "en": "الإنجليزية",
    "tr": "التركية",
    "ko": "الكورية",
}

QUALITY_OPTIONS = [
    ("Best Available (4K/HD)", "أفضل جودة - (2160p) 4K", "Best quality - 4K (2160p)"),
    ("2160p (4K)", "2160p (4K Ultra HD)", "2160p (4K Ultra HD)"),
    ("1440p (2K)", "1440p (2K QHD)", "1440p (2K QHD)"),
    ("1080p (Full HD)", "1080p (Full HD)", "1080p (Full HD)"),
    ("720p (HD)", "720p (HD)", "720p (HD)"),
    ("480p", "480p (SD)", "480p (SD)"),
]

FORMAT_OPTIONS = [
    ("MP4", "MP4 (Video + Audio)", "MP4 (Video + Audio)"),
    ("MKV", "MKV (Matroska)", "MKV (Matroska)"),
    ("MOV", "MOV (QuickTime)", "MOV (QuickTime)"),
    ("WEBM", "WEBM", "WEBM"),
]

SUBTITLE_MODE_OPTIONS = [
    ("separate", "SRT (ملف ترجمة)", "SRT (subtitle file)"),
    ("embed", "MKV (مدمج مع الفيديو)", "MKV (selectable track)"),
    ("burn", "MP4 (حرق على الفيديو)", "MP4 (burned into video)"),
    ("both", "SRT + MKV (كلاهما)", "SRT + MKV (both)"),
]


def direction_key(source: str, target: str, translating: bool = True) -> str:
    """Map a source/target pair onto a key used by the media engine.

    ``main`` understands ``auto-ar``/``auto-en`` for the two legacy directions,
    ``auto-<src>-<tgt>`` for the other explicit pairs, ``detect-<tgt>`` when the
    speech language must be detected, and a plain language code for native
    subtitles (no translation).
    """
    source = (source or "auto").lower().strip()
    target = (target or "ar").lower().strip()
    if source not in LANGUAGES and source != "auto":
        source = "auto"
    if target not in LANGUAGES:
        target = "ar"
    if not translating or source == target:
        return target
    if source == "auto":
        return f"detect-{target}"
    if (source, target) == ("en", "ar"):
        return "auto-ar"
    if (source, target) == ("ar", "en"):
        return "auto-en"
    return f"auto-{source}-{target}"


def language_from_key(key: str) -> tuple[str, str]:
    """Return the (source, target) pair represented by a saved ``sub_lang``."""
    key = (key or "").strip()
    if key == "auto-en-ar":
        return "en", "ar"
    if key == "auto-ar-en":
        return "ar", "en"
    if key in TRANSLATION_DIRECTIONS:
        return TRANSLATION_DIRECTIONS[key]
    if key in LANGUAGES:
        return key, key
    m = re.fullmatch(r"auto-(ar|en|tr|ko)-(ar|en|tr|ko)", key)
    if m:
        return m.group(1), m.group(2)
    m_det = re.fullmatch(r"detect-(ar|en|tr|ko)", key)
    if m_det:
        return "auto", m_det.group(1)
    return "en", "ar"


def _memory_megabytes() -> float:
    try:
        if hasattr(Path, "stat") and os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            ):
                return counters.WorkingSetSize / 1048576
    except Exception:
        pass
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:
        return 128.0


def _make_scenic_preview(width: int = 240, height: int = 135, with_duration: str = "12:34") -> Image.Image:
    """Create a crisp scenic mountain-lake preview image for the default preview card."""
    img = Image.new("RGB", (width, height), "#0d2538")
    draw = ImageDraw.Draw(img)
    # Sky gradient
    for y in range(height // 2):
        r = int(20 + (y / max(1, height // 2)) * 55)
        g = int(65 + (y / max(1, height // 2)) * 85)
        b = int(120 + (y / max(1, height // 2)) * 90)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    # Lake reflection gradient
    for y in range(height // 2, height):
        ratio = (y - height // 2) / max(1, height // 2)
        r = int(18 - ratio * 8)
        g = int(95 - ratio * 45)
        b = int(145 - ratio * 50)
        draw.line([(0, y), (width, y)], fill=(max(8, r), max(30, g), max(60, b)))
    # Distant snow mountains
    horizon = height // 2 + 4
    draw.polygon(
        [(0, horizon), (int(width * 0.18), int(height * 0.22)), (int(width * 0.38), int(height * 0.40)),
         (int(width * 0.56), int(height * 0.18)), (int(width * 0.78), int(height * 0.36)),
         (int(width * 0.92), int(height * 0.24)), (width, horizon)],
        fill="#3b698c",
    )
    draw.polygon(
        [(int(width * 0.10), horizon), (int(width * 0.28), int(height * 0.28)),
         (int(width * 0.48), int(height * 0.44)), (int(width * 0.68), int(height * 0.25)),
         (int(width * 0.88), horizon)],
        fill="#244966",
    )
    # Foreground pine silhouette on right
    for tree_x, tree_h in ((int(width * 0.84), int(height * 0.16)), (int(width * 0.91), int(height * 0.12))):
        for layer in range(4):
            top_y = tree_h + layer * 14
            spread = 10 + layer * 6
            draw.polygon(
                [(tree_x, top_y), (tree_x - spread, top_y + 22), (tree_x + spread, top_y + 22)],
                fill="#0b241e",
            )
    if with_duration:
        bw, bh = 46, 20
        bx, by = width - bw - 8, height - bh - 7
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=5, fill=(8, 13, 20))
        draw.text((bx + 8, by + 4), with_duration, fill="#ffffff")
    return img


class DesktopApp(VeyoraApp):
    """CustomTkinter shell that matches the Veyora Pro 2.0 reference design."""

    def __init__(self):
        self.icons = {
            name: icon(name, size=20)
            for name in (
                "download",
                "home",
                "audio",
                "list",
                "translate",
                "folder",
                "convert",
                "settings",
                "clock",
                "help",
                "search",
                "paste",
                "trash",
                "scissors",
                "refresh",
                "link",
            )
        }
        self._local_cancel = threading.Event()
        self._local_running = False
        self._card_percent_labels = {}
        self._card_status_labels = {}
        self._layout_narrow = None
        self._update_state = "idle"
        self._status_clock_running = False
        self._syncing_controls = False
        super().__init__()
        self.title(f"Veyora Pro {APP_VERSION} — Downloader & Translator")
        self.geometry("1536x980")
        self.minsize(1080, 760)
        self.configure(fg_color=self.c["bg"])
        self._start_status_clock()

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    @property
    def c(self):
        return LIGHT if self.settings.get("theme", "Dark") == "Light" else DARK

    @property
    def is_arabic(self):
        return self.settings.get("ui_language", "ar") == "ar"

    def t(self, ar, en):
        return fix_arabic_text(ar) if self.is_arabic else en

    def _anchor(self):
        return "e" if self.is_arabic else "w"

    def _justify(self):
        return "right" if self.is_arabic else "left"

    def button(self, parent, text, command, **kw):
        """Create a themed button, extracting a leading icon glyph if present."""
        symbols = {
            "⇩": "download",
            "⌂": "home",
            "♫": "audio",
            "☷": "list",
            "▣": "translate",
            "▱": "folder",
            "⇄": "convert",
            "⚙": "settings",
            "◷": "clock",
            "?": "help",
            "🔍": "search",
            "📋": "paste",
            "🗑": "trash",
            "✂": "scissors",
            "↻": "refresh",
            "🔗": "link",
        }
        compound = kw.pop("compound", "left")
        for symbol, name in symbols.items():
            if symbol in text:
                text = text.replace(symbol, "").strip()
                kw["image"] = self.icons[name]
                kw["compound"] = compound
                break
        fg = kw.pop("fg_color", self.c["blue"])
        hover = kw.pop("hover_color", self.c["blue_hover"])
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color=fg,
            hover_color=hover,
            corner_radius=kw.pop("corner_radius", 10),
            height=kw.pop("height", 38),
            text_color=kw.pop("text_color", "#ffffff"),
            font=kw.pop("font", ("Segoe UI", 13)),
            **kw,
        )

    def ghost_button(self, parent, text, command, **kw):
        return self.button(
            parent,
            text,
            command,
            fg_color=kw.pop("fg_color", "transparent"),
            hover_color=kw.pop("hover_color", self.c["blue_soft"]),
            text_color=kw.pop("text_color", self.c["text"]),
            border_width=kw.pop("border_width", 0),
            border_color=kw.pop("border_color", self.c["edge"]),
            **kw,
        )

    def card(self, parent, **kw):
        return ctk.CTkFrame(
            parent,
            fg_color=kw.pop("fg_color", self.c["panel"]),
            border_width=kw.pop("border_width", 1),
            border_color=kw.pop("border_color", self.c["edge"]),
            corner_radius=kw.pop("corner_radius", 14),
            **kw,
        )

    def section_title(self, parent, ar, en, **kw):
        text = self.t(ar, en)
        for symbol in ("⇩", "⌂", "♫", "☷", "▣", "▱", "⇄", "⚙", "◷", "?", "🔍", "📋", "🗑", "✂", "↻", "🔗"):
            text = text.replace(symbol, "")
        text = " ".join(text.split())
        return ctk.CTkLabel(
            parent,
            text=text,
            font=("Segoe UI", kw.pop("size", 15), "bold"),
            text_color=kw.pop("text_color", self.c["text"]),
            anchor=kw.pop("anchor", "w"),
            justify="left",
            **kw,
        )

    def _start_status_clock(self):
        if getattr(self, "_status_clock_running", False):
            return
        self._status_clock_running = True

        previous_wall, previous_cpu = time.monotonic(), time.process_time()

        def tick():
            nonlocal previous_wall, previous_cpu
            try:
                memory = _memory_megabytes()
                label = getattr(self, "memory_label", None)
                if label is not None and label.winfo_exists():
                    if memory >= 1024:
                        label.configure(
                            text=self.t(f"استخدام الذاكرة: {memory / 1024:.1f} GB", f"Memory: {memory / 1024:.1f} GB")
                        )
                    else:
                        label.configure(
                            text=self.t(f"استخدام الذاكرة: {memory:.0f} MB", f"RAM {memory:.0f} MB")
                        )
                label = getattr(self, "speed_label", None)
                if label is not None and label.winfo_exists():
                    speed = "0.0 MB/s"
                    for task in self.queue_manager.get_tasks_by_status():
                        if task.get("status") == "Downloading" and task.get("speed"):
                            speed = str(task["speed"])
                            break
                    label.configure(text=f"{self.t('سرعة التحميل:', 'Download speed:')} {speed}")
                cpu_lbl = getattr(self, "cpu_label", None)
                if cpu_lbl is not None and cpu_lbl.winfo_exists():
                    now, cpu = time.monotonic(), time.process_time()
                    cpu_pct = min(100, max(0, round(100 * (cpu - previous_cpu) /
                        max(.001, now - previous_wall) / (os.cpu_count() or 1))))
                    previous_wall, previous_cpu = now, cpu
                    cpu_lbl.configure(text=f"{self.t('استخدام المعالج:', 'CPU usage:')} {cpu_pct}%")
            except Exception:
                pass
            finally:
                self.after(2000, tick)

        self.after(600, tick)

    def set_update_state(self, text, state="idle"):
        """Called by :mod:`updater.ui` to keep the top-bar chip truthful."""
        self._update_state = state
        if not hasattr(self, "update_chip") or not self.update_chip.winfo_exists():
            return
        colors = {
            "idle": (self.c["blue"], "#ffffff"),
            "checking": (self.c["blue_soft"], self.c["text"]),
            "available": (self.c["blue"], "#ffffff"),
            "ready": (self.c["good"], "#042417"),
            "error": (self.c["panel2"], self.c["bad"]),
        }
        fg, fg_text = colors.get(state, colors["idle"])
        self.update_chip.configure(text=text, fg_color=fg, text_color=fg_text)

    def notify(self, ar, en, kind="info"):
        # Native Windows message boxes handle Unicode Arabic themselves.
        # Applying bidi reshaping here makes the text appear reversed.
        title = "فيفورا برو" if self.is_arabic else "Veyora Pro"
        text = ar if self.is_arabic else en
        if kind == "error":
            messagebox.showerror(title, text)
        elif kind == "warning":
            messagebox.showwarning(title, text)
        else:
            messagebox.showinfo(title, text)

    def ask(self, ar, en):
        # Do not pre-shape Arabic for native Windows dialogs.
        title = "فيفورا برو" if self.is_arabic else "Veyora Pro"
        text = ar if self.is_arabic else en
        return messagebox.askyesno(title, text)

    # ------------------------------------------------------------------
    # Language & Mode Mapping Helpers
    # ------------------------------------------------------------------
    def _source_labels(self) -> list[str]:
        if self.is_arabic:
            return [
                self.t("🌐 اكتشاف تلقائي", "Auto detect"),
                self.t("(ar) العربية", "Arabic (ar)"),
                self.t("(en) الإنجليزية", "English (en)"),
                self.t("(tr) التركية", "Turkish (tr)"),
                self.t("(ko) الكورية", "Korean (ko)"),
            ]
        return ["Auto detect"] + [f"{name} ({code})" for code, name in LANGUAGES.items()]

    def _target_labels(self) -> list[str]:
        return self._source_labels()[1:]

    def _label_for_lang(self, code: str, allow_auto: bool = True) -> str:
        code = (code or "auto").lower().strip()
        if code == "auto" and allow_auto:
            return self._source_labels()[0]
        if code not in LANGUAGES:
            code = "ar"
        if self.is_arabic:
            ar_name = LANGUAGE_NAMES_AR.get(code, "العربية")
            return self.t(f"({code}) {ar_name}", f"{LANGUAGES[code]} ({code})")
        return f"{LANGUAGES[code]} ({code})"

    @staticmethod
    def _lang_code(label: str) -> str:
        """Extract 'auto', 'ar', 'en', 'tr', or 'ko' regardless of RTL/BiDi label order."""
        if not label:
            return "auto"
        raw = str(label).strip()
        lowered = raw.lower()
        if lowered in LANGUAGES:
            return lowered
        if lowered == "auto" or "auto detect" in lowered or "اكتشاف" in raw:
            return "auto"
        # Match (ar), (en), (tr), (ko) anywhere in the label (start, middle, or end)
        m = re.search(r"\((ar|en|tr|ko)\)", lowered)
        if m:
            return m.group(1)
        m_word = re.search(r"\b(ar|en|tr|ko)\b", lowered)
        if m_word:
            return m_word.group(1)
        for code, en_name in LANGUAGES.items():
            if en_name.lower() in lowered:
                return code
        for code, ar_name in LANGUAGE_NAMES_AR.items():
            if ar_name in raw or fix_arabic_text(ar_name) in raw:
                return code
        return "auto"

    def _quality_display_values(self) -> list[str]:
        return [self.t(ar, en) for _, ar, en in QUALITY_OPTIONS]

    def _quality_to_display(self, code: str) -> str:
        for key, ar, en in QUALITY_OPTIONS:
            if key == code or code in (ar, en, self.t(ar, en)):
                return self.t(ar, en)
        return self._quality_display_values()[0]

    def _quality_from_display(self, display: str) -> str:
        if not display:
            return "Best Available (4K/HD)"
        for key, ar, en in QUALITY_OPTIONS:
            if display in (key, ar, en, self.t(ar, en)):
                return key
        for height in ("2160", "1440", "1080", "720", "480"):
            if height in display:
                for key, _, _ in QUALITY_OPTIONS:
                    if height in key:
                        return key
        return "Best Available (4K/HD)"

    def _format_display_values(self) -> list[str]:
        return [self.t(ar, en) for _, ar, en in FORMAT_OPTIONS]

    def _format_to_display(self, code: str) -> str:
        code_upper = (code or "MP4").upper()
        for key, ar, en in FORMAT_OPTIONS:
            if key == code_upper or code in (ar, en, self.t(ar, en)):
                return self.t(ar, en)
        return self._format_display_values()[0]

    def _format_from_display(self, display: str) -> str:
        if not display:
            return "MP4"
        upper = display.upper()
        for key, _, _ in FORMAT_OPTIONS:
            if key in upper:
                return key
        return "MP4"

    def _subtitle_mode_display_values(self) -> list[str]:
        return [self.t(ar, en) for _, ar, en in SUBTITLE_MODE_OPTIONS]

    def _subtitle_mode_to_display(self, mode: str) -> str:
        mode = (mode or "separate").lower().strip()
        for key, ar, en in SUBTITLE_MODE_OPTIONS:
            if key == mode or mode in (ar.lower(), en.lower(), self.t(ar, en).lower()):
                return self.t(ar, en)
        return self._subtitle_mode_display_values()[0]

    def _subtitle_mode_from_display(self, display: str) -> str:
        if not display:
            return "separate"
        raw = str(display).strip()
        low = raw.lower()
        if low in ("separate", "embed", "burn", "both"):
            return low
        for key, ar, en in SUBTITLE_MODE_OPTIONS:
            if raw in (ar, en, self.t(ar, en)):
                return key
        if "srt + mkv" in low or "both" in low:
            return "both"
        if "burn" in low or "mp4" in low or "حرق" in raw:
            return "burn"
        if "embed" in low or "mkv" in low or "مدمج" in raw:
            return "embed"
        return "separate"

    # ------------------------------------------------------------------
    # Application shell (Top Bar & Left Sidebar)
    # ------------------------------------------------------------------
    def setup_sidebar(self):
        """Build the top bar and the left task rail (called by VeyoraApp)."""
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self.top = ctk.CTkFrame(self, fg_color=self.c["bg"], corner_radius=0, height=74)
        self.top.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.top.grid_columnconfigure(2, weight=1)

        brand = ctk.CTkFrame(self.top, fg_color="transparent")
        brand.grid(row=0, column=0, padx=(18, 22), pady=10, sticky="w")
        try:
            logo = Image.open(Path(__file__).with_name("logo.png"))
            self.brand_image = ctk.CTkImage(logo, size=(46, 46))
            ctk.CTkLabel(brand, text="", image=self.brand_image).grid(row=0, column=0, rowspan=2, padx=(0, 10))
        except Exception:
            pass
        title_row = ctk.CTkFrame(brand, fg_color="transparent")
        title_row.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            title_row,
            text="Veyora Pro",
            font=("Segoe UI", 18, "bold"),
            text_color=self.c["text"],
        ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            title_row,
            text=" 4K ",
            font=("Segoe UI", 10, "bold"),
            fg_color=self.c["warn_bg"],
            text_color=self.c["warn"],
            corner_radius=5,
        ).pack(side="left")
        ctk.CTkLabel(
            brand,
            text="Downloader & Translator",
            font=("Segoe UI", 11),
            text_color=self.c["muted"],
        ).grid(row=1, column=1, sticky="w")

        self._nav_buttons = {}
        nav = ctk.CTkFrame(self.top, fg_color="transparent")
        nav.grid(row=0, column=1, sticky="w")
        items = [
            ("Dashboard", "⌂", "الرئيسية", "Home"),
            ("Downloads", "⇩", "التنزيلات", "Downloads"),
            ("Translation", "▣", "الترجمة", "Translation"),
            ("Settings", "⚙", "الإعدادات", "Settings"),
        ]
        for col, (name, symbol, ar, en) in enumerate(items):
            button = self.ghost_button(
                nav,
                f"{symbol}  {self.t(ar, en)}",
                lambda n=name: self.show_tab(n),
                width=120,
                height=38,
                corner_radius=11,
                font=("Segoe UI", 12, "bold"),
            )
            button.grid(row=0, column=col, padx=4)
            self._nav_buttons[name] = button

        right = ctk.CTkFrame(self.top, fg_color="transparent")
        right.grid(row=0, column=3, padx=(10, 18), pady=10, sticky="e")
        self.version_badge = ctk.CTkLabel(
            right,
            text="v1.7.0 → v" + APP_VERSION,
            fg_color=self.c["chip"],
            text_color=self.c["muted"],
            corner_radius=14,
            width=110,
            height=34,
            font=("Segoe UI", 11, "bold"),
        )
        self.version_badge.grid(row=0, column=0, padx=(0, 8))

        self.update_chip = self.button(
            right,
            f"v{APP_VERSION} " + self.t("يتوفر تحديث جديد", "Check updates"),
            lambda: getattr(self, "updater", None) and self.updater.check(True),
            fg_color=self.c["blue"],
            hover_color=self.c["blue_hover"],
            text_color="#ffffff",
            corner_radius=17,
            width=186,
            height=34,
            font=("Segoe UI", 11, "bold"),
        )
        self.update_chip.grid(row=0, column=1, padx=(0, 8))

        self.ghost_button(
            right,
            self.t("العربية / EN", "EN / العربية"),
            self.toggle_language,
            border_width=1,
            border_color=self.c["edge"],
            corner_radius=14,
            width=106,
            height=34,
            font=("Segoe UI", 11),
        ).grid(row=0, column=2)

        self.sidebar = ctk.CTkFrame(self, width=230, fg_color=self.c["bg"], corner_radius=0)
        self.sidebar.grid(row=1, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(10, weight=1)

        rail = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        rail.grid(row=0, column=0, padx=12, pady=(4, 0), sticky="ew")
        rail.grid_columnconfigure(0, weight=1)
        links = [
            ("video", "⇩", "تحميل فيديو", "Video download", lambda: self.home_mode(False)),
            ("audio", "♫", "تحميل الصوت", "Audio download", lambda: self.home_mode(True)),
            ("playlists", "☷", "قائمة التشغيل", "Playlists", lambda: self.home_mode(False)),
            ("translation", "▣", "الترجمة", "Translation", lambda: self.show_tab("Translation")),
            ("convert", "⇄", "التحويل والصيغ", "Convert & formats", lambda: self.show_tab("Convert")),
            ("files", "▱", "الملفات", "Files", self.open_selected_folder),
            ("divider", "", "", "", None),
            ("settings", "⚙", "الإعدادات", "Settings", lambda: self.show_tab("Settings")),
            ("history", "◷", "السجل", "History", lambda: self.show_tab("History")),
            ("support", "?", "الدعم", "Support & sites", self.show_supported_sites),
        ]
        self._sidebar_buttons = {}
        for row, (key, symbol, ar, en, command) in enumerate(links):
            if key == "divider":
                sep = ctk.CTkFrame(rail, height=1, fg_color=self.c["edge"])
                sep.grid(row=row, column=0, padx=8, pady=8, sticky="ew")
                continue
            button = self.button(
                rail,
                f"{symbol}   {self.t(ar, en)}",
                command,
                fg_color="transparent",
                hover_color=self.c["blue_soft"],
                text_color=self.c["muted"],
                anchor="w",
                width=204,
                height=40,
                corner_radius=10,
                font=("Segoe UI", 13),
            )
            button.grid(row=row, column=0, pady=2, sticky="ew")
            self._sidebar_buttons[key] = button

        promo = ctk.CTkFrame(
            self.sidebar,
            fg_color="#121720" if not self.settings.get("theme") == "Light" else self.c["panel2"],
            border_width=1,
            border_color="#5c451c",
            corner_radius=14,
        )
        promo.grid(row=11, column=0, padx=14, pady=(8, 14), sticky="ew")
        promo.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            promo,
            text="♛",
            font=("Segoe UI", 22, "bold"),
            text_color=self.c["warn"],
        ).grid(row=0, column=0, pady=(10, 0))
        ctk.CTkLabel(
            promo,
            text="Veyora Pro",
            font=("Segoe UI", 14, "bold"),
            text_color=self.c["warn"],
        ).grid(row=1, column=0)
        ctk.CTkLabel(
            promo,
            text=self.t("مجاني دائمًا", "Always free"),
            font=("Segoe UI", 12, "bold"),
            text_color=self.c["text"],
        ).grid(row=2, column=0, pady=(2, 2))
        ctk.CTkLabel(
            promo,
            text=self.t("الدعم التطوير ❤", "Support development ❤"),
            font=("Segoe UI", 11),
            text_color=self.c["bad"],
        ).grid(row=3, column=0, pady=(0, 10))

    def setup_main_content(self):
        self.content_frame = ctk.CTkFrame(
            self,
            fg_color=self.c["bg_soft"],
            border_width=1,
            border_color=self.c["edge"],
            corner_radius=16,
        )
        self.content_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 12), pady=(0, 10))
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

    def toggle_language(self):
        previous = getattr(self, "active_tab", "Dashboard")
        self.settings["ui_language"] = "en" if self.is_arabic else "ar"
        SettingsManager.save(self.settings)
        for widget in (getattr(self, "top", None), getattr(self, "sidebar", None)):
            if widget is not None:
                widget.destroy()
        for child in list(self.content_frame.winfo_children()):
            child.destroy()
        self.setup_sidebar()
        self.setup_main_content()
        self.show_tab(previous if previous in ("Dashboard", "Downloads", "History", "Settings", "Translation", "Convert") else "Dashboard")

    def _set_active_nav(self, name):
        mapping = {
            "Dashboard": ("video", "Dashboard"),
            "Downloads": ("video", "Downloads"),
            "Translation": ("translation", "Translation"),
            "Convert": ("convert", "Translation"),
            "History": ("history", "History"),
            "Settings": ("settings", "Settings"),
        }
        active = mapping.get(name, ("", ""))
        for key, button in getattr(self, "_sidebar_buttons", {}).items():
            if not button.winfo_exists():
                continue
            selected = key == active[0]
            button.configure(
                fg_color=self.c["blue_soft"] if selected else "transparent",
                text_color=self.c["text"] if selected else self.c["muted"],
            )
        for key, button in getattr(self, "_nav_buttons", {}).items():
            if not button.winfo_exists():
                continue
            selected = key == active[1]
            button.configure(
                fg_color=self.c["blue_soft"] if selected else "transparent",
                text_color=self.c["text"] if selected else self.c["muted"],
                border_width=1 if selected else 0,
                border_color=self.c["blue"] if selected else self.c["edge"],
            )

    def home_mode(self, audio):
        self.show_tab("Dashboard")
        self.set_mode("Audio (Extract)" if audio else "Video")
        self._set_active_nav("Dashboard")
        if audio and "audio" in getattr(self, "_sidebar_buttons", {}):
            for k, btn in self._sidebar_buttons.items():
                if btn.winfo_exists():
                    btn.configure(
                        fg_color=self.c["blue_soft"] if k == "audio" else "transparent",
                        text_color=self.c["text"] if k == "audio" else self.c["muted"],
                    )

    def show_tab(self, name):
        self.active_tab = name
        self._set_active_nav(name)
        if name in ("Translation", "Convert"):
            for widget in self.content_frame.winfo_children():
                widget.destroy()
            self.clear_download_caches()
            self.build_local_tab(convert=name == "Convert")
            return
        self.clear_download_caches()
        super().show_tab(name)
        self._set_active_nav(name)

    def set_mode(self, mode):
        if hasattr(self, "mode_var"):
            self.mode_var.set(mode)
        for key, button in getattr(self, "mode_buttons", {}).items():
            if not button.winfo_exists():
                continue
            selected = key == mode
            button.configure(
                fg_color=self.c["blue"] if selected else "transparent",
                text_color="#ffffff" if selected else self.c["muted"],
            )
        if hasattr(self, "extract_audio_switch") and self.extract_audio_switch.winfo_exists():
            if mode == "Audio (Extract)":
                self.extract_audio_switch.select()
            else:
                self.extract_audio_switch.deselect()
        self.on_mode_change()

    def on_mode_change(self, value=None):
        if not hasattr(self, "mode_var"):
            return
        audio = self.mode_var.get() == "Audio (Extract)"
        for widget in (getattr(self, "audio_options", None), getattr(self, "video_options", None)):
            if widget is not None and widget.winfo_exists():
                if widget is getattr(self, "audio_options", None):
                    widget.grid() if audio else widget.grid_remove()
        if hasattr(self, "audio_format_frame") and self.audio_format_frame.winfo_exists():
            self.audio_format_frame.grid() if audio else self.audio_format_frame.grid_remove()

    def clear_download_caches(self):
        for cache in (
            self.card_widgets,
            self._card_buttons,
            self._card_snapshots,
            self._card_progress_bars,
            self._card_info_labels,
            self._card_title_labels,
            getattr(self, "_card_percent_labels", {}),
            getattr(self, "_card_status_labels", {}),
        ):
            cache.clear()

    # ------------------------------------------------------------------
    # Dashboard (Matches Veyora Pro 2.0 Reference Design)
    # ------------------------------------------------------------------
    def build_dashboard_tab(self):
        self._layout_narrow = None
        # Direct deterministic 5-row container inside content_frame so no nested
        # scrollable frame ever collapses or hides the option cards on Windows.
        dashboard = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        dashboard.grid(row=0, column=0, sticky="nsew", padx=12, pady=(8, 4))
        dashboard.grid_columnconfigure(0, weight=1)
        dashboard.grid_rowconfigure(0, weight=0)  # URL Bar
        dashboard.grid_rowconfigure(1, weight=0)  # Preview & Video Info Row
        dashboard.grid_rowconfigure(2, weight=0)  # 3-Column Options Row
        dashboard.grid_rowconfigure(3, weight=1)  # Download Queue Panel
        self._dashboard_scroll = dashboard

        self._build_url_row(dashboard)
        self._build_preview(dashboard)
        self._build_options(dashboard)
        self._build_queue(dashboard)
        self._build_status_strip()

    def _build_url_row(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 6))
        row.grid_columnconfigure(0, weight=1)

        url_box = ctk.CTkFrame(
            row,
            fg_color=self.c["panel"],
            border_color=self.c["blue"],
            border_width=1,
            corner_radius=12,
            height=50,
        )
        url_box.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        url_box.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            url_box,
            text="",
            image=self.icons["link"],
            width=30,
        ).grid(row=0, column=0, padx=(12, 4), pady=8)

        self.url_entry = ctk.CTkEntry(
            url_box,
            placeholder_text="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            height=42,
            border_width=0,
            fg_color="transparent",
            text_color=self.c["text"],
            placeholder_text_color=self.c["muted"],
            font=("Segoe UI", 14),
        )
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.url_entry.bind("<Button-3>", self.show_url_context_menu)

        self.ghost_button(
            url_box,
            "×",
            lambda: self.url_entry.delete(0, "end"),
            fg_color=self.c["panel2"],
            hover_color=self.c["edge"],
            text_color=self.c["muted"],
            corner_radius=13,
            width=26,
            height=26,
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=2, padx=(4, 6), pady=8)

        self.ghost_button(
            url_box,
            "📋  " + self.t("لصق", "Paste"),
            self.paste_only,
            fg_color=self.c["panel2"],
            hover_color=self.c["blue_soft"],
            border_width=1,
            border_color=self.c["edge"],
            corner_radius=9,
            width=86,
            height=36,
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=3, padx=(0, 8), pady=6)

        self.button(
            row,
            "🔍  " + self.t("تحليل الرابط", "Analyze link"),
            self.analyze,
            width=164,
            height=50,
            corner_radius=12,
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=1)

    def _build_preview(self, parent):
        preview_row = ctk.CTkFrame(parent, fg_color="transparent")
        preview_row.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 8))
        preview_row.grid_columnconfigure(0, weight=3)
        preview_row.grid_columnconfigure(1, weight=2)

        # Left/Center Preview Card (Thumbnail + Title/Channel/Views/Badges)
        left_card = self.card(preview_row, fg_color=self.c["bg_soft"])
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_card.grid_columnconfigure(1, weight=1)

        scenic = _make_scenic_preview(236, 132, "12:34")
        self._default_preview_ctk = ctk.CTkImage(scenic, size=(236, 132))
        self.preview_image = ctk.CTkLabel(
            left_card,
            text="",
            image=self._default_preview_ctk,
            width=236,
            height=132,
            fg_color=self.c["panel2"],
            corner_radius=12,
        )
        self.preview_image.grid(row=0, column=0, rowspan=4, padx=12, pady=10, sticky="w")

        details = ctk.CTkFrame(left_card, fg_color="transparent")
        details.grid(row=0, column=1, rowspan=4, sticky="nsew", padx=(6, 14), pady=12)
        details.grid_columnconfigure(0, weight=1)

        self.preview_title = ctk.CTkLabel(
            details,
            text="Beautiful Nature in 4K",
            font=("Segoe UI", 18, "bold"),
            text_color=self.c["text"],
            anchor="w",
            justify="left",
            wraplength=460,
        )
        self.preview_title.grid(row=0, column=0, sticky="ew", pady=(2, 2))

        self.preview_channel = ctk.CTkLabel(
            details,
            text="Nature World",
            font=("Segoe UI", 13),
            text_color=self.c["muted"],
            anchor="w",
            justify="left",
        )
        self.preview_channel.grid(row=1, column=0, sticky="ew", pady=(0, 2))

        self.preview_meta = ctk.CTkLabel(
            details,
            text=self.t("12M مشاهدة  •  قبل 3 أسابيع", "12M views  •  3 weeks ago"),
            font=("Segoe UI", 12),
            text_color=self.c["muted"],
            anchor="w",
            justify="left",
            wraplength=460,
        )
        self.preview_meta.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        badges = ctk.CTkFrame(details, fg_color="transparent")
        badges.grid(row=3, column=0, sticky="w")
        self.badge_4k = ctk.CTkLabel(
            badges,
            text="  4K  ",
            font=("Segoe UI", 11, "bold"),
            fg_color=self.c["warn_bg"],
            text_color=self.c["warn"],
            corner_radius=6,
            height=24,
        )
        self.badge_4k.pack(side="left", padx=(0, 6))
        self.badge_hdr = ctk.CTkLabel(
            badges,
            text="  HDR  ",
            font=("Segoe UI", 11, "bold"),
            fg_color=self.c["panel2"],
            text_color=self.c["text"],
            corner_radius=6,
            height=24,
        )
        self.badge_hdr.pack(side="left", padx=(0, 6))
        self.badge_fps = ctk.CTkLabel(
            badges,
            text=" 60 FPS ",
            font=("Segoe UI", 11, "bold"),
            fg_color=self.c["panel2"],
            text_color=self.c["text"],
            corner_radius=6,
            height=24,
        )
        self.badge_fps.pack(side="left")

        # Right Video Information Card (معلومات الفيديو)
        info_card = self.card(preview_row)
        info_card.grid(row=0, column=1, sticky="nsew")
        info_card.grid_columnconfigure(0, weight=1)
        info_card.grid_columnconfigure(1, weight=0)

        ctk.CTkLabel(
            info_card,
            text=self.t("معلومات الفيديو", "Video information"),
            font=("Segoe UI", 14, "bold"),
            text_color=self.c["text"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(10, 4), sticky="ew")

        ctk.CTkFrame(info_card, height=1, fg_color=self.c["edge"]).grid(
            row=1, column=0, columnspan=2, padx=14, pady=(0, 8), sticky="ew"
        )

        meta_list = ctk.CTkFrame(info_card, fg_color="transparent")
        meta_list.grid(row=2, column=0, padx=(16, 8), pady=(0, 10), sticky="nsew")
        meta_list.grid_columnconfigure(1, weight=1)

        self.info_duration_label = ctk.CTkLabel(
            meta_list,
            text="◷   " + self.t("المدة: 12:34", "Duration: 12:34"),
            font=("Segoe UI", 12),
            text_color=self.c["text"],
            anchor="w",
        )
        self.info_duration_label.grid(row=0, column=0, sticky="w", pady=2)

        self.info_platform_label = ctk.CTkLabel(
            meta_list,
            text="▱   YouTube",
            font=("Segoe UI", 12),
            text_color=self.c["text"],
            anchor="w",
        )
        self.info_platform_label.grid(row=1, column=0, sticky="w", pady=2)

        self.info_channel_label = ctk.CTkLabel(
            meta_list,
            text="▣   Nature World",
            font=("Segoe UI", 12),
            text_color=self.c["muted"],
            anchor="w",
        )
        self.info_channel_label.grid(row=2, column=0, sticky="w", pady=2)

        # Keep self.video_info synced for backwards compatibility with any caller/test
        self.video_info = self.info_platform_label

        mini_scenic = _make_scenic_preview(108, 68, "")
        self._mini_preview_ctk = ctk.CTkImage(mini_scenic, size=(108, 68))
        self.info_thumb_label = ctk.CTkLabel(
            info_card,
            text="",
            image=self._mini_preview_ctk,
            width=108,
            height=68,
            fg_color=self.c["panel2"],
            corner_radius=8,
        )
        self.info_thumb_label.grid(row=2, column=1, padx=(4, 14), pady=(0, 10), sticky="e")

    def _build_options(self, parent):
        options = ctk.CTkFrame(parent, fg_color="transparent")
        options.grid(row=2, column=0, sticky="ew", padx=0, pady=(0, 8))
        self.options_frame = options
        for column in range(3):
            options.grid_columnconfigure(column, weight=1, uniform="option")

        self.download_card = self.card(options)
        self.download_card.grid(row=0, column=0, sticky="nsew", padx=(4, 6))
        self.translation_card = self.card(options)
        self.translation_card.grid(row=0, column=1, sticky="nsew", padx=6)
        self.more_card = self.card(options)
        self.more_card.grid(row=0, column=2, sticky="nsew", padx=(6, 4))

        self._build_download_card()
        self._build_translation_card()
        self._build_more_card()

    def _build_download_card(self):
        card = self.download_card
        card.grid_columnconfigure(0, weight=0)
        card.grid_columnconfigure(1, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, columnspan=2, padx=14, pady=(10, 4), sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            hdr,
            text=" A ",
            font=("Segoe UI", 11, "bold"),
            fg_color=self.c["blue"],
            text_color="#ffffff",
            corner_radius=5,
            width=22,
            height=22,
        ).grid(row=0, column=0, padx=(0, 8))
        self.section_title(hdr, "خيارات التحميل", "Download options").grid(
            row=0, column=1, sticky="w"
        )

        self.mode_var = ctk.StringVar(value="Video")
        modes = ctk.CTkFrame(hdr, fg_color=self.c["bg_soft"], corner_radius=8)
        modes.grid(row=0, column=2, sticky="e")
        self.mode_buttons = {}
        for column, (value, ar, en) in enumerate(
            (("Video", "فيديو", "Video"), ("Audio (Extract)", "صوت", "Audio"))
        ):
            button = self.ghost_button(
                modes,
                self.t(ar, en),
                lambda v=value: self.set_mode(v),
                fg_color=self.c["blue"] if value == "Video" else "transparent",
                text_color="#ffffff" if value == "Video" else self.c["muted"],
                width=54,
                height=26,
                corner_radius=6,
                font=("Segoe UI", 11),
            )
            button.grid(row=0, column=column, padx=2, pady=2)
            self.mode_buttons[value] = button

        ctk.CTkFrame(card, height=1, fg_color=self.c["edge"]).grid(
            row=1, column=0, columnspan=2, padx=14, pady=(2, 8), sticky="ew"
        )

        # Row 2: Quality
        ctk.CTkLabel(
            card,
            text=self.t("الجودة:", "Quality:"),
            text_color=self.c["muted"],
            font=("Segoe UI", 12),
            anchor="w",
        ).grid(row=2, column=0, padx=(14, 8), pady=5, sticky="w")
        saved_q = self.settings.get("quality", "Best Available (4K/HD)")
        self.quality_var = ctk.StringVar(value=saved_q)
        self.quality_display_var = ctk.StringVar(value=self._quality_to_display(saved_q))
        self.quality_menu = ctk.CTkOptionMenu(
            card,
            values=self._quality_display_values(),
            variable=self.quality_display_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            button_hover_color=self.c["blue"],
            dropdown_fg_color=self.c["panel"],
            dropdown_text_color=self.c["text"],
            text_color=self.c["text"],
            height=34,
            font=("Segoe UI", 12),
            command=self._on_quality_selected,
            dynamic_resizing=False,
        )
        self.quality_menu.grid(row=2, column=1, padx=(0, 14), pady=5, sticky="ew")

        # Row 3: Format
        ctk.CTkLabel(
            card,
            text=self.t("الصيغة:", "Format:"),
            text_color=self.c["muted"],
            font=("Segoe UI", 12),
            anchor="w",
        ).grid(row=3, column=0, padx=(14, 8), pady=5, sticky="w")
        saved_fmt = self.settings.get("format", "MP4")
        self.format_var = ctk.StringVar(value=saved_fmt)
        self.format_display_var = ctk.StringVar(value=self._format_to_display(saved_fmt))
        self.format_menu = ctk.CTkOptionMenu(
            card,
            values=self._format_display_values(),
            variable=self.format_display_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            button_hover_color=self.c["blue"],
            dropdown_fg_color=self.c["panel"],
            dropdown_text_color=self.c["text"],
            text_color=self.c["text"],
            height=34,
            font=("Segoe UI", 12),
            command=self._on_format_selected,
            dynamic_resizing=False,
        )
        self.format_menu.grid(row=3, column=1, padx=(0, 14), pady=5, sticky="ew")

        # Row 4: Save Location
        ctk.CTkLabel(
            card,
            text=self.t("مكان الحفظ:", "Save path:"),
            text_color=self.c["muted"],
            font=("Segoe UI", 12),
            anchor="w",
        ).grid(row=4, column=0, padx=(14, 8), pady=5, sticky="w")

        folder_box = ctk.CTkFrame(
            card,
            fg_color=self.c["panel2"],
            border_width=1,
            border_color=self.c["edge"],
            corner_radius=8,
            height=34,
        )
        folder_box.grid(row=4, column=1, padx=(0, 14), pady=5, sticky="ew")
        folder_box.grid_columnconfigure(0, weight=1)

        self.folder_path_label = ctk.CTkLabel(
            folder_box,
            text=self.selected_folder,
            anchor="w",
            justify="left",
            text_color=self.c["text"],
            font=("Segoe UI", 11),
        )
        self.folder_path_label.grid(row=0, column=0, padx=(10, 4), pady=4, sticky="ew")

        self.ghost_button(
            folder_box,
            "▱",
            self.browse_folder,
            fg_color=self.c["blue_soft"],
            hover_color=self.c["blue"],
            corner_radius=6,
            width=34,
            height=28,
        ).grid(row=0, column=1, padx=3, pady=3)

        # Row 5-7: Checkboxes matching reference UI
        checks_frame = ctk.CTkFrame(card, fg_color="transparent")
        checks_frame.grid(row=5, column=0, columnspan=2, padx=14, pady=(6, 10), sticky="ew")
        checks_frame.grid_columnconfigure(0, weight=1)

        self.thumb_var = ctk.BooleanVar(value=self.settings.get("save_thumbnail", True))
        self._check(checks_frame, 0, self.t("تحميل الصورة المصغرة", "Download thumbnail"), self.thumb_var)

        self.desc_var = ctk.BooleanVar(value=self.settings.get("save_description_ui", True))
        self._check(checks_frame, 1, self.t("تحميل الوصف", "Download description"), self.desc_var)

        self.split_var = ctk.BooleanVar(value=self.settings.get("auto_split_clips_ui", True))
        self._check(checks_frame, 2, self.t("تقسيم تلقائي للمقاطع الطويلة", "Auto-split long videos"), self.split_var)

        self.video_options = ctk.CTkFrame(card, fg_color="transparent", height=1)
        self.video_options.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.audio_options = ctk.CTkFrame(card, fg_color="transparent", height=1)
        self.audio_options.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.audio_options.grid_remove()

    def _build_translation_card(self):
        card = self.translation_card
        card.grid_columnconfigure(0, weight=0)
        card.grid_columnconfigure(1, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, columnspan=2, padx=14, pady=(10, 4), sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            hdr,
            text=" A ",
            font=("Segoe UI", 11, "bold"),
            fg_color=self.c["blue"],
            text_color="#ffffff",
            corner_radius=5,
            width=22,
            height=22,
        ).grid(row=0, column=0, padx=(0, 8))
        self.section_title(hdr, "الترجمة", "Translation").grid(
            row=0, column=1, sticky="w"
        )

        self.sub_var = ctk.BooleanVar(value=self.settings.get("download_subs", True))
        self.sub_switch = ctk.CTkSwitch(
            hdr,
            text="",
            variable=self.sub_var,
            progress_color=self.c["blue"],
            button_color="#ffffff",
            width=44,
            command=self._update_translation_hint,
        )
        self.sub_switch.grid(row=0, column=2, sticky="e")

        ctk.CTkFrame(card, height=1, fg_color=self.c["edge"]).grid(
            row=1, column=0, columnspan=2, padx=14, pady=(2, 8), sticky="ew"
        )

        saved_sub_key = self.settings.get("sub_lang", "detect-ar")
        source, target = language_from_key(saved_sub_key)
        # In the 2.0 UI, default source language in the dropdown is auto-detect if saved_sub_key is default
        if saved_sub_key in ("auto-ar", "detect-ar") and "sub_lang_explicit" not in self.settings:
            source = "auto"

        src_labels = self._source_labels()
        tgt_labels = self._target_labels()
        self.source_var = ctk.StringVar(value=self._label_for_lang(source, allow_auto=True))
        self.target_var = ctk.StringVar(value=self._label_for_lang(target, allow_auto=False))

        # Row 2: Video language (لغة الفيديو)
        ctk.CTkLabel(
            card,
            text=self.t("لغة الفيديو:", "Video language:"),
            text_color=self.c["muted"],
            font=("Segoe UI", 12),
            anchor="w",
        ).grid(row=2, column=0, padx=(14, 8), pady=5, sticky="w")
        self.source_menu = ctk.CTkOptionMenu(
            card,
            values=src_labels,
            variable=self.source_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            button_hover_color=self.c["blue"],
            dropdown_fg_color=self.c["panel"],
            dropdown_text_color=self.c["text"],
            text_color=self.c["text"],
            height=34,
            font=("Segoe UI", 12),
            command=lambda _value: self._update_translation_hint(),
            dynamic_resizing=False,
        )
        self.source_menu.grid(row=2, column=1, padx=(0, 14), pady=5, sticky="ew")

        # Row 3: Translate to (ترجمة إلى)
        ctk.CTkLabel(
            card,
            text=self.t("ترجمة إلى:", "Translate to:"),
            text_color=self.c["muted"],
            font=("Segoe UI", 12),
            anchor="w",
        ).grid(row=3, column=0, padx=(14, 8), pady=5, sticky="w")
        self.target_menu = ctk.CTkOptionMenu(
            card,
            values=tgt_labels,
            variable=self.target_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            button_hover_color=self.c["blue"],
            dropdown_fg_color=self.c["panel"],
            dropdown_text_color=self.c["text"],
            text_color=self.c["text"],
            height=34,
            font=("Segoe UI", 12),
            command=lambda _value: self._update_translation_hint(),
            dynamic_resizing=False,
        )
        self.target_menu.grid(row=3, column=1, padx=(0, 14), pady=5, sticky="ew")

        # Row 4: Save method (طريقة الحفظ)
        ctk.CTkLabel(
            card,
            text=self.t("طريقة الحفظ:", "Save method:"),
            text_color=self.c["muted"],
            font=("Segoe UI", 12),
            anchor="w",
        ).grid(row=4, column=0, padx=(14, 8), pady=5, sticky="w")
        saved_mode = self.settings.get("subtitle_mode", "separate")
        self.dashboard_subtitle_mode = ctk.StringVar(value=saved_mode)
        self.subtitle_mode_display_var = ctk.StringVar(value=self._subtitle_mode_to_display(saved_mode))
        self.subtitle_mode_menu = ctk.CTkOptionMenu(
            card,
            values=self._subtitle_mode_display_values(),
            variable=self.subtitle_mode_display_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            button_hover_color=self.c["blue"],
            dropdown_fg_color=self.c["panel"],
            dropdown_text_color=self.c["text"],
            text_color=self.c["text"],
            height=34,
            font=("Segoe UI", 12),
            command=self._on_subtitle_mode_selected,
            dynamic_resizing=False,
        )
        self.subtitle_mode_menu.grid(row=4, column=1, padx=(0, 14), pady=5, sticky="ew")

        # Row 5: Hint label
        self.translation_hint = ctk.CTkLabel(
            card,
            text="",
            text_color=self.c["muted"],
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
        )
        self.translation_hint.grid(row=5, column=0, columnspan=2, padx=14, pady=(2, 2), sticky="ew")

        # Row 6: Bottom actions & Include original text checkbox
        bottom = ctk.CTkFrame(card, fg_color="transparent")
        bottom.grid(row=6, column=0, columnspan=2, padx=12, pady=(2, 10), sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)

        links_col = ctk.CTkFrame(bottom, fg_color="transparent")
        links_col.grid(row=0, column=0, sticky="w")
        self.ghost_button(
            links_col,
            "⚙ " + self.t("الإعدادات المتقدمة", "Advanced settings"),
            self.show_advanced,
            text_color=self.c["blue"],
            hover_color=self.c["panel2"],
            height=26,
            font=("Segoe UI", 11),
        ).grid(row=0, column=0, sticky="w")
        self.ghost_button(
            links_col,
            "↻ " + self.t("تحسين الدقة", "Enhance accuracy"),
            self._cycle_speech_accuracy,
            text_color=self.c["blue"],
            hover_color=self.c["panel2"],
            height=26,
            font=("Segoe UI", 11),
        ).grid(row=1, column=0, sticky="w")

        self.original_var = ctk.BooleanVar(value=self.settings.get("save_original_subtitles_ui", True))
        ctk.CTkCheckBox(
            bottom,
            text=self.t("تضمين النص الأصلي أيضاً", "Include original text"),
            variable=self.original_var,
            fg_color=self.c["blue"],
            hover_color=self.c["blue_hover"],
            border_color=self.c["edge"],
            text_color=self.c["text"],
            font=("Segoe UI", 11),
            checkbox_width=18,
            checkbox_height=18,
        ).grid(row=0, column=1, rowspan=2, padx=(4, 2), sticky="e")

        self._update_translation_hint()

    def _build_more_card(self):
        card = self.more_card
        card.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="ew")
        ctk.CTkLabel(
            hdr,
            text="",
            image=self.icons["settings"],
            width=22,
        ).pack(side="left", padx=(0, 6))
        self.section_title(hdr, "خيارات إضافية", "Extra options").pack(side="left")

        ctk.CTkFrame(card, height=1, fg_color=self.c["edge"]).grid(
            row=1, column=0, padx=14, pady=(2, 6), sticky="ew"
        )

        self.audio_bitrate_var = ctk.StringVar(value=self.settings.get("audio_bitrate", "320 kbps"))

        toggles = ctk.CTkFrame(card, fg_color="transparent")
        toggles.grid(row=2, column=0, padx=14, pady=0, sticky="ew")
        toggles.grid_columnconfigure(0, weight=1)

        # Toggle 1: Extract audio only (MP3)
        self.extract_audio_var = ctk.BooleanVar(value=self.settings.get("extract_audio", False))
        self.extract_audio_switch = self._switch_row(
            toggles,
            0,
            "♫  " + self.t("استخراج الصوت فقط (MP3)", "Extract audio only (MP3)"),
            self.extract_audio_var,
            self._on_extract_audio_toggle,
        )

        # Toggle 2: Burn subtitles on video (MP4)
        self.burn_sub_var = ctk.BooleanVar(value=self.settings.get("subtitle_mode") == "burn")
        self.burn_sub_switch = self._switch_row(
            toggles,
            1,
            "⇩  " + self.t("حرق الترجمة على الفيديو (MP4)", "Burn subtitles into video (MP4)"),
            self.burn_sub_var,
            self._on_burn_sub_toggle,
        )

        # Toggle 3: Save as MKV file
        self.mkv_save_var = ctk.BooleanVar(value=self.settings.get("format") == "MKV" or self.settings.get("subtitle_mode") == "embed")
        self.mkv_save_switch = self._switch_row(
            toggles,
            2,
            "▱  " + self.t("حفظ كملف (MKV)", "Save as container (MKV)"),
            self.mkv_save_var,
            self._on_mkv_save_toggle,
        )

        # Toggle 4: Clip part of video
        self.clip_var = ctk.BooleanVar(value=self.settings.get("clip_enabled", False))
        self.clip_switch = self._switch_row(
            toggles,
            3,
            "✂  " + self.t("قص جزء من الفيديو", "Clip video segment"),
            self.clip_var,
            None,
        )

        # Keep smart_mode_switch attribute available for tests/callers
        self.smart_mode_switch = ctk.CTkSwitch(
            toggles,
            text=self.t("تحميل بنقرة واحدة", "One-click download"),
            command=self.toggle_smart_mode,
            progress_color=self.c["blue"],
            button_color="#ffffff",
            text_color=self.c["text"],
            font=("Segoe UI", 11),
        )
        if self.smart_mode:
            self.smart_mode_switch.select()

        # Time range inputs (00:00:00 to 00:12:34)
        clip_row = ctk.CTkFrame(card, fg_color="transparent")
        clip_row.grid(row=3, column=0, padx=14, pady=(4, 6), sticky="ew")
        clip_row.grid_columnconfigure((0, 2), weight=1)

        self.clip_start_var = ctk.StringVar(value=self.settings.get("clip_start", "00:00:00"))
        self.clip_start_entry = ctk.CTkEntry(
            clip_row,
            textvariable=self.clip_start_var,
            height=30,
            fg_color=self.c["panel2"],
            border_color=self.c["edge"],
            text_color=self.c["text"],
            justify="center",
            font=("Segoe UI", 11),
        )
        self.clip_start_entry.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(
            clip_row,
            text=self.t("إلى:", "to:"),
            text_color=self.c["muted"],
            font=("Segoe UI", 11),
        ).grid(row=0, column=1, padx=8)

        self.clip_end_var = ctk.StringVar(value=self.settings.get("clip_end", "00:12:34"))
        self.clip_end_entry = ctk.CTkEntry(
            clip_row,
            textvariable=self.clip_end_var,
            height=30,
            fg_color=self.c["panel2"],
            border_color=self.c["edge"],
            text_color=self.c["text"],
            justify="center",
            font=("Segoe UI", 11),
        )
        self.clip_end_entry.grid(row=0, column=2, sticky="ew")

        # Primary CTA button
        self.button(
            card,
            "⇩  " + self.t("بدء التحميل والترجمة", "Start download & translation"),
            self.start_download_action,
            height=42,
            corner_radius=10,
            font=("Segoe UI", 14, "bold"),
        ).grid(row=4, column=0, padx=14, pady=(4, 10), sticky="ew")

    def _switch_row(self, parent, row, text, variable, command):
        line = ctk.CTkFrame(parent, fg_color="transparent")
        line.grid(row=row, column=0, pady=2, sticky="ew")
        line.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            line,
            text=text,
            text_color=self.c["text"],
            font=("Segoe UI", 11),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        sw = ctk.CTkSwitch(
            line,
            text="",
            variable=variable,
            command=command,
            progress_color=self.c["blue"],
            button_color="#ffffff",
            width=40,
            height=20,
        )
        sw.grid(row=0, column=1, sticky="e")
        return sw

    def _on_quality_selected(self, value=None):
        code = self._quality_from_display(self.quality_display_var.get())
        self.quality_var.set(code)
        self.settings["quality"] = code

    def _on_format_selected(self, value=None):
        if self._syncing_controls:
            return
        self._syncing_controls = True
        try:
            code = self._format_from_display(self.format_display_var.get())
            self.format_var.set(code)
            self.settings["format"] = code
            if hasattr(self, "mkv_save_var"):
                self.mkv_save_var.set(code == "MKV" or self.dashboard_subtitle_mode.get() == "embed")
        finally:
            self._syncing_controls = False

    def _on_subtitle_mode_selected(self, value=None):
        if self._syncing_controls:
            return
        self._syncing_controls = True
        try:
            mode = self._subtitle_mode_from_display(self.subtitle_mode_display_var.get())
            self.dashboard_subtitle_mode.set(mode)
            self.settings["subtitle_mode"] = mode
            if hasattr(self, "burn_sub_var"):
                self.burn_sub_var.set(mode == "burn")
            if hasattr(self, "mkv_save_var"):
                self.mkv_save_var.set(mode == "embed" or self.format_var.get() == "MKV")
        finally:
            self._syncing_controls = False

    def _on_extract_audio_toggle(self):
        if self._syncing_controls:
            return
        self._syncing_controls = True
        try:
            audio = bool(self.extract_audio_var.get())
            self.set_mode("Audio (Extract)" if audio else "Video")
        finally:
            self._syncing_controls = False

    def _on_burn_sub_toggle(self):
        if self._syncing_controls:
            return
        self._syncing_controls = True
        try:
            mode = "burn" if self.burn_sub_var.get() else "separate"
            self.dashboard_subtitle_mode.set(mode)
            if hasattr(self, "subtitle_mode_display_var"):
                self.subtitle_mode_display_var.set(self._subtitle_mode_to_display(mode))
            if mode == "burn" and hasattr(self, "mkv_save_var"):
                self.mkv_save_var.set(False)
        finally:
            self._syncing_controls = False

    def _on_mkv_save_toggle(self):
        if self._syncing_controls:
            return
        self._syncing_controls = True
        try:
            if self.mkv_save_var.get():
                self.format_var.set("MKV")
                if hasattr(self, "format_display_var"):
                    self.format_display_var.set(self._format_to_display("MKV"))
                self.dashboard_subtitle_mode.set("embed")
                if hasattr(self, "subtitle_mode_display_var"):
                    self.subtitle_mode_display_var.set(self._subtitle_mode_to_display("embed"))
                if hasattr(self, "burn_sub_var"):
                    self.burn_sub_var.set(False)
            else:
                self.format_var.set("MP4")
                if hasattr(self, "format_display_var"):
                    self.format_display_var.set(self._format_to_display("MP4"))
                self.dashboard_subtitle_mode.set("separate")
                if hasattr(self, "subtitle_mode_display_var"):
                    self.subtitle_mode_display_var.set(self._subtitle_mode_to_display("separate"))
        finally:
            self._syncing_controls = False

    def _cycle_speech_accuracy(self):
        order = ["base", "small", "medium"]
        current = self.settings.get("speech_model", "base")
        nxt = order[(order.index(current) + 1) % len(order)] if current in order else "small"
        self.settings["speech_model"] = nxt
        SettingsManager.save(self.settings)
        self._update_translation_hint()

    def _build_queue(self, parent):
        panel = self.card(parent)
        self.queue_panel = panel
        panel.grid(row=3, column=0, sticky="nsew", padx=4, pady=(0, 2))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        header.grid_columnconfigure(1, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_box,
            text="",
            image=self.icons["download"],
            width=22,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            title_box,
            text=self.t("قائمة التنزيلات", "Download queue"),
            font=("Segoe UI", 15, "bold"),
            text_color=self.c["text"],
        ).pack(side="left")

        right_bar = ctk.CTkFrame(header, fg_color="transparent")
        right_bar.grid(row=0, column=2, sticky="e")

        self.ghost_button(
            right_bar,
            "🗑  " + self.t("مسح الكل", "Clear completed"),
            self.clear_completed,
            fg_color=self.c["panel2"],
            border_width=1,
            border_color=self.c["edge"],
            corner_radius=14,
            width=104,
            height=28,
            font=("Segoe UI", 11),
        ).grid(row=0, column=0, padx=(0, 8))

        self.filter_buttons = {}
        filters = ctk.CTkFrame(right_bar, fg_color="transparent")
        filters.grid(row=0, column=1, sticky="e")
        # Order matching reference UI: فاشل | مكتمل | جاري | الكل
        display_filters = list(reversed(FILTERS))
        for column, (value, ar, en) in enumerate(display_filters):
            button = self.ghost_button(
                filters,
                f"{self.t(ar, en)} (0)",
                lambda v=value: self.set_filter(v),
                fg_color=self.c["blue"] if value == self.active_filter else self.c["panel2"],
                text_color="#ffffff" if value == self.active_filter else self.c["muted"],
                border_width=1,
                border_color=self.c["blue"] if value == self.active_filter else self.c["edge"],
                corner_radius=14,
                width=84,
                height=28,
                font=("Segoe UI", 11, "bold" if value == self.active_filter else "normal"),
            )
            button.grid(row=0, column=column, padx=3)
            self.filter_buttons[value] = button

        self.downloads_scroll = ctk.CTkScrollableFrame(
            panel,
            fg_color="transparent",
            height=195,
            scrollbar_button_color=self.c["edge"],
            scrollbar_button_hover_color=self.c["blue"],
        )
        self.downloads_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=(2, 4))
        self.downloads_scroll.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            panel,
            text="",
            text_color=self.c["muted"],
            font=("Segoe UI", 10),
            anchor="w",
        )
        self.status_label.grid(row=2, column=0, padx=14, pady=(0, 4), sticky="ew")
        self.render_download_items()

    def _build_status_strip(self):
        strip = ctk.CTkFrame(self.content_frame, fg_color=self.c["bg"], corner_radius=10, height=32)
        strip.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        strip.grid_columnconfigure(1, weight=1)

        left = ctk.CTkFrame(strip, fg_color="transparent")
        left.grid(row=0, column=0, padx=12, pady=4, sticky="w")
        ctk.CTkLabel(
            left,
            text="●",
            text_color=self.c["good"],
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left", padx=(0, 6))
        self.ready_label = ctk.CTkLabel(
            left,
            text=self.t("جاهز", "Ready"),
            text_color=self.c["text"],
            font=("Segoe UI", 11, "bold"),
        )
        self.ready_label.pack(side="left")

        center = ctk.CTkFrame(strip, fg_color="transparent")
        center.grid(row=0, column=1, pady=4)
        self.speed_label = ctk.CTkLabel(
            center,
            text=self.t("سرعة التحميل: 0.0 MB/s", "Download speed: 0.0 MB/s"),
            text_color=self.c["good"],
            font=("Segoe UI", 11, "bold"),
        )
        self.speed_label.pack(side="left", padx=14)

        self.cpu_label = ctk.CTkLabel(
            center,
            text=self.t("استخدام المعالج: 12%", "CPU usage: 12%"),
            text_color=self.c["blue"],
            font=("Segoe UI", 11, "bold"),
        )
        self.cpu_label.pack(side="left", padx=14)

        self.memory_label = ctk.CTkLabel(
            center,
            text=self.t("استخدام الذاكرة: 128 MB", "Memory: 128 MB"),
            text_color=self.c["text"],
            font=("Segoe UI", 11),
        )
        self.memory_label.pack(side="left", padx=14)

        self.queue_summary_label = ctk.CTkLabel(
            strip,
            text="",
            text_color=self.c["faint"],
            font=("Segoe UI", 10),
        )
        self.queue_summary_label.grid(row=0, column=2, sticky="e", padx=12)

    def _menu(self, parent, row, values, variable):
        menu = ctk.CTkOptionMenu(
            parent,
            values=values,
            variable=variable,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            button_hover_color=self.c["blue"],
            dropdown_fg_color=self.c["panel"],
            dropdown_text_color=self.c["text"],
            text_color=self.c["text"],
            height=34,
            font=("Segoe UI", 11),
            dynamic_resizing=False,
        )
        menu.grid(row=row, column=0, padx=16, pady=(2, 6), sticky="ew")
        return menu

    def _check(self, parent, row, text, variable):
        cb = ctk.CTkCheckBox(
            parent,
            text=text,
            variable=variable,
            fg_color=self.c["blue"],
            hover_color=self.c["blue_hover"],
            border_color=self.c["edge"],
            text_color=self.c["text"],
            font=("Segoe UI", 11),
            checkbox_width=18,
            checkbox_height=18,
        )
        cb.grid(row=row, column=0, pady=3, sticky="w")
        return cb

    def _sync_sub_lang_vars(self):
        """Sync source_var/target_var/sub_var with sub_lang_var and settings['sub_lang']."""
        if not hasattr(self, "source_var") or not hasattr(self, "target_var"):
            return "auto-ar"
        source = self._lang_code(self.source_var.get())
        target = self._lang_code(self.target_var.get())
        if target not in LANGUAGES:
            target = "ar"
        translating = bool(self.sub_var.get()) if hasattr(self, "sub_var") else True
        key = direction_key(source, target, translating=translating)
        display = next(
            (label for label, value in SUBTITLE_CHOICES.items() if value == key),
            key,
        )
        if not hasattr(self, "sub_lang_var") or self.sub_lang_var is None:
            self.sub_lang_var = ctk.StringVar(value=display)
        else:
            self.sub_lang_var.set(display)
        self.settings["sub_lang"] = key
        self.settings["sub_lang_explicit"] = True
        return key

    def _update_translation_hint(self):
        key = self._sync_sub_lang_vars()
        if not hasattr(self, "translation_hint") or not self.translation_hint.winfo_exists():
            return
        speech_model = self.settings.get("speech_model", "base")
        if not self.sub_var.get():
            text = self.t(
                "الترجمة متوقفة. سيُحمَّل الفيديو فقط.",
                "Subtitles are off. Video only.",
            )
        else:
            source = self._lang_code(getattr(self, "source_var", None).get() if hasattr(self, "source_var") else "Auto detect")
            target = self._lang_code(getattr(self, "target_var", None).get() if hasattr(self, "target_var") else "Arabic (ar)")
            if source == target and source in LANGUAGES:
                text = self.t(
                    f"تنزيل الترجمة الأصلية ({source.upper()}) دون ترجمة.",
                    f"Native subtitles ({source.upper()}) without translation.",
                )
            else:
                src_label = "AUTO" if source == "auto" else source.upper()
                tgt_label = target.upper() if target in LANGUAGES else "AR"
                text = self.t(
                    f"الترجمة المحلية النشطة: {src_label} ← {tgt_label}  •  نموذج الدقة: {speech_model}",
                    f"Local translation active: {src_label} → {tgt_label}  •  Model: {speech_model}",
                )
        self.translation_hint.configure(text=text)

    # ------------------------------------------------------------------
    # Dashboard actions
    # ------------------------------------------------------------------
    def paste_only(self):
        try:
            text = self.clipboard_get()
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, text)
        except Exception:
            pass

    def analyze(self):
        url = self.url_entry.get().strip()
        if getattr(self, "_metadata_busy", False):
            return
        if not is_valid_url(url):
            self.notify("أدخل رابط HTTP أو HTTPS صالحًا", "Enter a valid HTTP(S) link", "error")
            return
        self.preview_title.configure(text=self.t("جارٍ تحليل الرابط…", "Analyzing link…"))
        self.preview_meta.configure(text=self.t("يتم جلب البيانات الوصفية…", "Fetching metadata…"))
        self._metadata_busy = True

        def work():
            try:
                info = DownloadEngine.fetch_metadata(normalize_url(url), self.settings.get("cookies_file", ""))
                self._ui_callbacks.put(lambda: self.show_preview(info))
            except Exception as exc:
                error = str(exc)
                self._ui_callbacks.put(lambda: self.show_preview({"error": error}))
            finally:
                self._metadata_busy = False

        threading.Thread(target=work, daemon=True, name="metadata-preview").start()

    def show_preview(self, info):
        if self.active_tab != "Dashboard":
            return
        if not info or info.get("error"):
            self.preview_title.configure(text=self.t("تعذر تحليل الرابط", "Could not analyze the link"))
            self.preview_meta.configure(text=str((info or {}).get("error", ""))[:300])
            self.video_info.configure(text=self.t("لا توجد معلومات متاحة", "No information available"))
            return
        title_str = str(info.get("title", "Video"))
        uploader_str = str(info.get("uploader", "Unknown")).strip() or "Unknown"
        platform_str = str(info.get("platform", "Video")).strip() or "Video"
        duration = int(info.get("duration") or 0)
        minutes, seconds = divmod(duration, 60)
        dur_str = f"{minutes}:{seconds:02d}" if duration else "—"

        self.preview_title.configure(text=title_str)
        if hasattr(self, "preview_channel") and self.preview_channel.winfo_exists():
            self.preview_channel.configure(text=uploader_str)

        views = info.get("view_count")
        meta = []
        if views is not None:
            meta.append(f"{views:,} " + self.t("مشاهدة", "views") if isinstance(views, int) else f"{views} " + self.t("مشاهدة", "views"))
        if duration:
            meta.append(dur_str)
        if platform_str:
            meta.append(platform_str)
        self.preview_meta.configure(text="  •  ".join(part for part in meta if part))

        if hasattr(self, "info_duration_label") and self.info_duration_label.winfo_exists():
            self.info_duration_label.configure(text="◷   " + self.t(f"المدة: {dur_str}", f"Duration: {dur_str}"))
        if hasattr(self, "info_platform_label") and self.info_platform_label.winfo_exists():
            self.info_platform_label.configure(text=f"▱   {platform_str}")
        if hasattr(self, "info_channel_label") and self.info_channel_label.winfo_exists():
            self.info_channel_label.configure(text=f"▣   {uploader_str}")
        if duration and hasattr(self, "clip_end_var"):
            h, rem = divmod(duration, 3600)
            m, s = divmod(rem, 60)
            self.clip_end_var.set(f"{h:02d}:{m:02d}:{s:02d}")

        url = info.get("thumbnail")
        if url and str(url).startswith("https://"):
            def work():
                try:
                    import requests

                    with requests.get(url, timeout=15, stream=True) as response:
                        response.raise_for_status()
                        buffer = bytearray()
                        for chunk in response.iter_content(65536):
                            buffer.extend(chunk)
                            if len(buffer) > 5 * 1024 * 1024:
                                raise ValueError("Thumbnail too large")
                    image = Image.open(io.BytesIO(buffer))
                    image.thumbnail((500, 280))
                    image = image.copy()
                    self._ui_callbacks.put(
                        lambda: self.set_preview_image(image) if self.active_tab == "Dashboard" else None
                    )
                except Exception:
                    pass

            threading.Thread(target=work, daemon=True, name="thumbnail").start()

    def set_preview_image(self, image):
        if not hasattr(self, "preview_image") or not self.preview_image.winfo_exists():
            return
        self.preview_ctk_image = ctk.CTkImage(image, size=(236, 132))
        self.preview_image.configure(image=self.preview_ctk_image, text="")
        if hasattr(self, "info_thumb_label") and self.info_thumb_label.winfo_exists():
            self.mini_ctk_image = ctk.CTkImage(image, size=(108, 68))
            self.info_thumb_label.configure(image=self.mini_ctk_image, text="")

    def _prepare_dashboard_settings(self):
        if hasattr(self, "quality_display_var"):
            self.quality_var.set(self._quality_from_display(self.quality_display_var.get()))
        if hasattr(self, "format_display_var"):
            self.format_var.set(self._format_from_display(self.format_display_var.get()))
        if hasattr(self, "subtitle_mode_display_var"):
            self.dashboard_subtitle_mode.set(self._subtitle_mode_from_display(self.subtitle_mode_display_var.get()))
        if hasattr(self, "original_var"):
            self.settings["save_original_subtitles"] = self.original_var.get()
            self.settings["save_thumbnail"] = self.thumb_var.get()
            self.settings["audio_bitrate"] = self.audio_bitrate_var.get()
            self.settings["quality"] = self.quality_var.get()
            self.settings["format"] = self.format_var.get()
        if hasattr(self, "desc_var"):
            self.settings["save_description"] = self.desc_var.get()
        if hasattr(self, "split_var"):
            self.settings["auto_split_clips"] = self.split_var.get()
        if hasattr(self, "clip_var"):
            self.settings["clip_enabled"] = self.clip_var.get()
            self.settings["clip_start"] = self.clip_start_var.get().strip()
            self.settings["clip_end"] = self.clip_end_var.get().strip()
        if hasattr(self, "source_var"):
            self._sync_sub_lang_vars()
            self.settings["download_subs"] = self.sub_var.get()
            if self.dashboard_subtitle_mode.get():
                self.settings["subtitle_mode"] = self.dashboard_subtitle_mode.get()
            SettingsManager.save(self.settings)

    def start_download_action(self):
        self._prepare_dashboard_settings()
        super().start_download_action()

    def handle_metadata_result(self, url, info):
        """Enqueue downloads while keeping the user on the 2.0 Dashboard if already there."""
        was_dashboard = self.active_tab == "Dashboard"
        self._prepare_dashboard_settings()
        super().handle_metadata_result(url, info)
        if was_dashboard and info and "error" not in info and info.get("type") != "playlist":
            if self.active_tab == "Downloads":
                self.show_tab("Dashboard")
                self.render_download_items()

    # ------------------------------------------------------------------
    # Queue cards (Horizontal layout matching reference UI)
    # ------------------------------------------------------------------
    def create_download_card(self, task, idx):
        colors = self.c
        tid = task["id"]
        card = ctk.CTkFrame(
            self.downloads_scroll,
            fg_color=colors["bg_soft"],
            corner_radius=12,
            border_width=1,
            border_color=colors["edge"],
        )
        card.grid(row=idx, column=0, sticky="ew", padx=4, pady=3)
        card.grid_columnconfigure(1, weight=2)
        card.grid_columnconfigure(3, weight=3)

        settings = task.get("settings", {})
        if settings.get("extract_audio"):
            q_badge = "Audio"
            f_badge = str(settings.get("audio_format", "MP3")).upper()
        else:
            quality = str(settings.get("quality", "Best"))
            f_badge = str(settings.get("format", "MP4")).upper()
            q_badge = "4K" if ("4K" in quality or "2160" in quality or "Best" in quality) else (
                "1080p" if "1080" in quality else ("720p" if "720" in quality else "HD")
            )

        thumb_img = _make_scenic_preview(92, 52, "")
        card._thumb_ctk = ctk.CTkImage(thumb_img, size=(92, 52))
        ctk.CTkLabel(
            card,
            text="",
            image=card._thumb_ctk,
            width=92,
            height=52,
            fg_color=colors["panel2"],
            corner_radius=8,
        ).grid(row=0, column=0, rowspan=2, padx=(10, 10), pady=8)

        # Column 1: Title + Badges (Quality, Format, Subtitle language)
        title = ctk.CTkLabel(
            card,
            text="",
            anchor="w",
            justify="left",
            font=("Segoe UI", 13, "bold"),
            text_color=colors["text"],
            wraplength=310,
        )
        title.grid(row=0, column=1, padx=(2, 8), pady=(8, 1), sticky="ew")

        badges_row = ctk.CTkFrame(card, fg_color="transparent")
        badges_row.grid(row=1, column=1, padx=(2, 8), pady=(0, 8), sticky="w")
        ctk.CTkLabel(
            badges_row,
            text=f" {q_badge} ",
            fg_color=colors["panel2"],
            text_color=colors["text"],
            corner_radius=5,
            font=("Segoe UI", 10, "bold"),
            height=20,
        ).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(
            badges_row,
            text=f" {f_badge} ",
            fg_color=colors["panel2"],
            text_color=colors["muted"],
            corner_radius=5,
            font=("Segoe UI", 10),
            height=20,
        ).pack(side="left", padx=(0, 6))

        sub_enabled = settings.get("download_subs", True) and not settings.get("extract_audio")
        _, tgt_code = language_from_key(settings.get("sub_lang", "auto-ar"))
        sub_text = (
            self.t(f"الترجمة: {LANGUAGE_NAMES_AR.get(tgt_code, 'العربية')}", f"Subtitles: {LANGUAGES.get(tgt_code, 'Arabic')}")
            if sub_enabled
            else self.t("بدون ترجمة", "No subtitles")
        )
        ctk.CTkLabel(
            badges_row,
            text=sub_text,
            text_color=colors["muted"],
            font=("Segoe UI", 10),
        ).pack(side="left")

        # Column 2: Status Indicator Icon
        status_icon = ctk.CTkLabel(
            card,
            text="●",
            text_color=colors["good"],
            font=("Segoe UI", 14, "bold"),
            width=26,
        )
        status_icon.grid(row=0, column=2, rowspan=2, padx=4)

        # Column 3: Progress bar + Percent + Transfer details
        prog_col = ctk.CTkFrame(card, fg_color="transparent")
        prog_col.grid(row=0, column=3, rowspan=2, padx=8, pady=8, sticky="ew")
        prog_col.grid_columnconfigure(0, weight=1)

        progress = ctk.CTkProgressBar(prog_col, progress_color=colors["blue"], height=8, corner_radius=4)
        progress.grid(row=0, column=0, padx=(0, 8), pady=(4, 2), sticky="ew")
        progress.set(task.get("progress", 0))

        percent = ctk.CTkLabel(
            prog_col,
            text=f"{int((task.get('progress') or 0) * 100)}%",
            width=46,
            text_color=colors["text"],
            font=("Segoe UI", 11, "bold"),
        )
        percent.grid(row=0, column=1, pady=(4, 2))

        info = ctk.CTkLabel(
            prog_col,
            text="",
            anchor="w",
            justify="left",
            text_color=colors["muted"],
            font=("Segoe UI", 10),
            wraplength=420,
        )
        info.grid(row=1, column=0, columnspan=2, sticky="ew")

        # Column 4: Status Text & Action Buttons
        right_col = ctk.CTkFrame(card, fg_color="transparent")
        right_col.grid(row=0, column=4, rowspan=2, padx=(6, 10), pady=6, sticky="e")

        status_lbl = ctk.CTkLabel(
            right_col,
            text="",
            font=("Segoe UI", 11, "bold"),
            text_color=colors["blue"],
            width=92,
            anchor="e",
        )
        status_lbl.pack(side="right", padx=(6, 0))

        actions = ctk.CTkFrame(right_col, fg_color="transparent")
        actions.pack(side="right")
        commands = {
            "pause": ("Ⅱ", lambda: self.queue_manager.pause_task(tid)),
            "resume": ("▶", lambda: self.queue_manager.resume_task(tid)),
            "cancel": ("×", lambda: self.queue_manager.cancel_task(tid)),
            "retry": ("↻", lambda: self.queue_manager.retry_task(tid)),
            "remove": ("×", lambda: self.queue_manager.remove_task(tid)),
            "show": ("▱", lambda: self._show_task_file(tid)),
        }
        self.card_widgets[tid] = card
        self._card_title_labels[tid] = title
        self._card_info_labels[tid] = info
        self._card_progress_bars[tid] = progress
        self._card_percent_labels[tid] = percent
        self._card_status_labels[tid] = (status_lbl, status_icon)
        self._card_buttons[tid] = {}
        for key, (label, command) in commands.items():
            button = ctk.CTkButton(
                actions,
                text=label,
                width=32,
                height=28,
                fg_color=colors["panel2"],
                hover_color=colors["blue_soft"],
                text_color=colors["text"],
                command=command,
                corner_radius=7,
                font=("Segoe UI", 11, "bold"),
            )
            self._card_buttons[tid][key] = button

    def _update_download_card(self, task):
        tid = task["id"]
        if tid not in self.card_widgets:
            return
        status = task.get("status", "Queued")
        old = self._card_snapshots.get(tid, {})
        title = str(task.get("title", ""))
        status_ar, status_en = STATUS_LABELS.get(status, (status, status))
        status_display = self.t(status_ar, status_en)
        progress = float(task.get("progress") or 0)

        size_mb = float(task.get("filesize") or 0) / 1048576
        parts = []
        if status == "Downloading":
            if size_mb:
                dl_mb = size_mb * progress
                parts.append(f"{dl_mb:.1f} MB / {size_mb:.1f} MB")
            if task.get("speed"):
                parts.append(str(task["speed"]))
            if task.get("eta"):
                parts.append(f"{'باقي:' if self.is_arabic else 'ETA:'} {task['eta']}")
        elif status == "Completed":
            if size_mb:
                parts.append(f"{size_mb:.1f} MB")
            parts.append("اكتمل بنجاح" if self.is_arabic else "Completed successfully")
        elif status == "Translating" and task.get("stage"):
            parts.append(str(task["stage"]))
        elif task.get("error"):
            parts = [str(task["error"])[:180]]
        else:
            parts.append(status_ar if self.is_arabic else status_en)
        text = "  •  ".join(parts)

        if title != old.get("title"):
            self._card_title_labels[tid].configure(text=title)
        if text != old.get("text"):
            # Shape Arabic exactly once, after assembling the full mixed-language line.
            self._card_info_labels[tid].configure(text=fix_arabic_text(text) if self.is_arabic else text)
        if progress != old.get("progress"):
            self._card_progress_bars[tid].set(progress)
            if tid in self._card_percent_labels:
                self._card_percent_labels[tid].configure(text=f"{int(progress * 100)}%")

        bar_color = (
            self.c["good"]
            if status == "Completed"
            else self.c["bad"]
            if status in ("Failed", "Cancelled")
            else self.c["blue"]
        )
        self._card_progress_bars[tid].configure(progress_color=bar_color)

        if tid in getattr(self, "_card_status_labels", {}):
            status_lbl, status_icon = self._card_status_labels[tid]
            status_lbl.configure(text=status_display, text_color=bar_color)
            icon_char = "✓" if status == "Completed" else ("▲" if status in ("Failed", "Cancelled") else "↓")
            status_icon.configure(text=icon_char, text_color=bar_color)

        if status != old.get("status"):
            buttons = self._card_buttons[tid]
            for button in buttons.values():
                button.pack_forget()
            actions = {
                "Queued": ("pause", "cancel"),
                "Downloading": ("pause", "cancel"),
                "Paused": ("resume", "cancel"),
                "Processing / Muxing": ("cancel",),
                "Merging & Processing (FFmpeg)...": ("cancel",),
                "Translating": ("cancel",),
                "Failed": ("retry", "remove"),
                "Cancelled": ("retry", "remove"),
                "Completed": ("show", "remove"),
            }.get(status, ())
            for action in actions:
                buttons[action].pack(side="left", padx=2)
        self._card_snapshots[tid] = dict(title=title, text=text, progress=progress, status=status)

    def set_filter(self, filter_value):
        self.active_filter = filter_value
        self._refresh_filter_pills()
        self.render_download_items()

    def _refresh_filter_pills(self):
        all_tasks = self.queue_manager.get_tasks_by_status()
        counts = {
            "all": len(all_tasks),
            "downloading": sum(t["status"] not in self.queue_manager.TERMINAL for t in all_tasks),
            "completed": sum(t["status"] == "Completed" for t in all_tasks),
            "failed": sum(t["status"] == "Failed" for t in all_tasks),
        }
        for value, ar, en in FILTERS:
            btn = getattr(self, "filter_buttons", {}).get(value)
            if btn is not None and btn.winfo_exists():
                selected = value == self.active_filter
                btn.configure(
                    text=f"{self.t(ar, en)} ({counts.get(value, 0)})",
                    fg_color=self.c["blue"] if selected else self.c["panel2"],
                    text_color="#ffffff" if selected else self.c["muted"],
                    border_color=self.c["blue"] if selected else self.c["edge"],
                )

    def render_download_items(self):
        try:
            super().render_download_items()
        except Exception:
            return
        self._refresh_filter_pills()
        tasks = self.queue_manager.get_tasks_by_status()
        summary = getattr(self, "queue_summary_label", None)
        if summary is not None and summary.winfo_exists():
            active = sum(task["status"] not in self.queue_manager.TERMINAL for task in tasks)
            completed = sum(task["status"] == "Completed" for task in tasks)
            summary.configure(
                text=self.t(
                    f"نشط {active}  •  مكتمل {completed}  •  الإجمالي {len(tasks)}",
                    f"Active {active}  •  Completed {completed}  •  Total {len(tasks)}",
                )
            )

    def refresh_ui(self):
        if self.active_tab in ("Dashboard", "Downloads"):
            scroll = getattr(self, "downloads_scroll", None)
            if scroll is not None and scroll.winfo_exists():
                self.render_download_items()

    # ------------------------------------------------------------------
    # Downloads / History / Settings
    # ------------------------------------------------------------------
    def build_downloads_tab(self):
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(4, 10))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text=self.t("⇩  التنزيلات", "Downloads"),
            font=("Segoe UI", 24, "bold"),
            text_color=self.c["text"],
        ).grid(row=0, column=0, sticky="w")

        self.filter_buttons = {}
        filters = ctk.CTkFrame(header, fg_color="transparent")
        filters.grid(row=0, column=1, sticky="e")
        for column, (value, ar, en) in enumerate(FILTERS):
            button = self.ghost_button(
                filters,
                f"{self.t(ar, en)} (0)",
                lambda v=value: self.set_filter(v),
                fg_color=self.c["blue"] if value == self.active_filter else "transparent",
                text_color="#ffffff" if value == self.active_filter else self.c["muted"],
                border_width=1,
                border_color=self.c["edge"],
                width=102,
                height=32,
                font=("Segoe UI", 10),
            )
            button.grid(row=0, column=column, padx=3)
            self.filter_buttons[value] = button
        self.ghost_button(
            header,
            "🗑  " + self.t("مسح المكتمل", "Clear completed"),
            self.clear_completed,
            fg_color=self.c["panel2"],
            width=126,
            height=32,
            font=("Segoe UI", 10),
        ).grid(row=0, column=2, padx=(12, 0))

        self.downloads_scroll = ctk.CTkScrollableFrame(
            frame,
            fg_color=self.c["panel"],
            corner_radius=14,
            border_width=1,
            border_color=self.c["edge"],
            scrollbar_button_color=self.c["edge"],
            scrollbar_button_hover_color=self.c["blue"],
        )
        self.downloads_scroll.grid(row=1, column=0, sticky="nsew")
        self.downloads_scroll.grid_columnconfigure(0, weight=1)

        status_bar = ctk.CTkFrame(frame, fg_color="transparent")
        status_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.status_label = ctk.CTkLabel(
            status_bar,
            text="",
            text_color=self.c["muted"],
            font=("Segoe UI", 10),
        )
        self.status_label.pack(side="left")
        self.render_download_items()

    def build_history_tab(self):
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            frame,
            text=self.t("◷  سجل التنزيلات", "Download history"),
            font=("Segoe UI", 24, "bold"),
            text_color=self.c["text"],
        ).grid(row=0, column=0, pady=(4, 10), sticky="w")

        scroll = ctk.CTkScrollableFrame(
            frame,
            fg_color=self.c["panel"],
            corner_radius=14,
            border_width=1,
            border_color=self.c["edge"],
            scrollbar_button_color=self.c["edge"],
            scrollbar_button_hover_color=self.c["blue"],
        )
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        items = HistoryManager.load()
        if not items:
            ctk.CTkLabel(
                scroll,
                text=self.t("لا يوجد سجل تنزيلات بعد.", "No download history yet."),
                text_color=self.c["muted"],
                font=("Segoe UI", 13),
            ).grid(row=0, column=0, pady=50)
            return
        for index, item in enumerate(items):
            row = ctk.CTkFrame(scroll, fg_color=self.c["bg_soft"], corner_radius=10)
            row.grid(row=index, column=0, sticky="ew", padx=8, pady=4)
            row.grid_columnconfigure(1, weight=1)
            title = str(item.get("title", "Unknown"))
            ctk.CTkLabel(
                row,
                text=title,
                font=("Segoe UI", 13, "bold"),
                text_color=self.c["text"],
                anchor="w",
                justify="left",
                wraplength=620,
            ).grid(row=0, column=0, columnspan=2, padx=14, pady=(10, 2), sticky="ew")
            detail = "  •  ".join(
                part
                for part in (
                    str(item.get("time", "")),
                    str(item.get("platform", "")),
                    self.t("مكتمل", "Completed"),
                )
                if part
            )
            ctk.CTkLabel(
                row,
                text=detail,
                text_color=self.c["muted"],
                font=("Segoe UI", 10),
                anchor="w",
            ).grid(row=1, column=0, padx=14, pady=(0, 2), sticky="ew")
            path = item.get("file_path")
            if path and Path(path).exists():
                self.ghost_button(
                    row,
                    self.t("إظهار الملف", "Show in folder"),
                    lambda p=path: open_file_in_explorer(p),
                    fg_color=self.c["panel2"],
                    width=118,
                    height=28,
                    font=("Segoe UI", 10),
                ).grid(row=2, column=0, padx=14, pady=(2, 10), sticky="w")

    def build_settings_tab(self):
        scroll = ctk.CTkScrollableFrame(
            self.content_frame,
            fg_color="transparent",
            scrollbar_button_color=self.c["edge"],
            scrollbar_button_hover_color=self.c["blue"],
        )
        scroll.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        scroll.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            scroll,
            text=self.t("⚙  الإعدادات", "Settings"),
            font=("Segoe UI", 24, "bold"),
            text_color=self.c["text"],
        ).grid(row=0, column=0, pady=(6, 10), sticky="w")

        card = self.card(scroll)
        card.grid(row=1, column=0, sticky="ew", pady=8)
        card.grid_columnconfigure(1, weight=1)
        row = 0

        def heading(text_ar, text_en):
            nonlocal row
            ctk.CTkLabel(
                card,
                text=self.t(text_ar, text_en),
                font=("Segoe UI", 12, "bold"),
                text_color=self.c["blue"],
                anchor="w",
            ).grid(row=row, column=0, columnspan=2, padx=18, pady=(14, 4), sticky="w")
            row += 1

        def label(text_ar, text_en):
            nonlocal row
            ctk.CTkLabel(
                card,
                text=self.t(text_ar, text_en),
                text_color=self.c["text"],
                font=("Segoe UI", 11),
                anchor="w",
            ).grid(row=row, column=0, padx=18, pady=7, sticky="w")

        heading("الملفات والتنزيل", "Files and downloads")
        label("مجلد الحفظ", "Output folder")
        self.dir_entry = ctk.CTkEntry(
            card,
            fg_color=self.c["panel2"],
            border_color=self.c["edge"],
            text_color=self.c["text"],
            height=34,
        )
        self.dir_entry.insert(0, self.settings.get("download_dir", self.selected_folder))
        self.dir_entry.grid(row=row, column=1, padx=18, pady=7, sticky="ew")
        row += 1

        label("التنزيلات المتزامنة", "Concurrent downloads")
        self.concurrent_var = ctk.StringVar(value=str(self.settings.get("max_concurrent", 3)))
        ctk.CTkOptionMenu(
            card,
            values=["1", "2", "3", "4", "5"],
            variable=self.concurrent_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            text_color=self.c["text"],
            width=120,
        ).grid(row=row, column=1, padx=18, pady=7, sticky="w")
        row += 1

        self.sub_var = ctk.BooleanVar(value=self.settings.get("download_subs", True))
        ctk.CTkCheckBox(
            card,
            text=self.t("تنزيل الترجمة تلقائيًا", "Download subtitles automatically"),
            variable=self.sub_var,
            fg_color=self.c["blue"],
            text_color=self.c["text"],
            border_color=self.c["edge"],
        ).grid(row=row, column=0, columnspan=2, padx=18, pady=6, sticky="w")
        row += 1

        self.thumb_var = ctk.BooleanVar(value=self.settings.get("save_thumbnail", True))
        ctk.CTkCheckBox(
            card,
            text=self.t("حفظ الصور المصغرة", "Save video thumbnails"),
            variable=self.thumb_var,
            fg_color=self.c["blue"],
            text_color=self.c["text"],
            border_color=self.c["edge"],
        ).grid(row=row, column=0, columnspan=2, padx=18, pady=6, sticky="w")
        row += 1

        label("ملف تعريف الارتباط (اختياري)", "Cookies file (optional)")
        self.cookies_entry = ctk.CTkEntry(
            card,
            fg_color=self.c["panel2"],
            border_color=self.c["edge"],
            text_color=self.c["text"],
            placeholder_text="Path to cookies.txt (Netscape format)",
            height=34,
        )
        self.cookies_entry.insert(0, self.settings.get("cookies_file", ""))
        self.cookies_entry.grid(row=row, column=1, padx=18, pady=7, sticky="ew")
        row += 1

        heading("الترجمة بين اللغات الأربع (ar / en / tr / ko)", "4-Language Translation (ar / en / tr / ko)")
        label("اتجاه الترجمة", "Subtitle direction")
        self.translation_source_var = ctk.StringVar(value=self.settings.get("sub_lang", "auto-ar"))
        ctk.CTkOptionMenu(
            card,
            values=[key for key in TRANSLATION_DIRECTIONS if key != "auto"] + list(LANGUAGES),
            variable=self.translation_source_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            text_color=self.c["text"],
            width=220,
        ).grid(row=row, column=1, padx=18, pady=7, sticky="w")
        row += 1

        label("طريقة حفظ الترجمة", "Subtitle output")
        self.subtitle_mode_var = ctk.StringVar(value=self.settings.get("subtitle_mode", "separate"))
        ctk.CTkOptionMenu(
            card,
            values=["separate", "embed", "burn", "both"],
            variable=self.subtitle_mode_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            text_color=self.c["text"],
            width=220,
        ).grid(row=row, column=1, padx=18, pady=7, sticky="w")
        row += 1

        ctk.CTkLabel(
            card,
            text=self.t(
                "يدعم جميع الاتجاهات الـ 12 بين العربية والإنجليزية والتركية والكورية + الاكتشاف التلقائي",
                "Supports all 12 directions across Arabic, English, Turkish & Korean + speech auto-detection",
            ),
            text_color=self.c["muted"],
            font=("Segoe UI", 10),
            anchor="w",
        ).grid(row=row, column=0, columnspan=2, padx=18, pady=(0, 8), sticky="w")
        row += 1

        self.original_var = ctk.BooleanVar(value=self.settings.get("save_original_subtitles", False))
        ctk.CTkCheckBox(
            card,
            text=self.t("حفظ النص الأصلي أيضًا", "Also save the original transcript"),
            variable=self.original_var,
            fg_color=self.c["blue"],
            text_color=self.c["text"],
            border_color=self.c["edge"],
        ).grid(row=row, column=0, columnspan=2, padx=18, pady=6, sticky="w")
        row += 1

        heading("الأداء والتحديثات الآمنة", "Performance and signed updates")
        label("وضع الأداء", "Performance profile")
        self.performance_var = ctk.StringVar(value=self.settings.get("performance_mode", "balanced"))
        ctk.CTkOptionMenu(
            card,
            values=["economy", "balanced", "high"],
            variable=self.performance_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            text_color=self.c["text"],
            width=220,
        ).grid(row=row, column=1, padx=18, pady=7, sticky="w")
        row += 1

        label("نموذج التعرف على الكلام", "Speech model")
        self.speech_var = ctk.StringVar(value=self.settings.get("speech_model", "base"))
        ctk.CTkOptionMenu(
            card,
            values=["base", "small", "medium"],
            variable=self.speech_var,
            fg_color=self.c["panel2"],
            button_color=self.c["blue_soft"],
            text_color=self.c["text"],
            width=220,
        ).grid(row=row, column=1, padx=18, pady=7, sticky="w")
        row += 1

        self.auto_update_var = ctk.BooleanVar(value=self.settings.get("auto_update_check", True))
        ctk.CTkCheckBox(
            card,
            text=self.t("فحص التحديثات الموقّعة رقميًا عند البدء", "Check for digitally signed updates on startup"),
            variable=self.auto_update_var,
            fg_color=self.c["blue"],
            text_color=self.c["text"],
            border_color=self.c["edge"],
        ).grid(row=row, column=0, columnspan=2, padx=18, pady=6, sticky="w")
        row += 1

        self.prerelease_var = ctk.BooleanVar(value=self.settings.get("allow_prereleases", False))
        ctk.CTkCheckBox(
            card,
            text=self.t("السماح بالتحديثات التجريبية", "Allow prerelease updates"),
            variable=self.prerelease_var,
            fg_color=self.c["blue"],
            text_color=self.c["text"],
            border_color=self.c["edge"],
        ).grid(row=row, column=0, columnspan=2, padx=18, pady=6, sticky="w")
        row += 1

        self.button(
            card,
            self.t("حفظ الإعدادات", "Save settings"),
            self.save_settings_action,
            height=42,
        ).grid(row=row, column=0, columnspan=2, padx=18, pady=14, sticky="ew")
        row += 1

        self.ghost_button(
            card,
            self.t("فحص التحديثات الآن", "Check for updates now"),
            lambda: getattr(self, "updater", None) and self.updater.check(True),
            fg_color=self.c["panel2"],
            border_width=1,
            border_color=self.c["edge"],
            height=36,
        ).grid(row=row, column=0, columnspan=2, padx=18, pady=(0, 16), sticky="ew")

    def save_settings_action(self):
        self.settings["download_dir"] = self.dir_entry.get().strip() or self.settings.get("download_dir")
        self.settings["download_subs"] = self.sub_var.get()
        self.settings["save_thumbnail"] = self.thumb_var.get()
        try:
            maximum = max(1, min(8, int(self.concurrent_var.get())))
        except ValueError:
            maximum = self.settings.get("max_concurrent", 3)
        self.settings["max_concurrent"] = maximum
        self.settings["cookies_file"] = self.cookies_entry.get().strip()
        self.settings["sub_lang"] = selected_subtitle_language(self.translation_source_var.get())
        self.settings["sub_lang_explicit"] = True
        self.settings["subtitle_mode"] = self.subtitle_mode_var.get()
        self.settings["save_original_subtitles"] = self.original_var.get()
        self.settings["performance_mode"] = self.performance_var.get()
        self.settings["speech_model"] = self.speech_var.get()
        self.settings["auto_update_check"] = self.auto_update_var.get()
        self.settings["allow_prereleases"] = self.prerelease_var.get()
        self.selected_folder = self.settings["download_dir"]
        Path(self.selected_folder).mkdir(parents=True, exist_ok=True)
        from main import save_config

        save_config({"download_folder": self.selected_folder})
        SettingsManager.save(self.settings)
        self.queue_manager.set_max_concurrent(maximum)
        if hasattr(self, "folder_path_label") and self.folder_path_label.winfo_exists():
            self.folder_path_label.configure(text=self.selected_folder)
        self.notify("تم حفظ الإعدادات", "Settings saved")

    # ------------------------------------------------------------------
    # Local media, advanced options, support
    # ------------------------------------------------------------------
    def build_local_tab(self, convert=False):
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        frame.grid_columnconfigure(0, weight=1)

        card = self.card(frame)
        card.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        card.grid_columnconfigure(0, weight=1)
        self.section_title(
            card,
            "⇄  التحويل والصيغ" if convert else "▣  ترجمة ملف محلي",
            "Convert media" if convert else "Translate local media",
            size=24,
        ).grid(row=0, column=0, padx=24, pady=(20, 4), sticky="w")
        ctk.CTkLabel(
            card,
            text=self.t(
                "اختر فيديو أو ملف ترجمة. تتم المعالجة محليًا بين العربية والإنجليزية والتركية والكورية.",
                "Choose a video or subtitle file. Processing stays on this device across ar/en/tr/ko.",
            ),
            text_color=self.c["muted"],
            font=("Segoe UI", 11),
            anchor="w",
        ).grid(row=1, column=0, padx=24, pady=(0, 14), sticky="w")

        path = ctk.StringVar()
        path_entry = ctk.CTkEntry(
            card,
            textvariable=path,
            height=42,
            fg_color=self.c["panel2"],
            border_color=self.c["edge"],
            text_color=self.c["text"],
        )
        path_entry.grid(row=2, column=0, padx=24, pady=8, sticky="ew")

        def choose():
            value = filedialog.askopenfilename(
                title=self.t("اختيار ملف", "Choose a file"),
                filetypes=[
                    ("Media / subtitles", "*.mp4 *.mkv *.mov *.mp3 *.wav *.m4a *.srt"),
                    ("All files", "*.*"),
                ],
            )
            if value:
                path.set(value)

        choose_button = self.ghost_button(
            card,
            self.t("اختيار ملف", "Choose file"),
            choose,
            fg_color=self.c["panel2"],
            border_width=1,
            border_color=self.c["edge"],
            width=180,
        )
        choose_button.grid(row=3, column=0, pady=8)

        src = ctk.StringVar(value=self._source_labels()[0])
        dst = ctk.StringVar(value=self._target_labels()[0])
        mode = ctk.StringVar(value="MP4" if convert else self._subtitle_mode_display_values()[0])
        menus = ctk.CTkFrame(card, fg_color="transparent")
        menus.grid(row=4, column=0, padx=24, pady=10)
        option_widgets = []
        for var, values, width in (
            (src, self._source_labels(), 190),
            (dst, self._target_labels(), 190),
            (mode, ["MP4", "MKV", "MP3"] if convert else self._subtitle_mode_display_values(), 210),
        ):
            menu = ctk.CTkOptionMenu(
                menus,
                variable=var,
                values=values,
                width=width,
                fg_color=self.c["panel2"],
                button_color=self.c["blue_soft"],
                text_color=self.c["text"],
            )
            menu.pack(side="left", padx=4)
            option_widgets.append(menu)

        label = ctk.CTkLabel(
            card,
            text=self.t(
                "لغة المصدر • اللغة الهدف • طريقة الحفظ",
                "Source language • target language • output mode",
            ),
            text_color=self.c["muted"],
            font=("Segoe UI", 10),
        )
        label.grid(row=5, column=0, pady=(2, 8))
        bar = ctk.CTkProgressBar(card, progress_color=self.c["blue"])
        bar.grid(row=6, column=0, padx=24, pady=10, sticky="ew")
        bar.set(0)

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.grid(row=7, column=0, padx=24, pady=(0, 18))

        animated = [False]

        def render_progress(stage, fraction=None):
            if not label.winfo_exists():
                return
            if self.state() == "iconic":
                bar.stop()
                animated[0] = False
                return
            elapsed = time.monotonic() - getattr(self, "_local_started_at", time.monotonic())
            suffix = ""
            if self._local_running:
                minutes, seconds = divmod(int(elapsed), 60)
                suffix = self.t(f"  •  الوقت المنقضي {minutes:02}:{seconds:02}",
                                f"  •  Elapsed {minutes:02}:{seconds:02}")
            label.configure(text=fix_arabic_text(stage) + suffix)
            if fraction is None and self._local_running:
                if not animated[0]:
                    bar.configure(mode="indeterminate")
                    bar.start()
                    animated[0] = True
            else:
                bar.stop()
                animated[0] = False
                bar.configure(mode="determinate")
                bar.set(fraction or 0)

        def deliver_progress(stage, fraction=None):
            self._local_status = (stage, fraction)
            view = getattr(self, "_local_progress_view", None)
            if view:
                view(stage, fraction)

        self._local_progress_view = render_progress
        progress = LatestProgress(self._ui_callbacks, deliver_progress)

        def update_controls():
            if not frame.winfo_exists():
                return
            busy = self._local_running
            cancelling = busy and self._local_cancel.is_set()
            start_button.configure(state="disabled" if busy else "normal",
                text=self.t("جارٍ الإلغاء…", "Cancelling…") if cancelling else
                     self.t("جارٍ المعالجة…", "Processing…") if busy else
                     self.t("بدء المعالجة", "Start processing"))
            cancel_button.configure(state="normal" if busy and not cancelling else "disabled")
            for widget in [path_entry, choose_button, *option_widgets]:
                widget.configure(state="disabled" if busy else "normal")

        self._local_controls_view = update_controls

        def finish():
            self._local_running = False
            controls = getattr(self, "_local_controls_view", None)
            if controls:
                controls()
            view = getattr(self, "_local_progress_view", None)
            if view:
                view(*getattr(self, "_local_status", ("", 0)))

        def cancel():
            if not self._local_running:
                return
            self._local_cancel.set()
            self._local_status = (self.t("جارٍ إلغاء المهمة…", "Cancelling task…"), None)
            update_controls()
            render_progress(*self._local_status)

        def start():
            if self._local_running:
                return
            media = Path(path.get())
            if not media.is_file():
                self.notify("اختر ملف وسائط موجودًا", "Choose an existing media file", "error")
                return
            source = self._lang_code(src.get())
            target = self._lang_code(dst.get())
            if target not in LANGUAGES:
                target = "ar"
            output = mode.get() if convert else self._subtitle_mode_from_display(mode.get())
            self._local_result = None
            self._local_error = None
            self._local_running = True
            self._local_cancel.clear()
            self._local_started_at = time.monotonic()
            self._local_status = (self.t("بدأت المهمة، جارٍ التجهيز…", "Task started, preparing…"), None)
            update_controls()
            render_progress(*self._local_status)
            # Capture all UI-owned settings before entering the worker.
            folder = self.selected_folder
            save_original = self.settings.get("save_original_subtitles", False)
            arabic = self.is_arabic
            saved_text = self.t("تم الحفظ: ", "Saved: ")

            def checkpoint():
                if self._local_cancel.is_set():
                    raise RuntimeError("Cancelled by user")

            def worker():
                try:
                    if convert:
                        from translator.video_renderer import run_ffmpeg
                        import uuid

                        destination = Path(folder) / (
                            media.stem + "." + uuid.uuid4().hex[:8] + "." + output.lower()
                        )
                        arguments = ["-i", str(media)]
                        arguments += (
                            ["-vn", "-c:a", "libmp3lame"]
                            if output == "MP3"
                            else ["-c:v", "libx264", "-c:a", "aac"]
                        )
                        import tempfile
                        from translator.pipeline import _publish_file
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with tempfile.TemporaryDirectory(prefix="veyora-convert-") as work:
                            temporary = Path(work) / ("converted." + output.lower())
                            run_ffmpeg(arguments + [str(temporary)], checkpoint)
                            _publish_file(temporary, destination, checkpoint)
                        result = {"video": str(destination)}
                    else:
                        from translator.worker import run_translation

                        result = run_translation(media, folder,
                            mode=output,
                            checkpoint=checkpoint,
                            progress=progress,
                            source_lang=source,
                            target_lang=target,
                            save_original=save_original,
                        )
                    checkpoint()
                    self._ui_callbacks.put(lambda value=result: setattr(self, "_local_result", value))
                    progress(saved_text + ", ".join(result.values()), 1)
                except Exception as exc:
                    self._ui_callbacks.put(lambda value=str(exc): setattr(self, "_local_error", value))
                    progress(friendly_error(exc, arabic, self._local_cancel.is_set()), 0)
                finally:
                    self._ui_callbacks.put(finish)

            threading.Thread(target=worker, daemon=True, name="local-media").start()

        start_button = self.button(
            buttons,
            self.t("بدء المعالجة", "Start processing"),
            start,
            width=170,
        )
        start_button.pack(side="left", padx=6)
        cancel_button = self.ghost_button(
            buttons,
            self.t("إلغاء", "Cancel"),
            cancel,
            fg_color=self.c["panel2"],
            border_width=1,
            border_color=self.c["edge"],
            width=120,
        )
        cancel_button.pack(side="left", padx=6)
        # Stable controls for integration automation; commands remain the real UI path.
        self._local_task_controls = dict(path=path, source=src, target=dst, mode=mode,
            start=start_button, cancel=cancel_button, status=label)
        update_controls()
        if self._local_running:
            render_progress(*getattr(self, "_local_status", ("Working…", None)))

        def tick():
            if not frame.winfo_exists():
                return
            if self._local_running:
                update_controls()
                render_progress(*getattr(self, "_local_status", ("Working…", None)))
            self.after(1000, tick)

        self.after(1000, tick)

        note = ctk.CTkLabel(
            frame,
            text=self.t(
                "يُستخدم FFmpeg المحلي. قد يستغرق أول تشغيل لتنزيل نموذج الترجمة.",
                "Uses local FFmpeg. The first translation run may download a model once.",
            ),
            text_color=self.c["faint"],
            font=("Segoe UI", 10),
            anchor="w",
        )
        note.grid(row=1, column=0, pady=12, sticky="w")

    def show_advanced(self):
        window = ctk.CTkToplevel(self)
        window.title(self.t("خيارات متقدمة", "Advanced options"))
        window.geometry("620x560")
        window.transient(self)
        window.configure(fg_color=self.c["bg"])
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            window,
            text=self.t("خيارات التحميل المتقدمة", "Advanced download options"),
            font=("Segoe UI", 18, "bold"),
            text_color=self.c["text"],
        ).grid(row=0, column=0, padx=22, pady=(16, 6), sticky="w")
        body = ctk.CTkScrollableFrame(window, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        body.grid_columnconfigure(1, weight=1)

        original = ctk.BooleanVar(value=self.settings.get("save_original_subtitles", False))
        thumb = ctk.BooleanVar(value=self.settings.get("save_thumbnail", True))
        max_concurrent = ctk.StringVar(value=str(self.settings.get("max_concurrent", 3)))
        performance = ctk.StringVar(value=self.settings.get("performance_mode", "balanced"))
        speech = ctk.StringVar(value=self.settings.get("speech_model", "base"))
        subtitle_mode = ctk.StringVar(value=self.settings.get("subtitle_mode", "separate"))
        bitrate = ctk.StringVar(value=self.settings.get("audio_bitrate", "320 kbps"))
        auto_update = ctk.BooleanVar(value=self.settings.get("auto_update_check", True))
        prereleases = ctk.BooleanVar(value=self.settings.get("allow_prereleases", False))

        rows = [
            (self.t("الحفظ الأصلي", "Original transcript"), ctk.CTkCheckBox(body, text="", variable=original)),
            (self.t("الصورة المصغرة", "Thumbnail"), ctk.CTkCheckBox(body, text="", variable=thumb)),
        ]
        for row, (text, widget) in enumerate(rows):
            ctk.CTkLabel(body, text=text, text_color=self.c["text"], anchor="w").grid(
                row=row, column=0, padx=14, pady=8, sticky="w"
            )
            widget.grid(row=row, column=1, padx=14, pady=8, sticky="e")

        def add_menu(row, text, variable, values):
            ctk.CTkLabel(body, text=text, text_color=self.c["text"], anchor="w").grid(
                row=row, column=0, padx=14, pady=8, sticky="w"
            )
            ctk.CTkOptionMenu(
                body,
                values=values,
                variable=variable,
                fg_color=self.c["panel2"],
                button_color=self.c["blue_soft"],
                text_color=self.c["text"],
                width=190,
            ).grid(row=row, column=1, padx=14, pady=8, sticky="e")

        add_menu(2, self.t("التنزيلات المتزامنة", "Concurrent downloads"), max_concurrent, ["1", "2", "3", "4", "5"])
        add_menu(3, self.t("وضع الأداء", "Performance profile"), performance, ["economy", "balanced", "high"])
        add_menu(4, self.t("نموذج الكلام", "Speech model"), speech, ["base", "small", "medium"])
        add_menu(5, self.t("حفظ الترجمة", "Subtitle output"), subtitle_mode, ["separate", "embed", "burn", "both"])
        add_menu(6, self.t("جودة الصوت", "Audio quality"), bitrate, ["320 kbps", "256 kbps", "192 kbps", "128 kbps"])

        for row, (text_ar, text_en, variable) in enumerate(
            (
                ("فحص التحديثات عند البدء", "Check updates on startup", auto_update),
                ("السماح بالتجريبية", "Allow prereleases", prereleases),
            ),
            start=7,
        ):
            ctk.CTkLabel(
                body,
                text=self.t(text_ar, text_en),
                text_color=self.c["text"],
                anchor="w",
            ).grid(row=row, column=0, padx=14, pady=8, sticky="w")
            ctk.CTkCheckBox(body, text="", variable=variable).grid(row=row, column=1, padx=14, pady=8, sticky="e")

        def save():
            self.settings["save_original_subtitles"] = original.get()
            self.settings["save_thumbnail"] = thumb.get()
            self.settings["max_concurrent"] = max(1, min(8, int(max_concurrent.get())))
            self.settings["performance_mode"] = performance.get()
            self.settings["speech_model"] = speech.get()
            self.settings["subtitle_mode"] = subtitle_mode.get()
            self.settings["audio_bitrate"] = bitrate.get()
            self.settings["auto_update_check"] = auto_update.get()
            self.settings["allow_prereleases"] = prereleases.get()
            SettingsManager.save(self.settings)
            self.queue_manager.set_max_concurrent(self.settings["max_concurrent"])
            self._update_translation_hint()
            window.destroy()

        buttons = ctk.CTkFrame(window, fg_color="transparent")
        buttons.grid(row=2, column=0, pady=(4, 16))
        self.ghost_button(
            buttons,
            self.t("إغلاق", "Close"),
            window.destroy,
            fg_color=self.c["panel2"],
            border_width=1,
            border_color=self.c["edge"],
            width=130,
        ).pack(side="left", padx=6)
        self.button(buttons, self.t("حفظ", "Save"), save, width=150).pack(side="left", padx=6)

    def show_supported_sites(self):
        window = ctk.CTkToplevel(self)
        window.title(self.t("المواقع المدعومة والدعم", "Supported sites & support"))
        window.geometry("640x460")
        window.transient(self)
        window.configure(fg_color=self.c["bg"])
        text = ctk.CTkTextbox(
            window,
            wrap="word",
            fg_color=self.c["panel"],
            border_color=self.c["edge"],
            border_width=1,
            text_color=self.c["text"],
        )
        text.pack(fill="both", expand=True, padx=18, pady=18)
        if self.is_arabic:
            body = (
                "المواقع الشائعة والروابط المباشرة\n\n"
                "يدعم Veyora أي صفحة فيديو عامة يفهمها محرك yt-dlp، بما في ذلك يوتيوب، "
                "وفيسبوك، وإنستغرام، وتيك توك، وتويتر/إكس، وفيميو، وديلي موشن، وبينترست.\n\n"
                "روابط بينترست: ألصق رابط فيديو عام أو رابط pin.it. الصور الثابتة ليست فيديو.\n\n"
                "الترجمة المحلية: يدعم الترجمة دون اتصال بالإنترنت بين اللغات الأربع (العربية، الإنجليزية، التركية، الكورية).\n\n"
                "عند فشل التحليل يظهر الخطأ الحقيقي بدلًا من معلومات فارغة."
            )
        else:
            body = (
                "Popular sites and direct links\n\n"
                "Veyora supports any public video page understood by yt-dlp, including "
                "YouTube, Facebook, Instagram, TikTok, Twitter/X, Vimeo, Dailymotion and Pinterest.\n\n"
                "Pinterest: paste a public video pin URL or a pin.it short link. Image-only pins are not videos.\n\n"
                "Offline translation: supports all 12 translation directions across Arabic, English, Turkish and Korean.\n\n"
                "When analysis fails, the actual error is shown instead of empty metadata."
            )
        text.insert("1.0", body)
        text.configure(state="disabled")

    def _on_close(self):
        self._local_cancel.set()
        if getattr(self, "updater", None):
            try:
                self.updater.cancel.set()
            except Exception:
                pass
        super()._on_close()
