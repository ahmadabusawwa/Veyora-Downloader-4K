import base64
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import main
from desktop_ui import DesktopApp, direction_key, language_from_key
from translator import pipeline
from updater import core


def test_direction_key_known_pairs():
    assert direction_key("en", "ar") == "auto-ar"
    assert direction_key("ar", "en") == "auto-en"
    assert direction_key("en", "tr") == "auto-en-tr"
    assert direction_key("tr", "ko") == "auto-tr-ko"
    assert direction_key("ko", "ar") == "auto-ko-ar"
    assert direction_key("auto", "ar") == "detect-ar"
    assert direction_key("auto", "en") == "detect-en"
    assert direction_key("auto", "tr") == "detect-tr"
    assert direction_key("auto", "ko") == "detect-ko"


def test_direction_key_native_subtitles():
    # Same language or subtitles disabled means native subtitles, not translation.
    assert direction_key("ar", "ar") == "ar"
    assert direction_key("en", "en") == "en"
    assert direction_key("tr", "ar", translating=False) == "ar"
    assert direction_key("auto", "ko", translating=False) == "ko"


@pytest.mark.parametrize(
    "source,target,expected",
    [
        ("en", "ar", ("en", "ar")),
        ("ar", "en", ("ar", "en")),
        ("en", "tr", ("en", "tr")),
        ("tr", "en", ("tr", "en")),
        ("en", "ko", ("en", "ko")),
        ("ko", "en", ("ko", "en")),
        ("ar", "tr", ("ar", "tr")),
        ("tr", "ar", ("tr", "ar")),
        ("ar", "ko", ("ar", "ko")),
        ("ko", "ar", ("ko", "ar")),
        ("tr", "ko", ("tr", "ko")),
        ("ko", "tr", ("ko", "tr")),
        ("auto", "ar", ("auto", "ar")),
        ("auto", "en", ("auto", "en")),
        ("auto", "tr", ("auto", "tr")),
        ("auto", "ko", ("auto", "ko")),
    ],
)
def test_direction_key_round_trips_through_engine(source, target, expected):
    key = direction_key(source, target)
    assert language_from_key(key) == expected
    assert main.selected_subtitle_language(key) == key


def test_lang_code_handles_arabic_rtl_and_english_labels():
    for label, expected in [
        ("Auto detect", "auto"),
        ("ðŸŒ Ø§ÙƒØªØ´Ø§Ù ØªÙ„Ù‚Ø§Ø¦ÙŠ", "auto"),
        ("Ø§ÙƒØªØ´Ø§Ù ØªÙ„Ù‚Ø§Ø¦ÙŠ", "auto"),
        ("(ar) Ø§Ù„Ø¹Ø±Ø¨ÙŠØ©", "ar"),
        ("Ø§Ù„Ø¹Ø±Ø¨ÙŠØ© (ar)", "ar"),
        ("Arabic (ar)", "ar"),
        ("(en) Ø§Ù„Ø¥Ù†Ø¬Ù„ÙŠØ²ÙŠØ©", "en"),
        ("English (en)", "en"),
        ("(tr) Ø§Ù„ØªØ±ÙƒÙŠØ©", "tr"),
        ("Turkish (tr)", "tr"),
        ("(ko) Ø§Ù„ÙƒÙˆØ±ÙŠØ©", "ko"),
        ("Korean (ko)", "ko"),
    ]:
        assert DesktopApp._lang_code(label) == expected
        assert DesktopApp._lang_code(main.fix_arabic_text(label)) == expected


def test_native_language_key_round_trips():
    assert language_from_key("ko") == ("ko", "ko")
    assert language_from_key("auto") == ("en", "ar")
    assert language_from_key("auto-en-ar") == ("en", "ar")
    assert language_from_key("auto-ar-en") == ("ar", "en")


def test_srt_auto_detect_across_four_languages(monkeypatch, tmp_path):
    provider = Mock()
    provider.translate.return_value = "Translated cue"
    captured = []

    def fake_provider(src, dst):
        captured.append((src, dst))
        return provider

    monkeypatch.setattr(pipeline, "TranslatorProvider", fake_provider)
    samples = [
        ("ar", "en", "1\n00:00:01,000 --> 00:00:02,000\nمرحبا بالعالم\n"),
        ("ko", "ar", "1\n00:00:01,000 --> 00:00:02,000\n안녕하세요\n"),
        ("tr", "ar", "1\n00:00:01,000 --> 00:00:02,000\nMerhaba dünya, bugün güzel\n"),
        ("en", "ar", "1\n00:00:01,000 --> 00:00:02,000\nHello world\n"),
    ]
    for idx, (expected_src, target, content) in enumerate(samples):
        srt = tmp_path / f"sample_{idx}.srt"
        srt.write_text(content, encoding="utf8")
        res = pipeline.TranslationPipeline(srt, tmp_path / f"out_{idx}").run(
            source_lang="auto", target_lang=target
        )
        assert Path(res["subtitle"]).is_file()
        assert captured[-1] == (expected_src, target)


def test_desktop_app_all_sections_and_tabs():
    app = DesktopApp()
    try:
        assert app.url_entry.winfo_exists()
        assert app.preview_image.winfo_exists()
        assert app.preview_title.winfo_exists()
        assert app.info_duration_label.winfo_exists()
        assert app.info_platform_label.winfo_exists()
        assert app.info_channel_label.winfo_exists()
        assert app.info_thumb_label.winfo_exists()
        assert app.download_card.winfo_exists()
        assert app.translation_card.winfo_exists()
        assert app.more_card.winfo_exists()
        assert app.queue_panel.winfo_exists()
        assert app.downloads_scroll.winfo_exists()
        assert app.ready_label.winfo_exists()
        assert app.speed_label.winfo_exists()
        assert app.cpu_label.winfo_exists()
        assert app.memory_label.winfo_exists()

        # Verify all 12 translation directions sync cleanly through the UI controls
        for src in ("ar", "en", "tr", "ko"):
            for dst in ("ar", "en", "tr", "ko"):
                if src == dst:
                    continue
                app.source_var.set(app._label_for_lang(src, allow_auto=True))
                app.target_var.set(app._label_for_lang(dst, allow_auto=False))
                app.sub_var.set(True)
                key = app._sync_sub_lang_vars()
                assert language_from_key(key) == (src, dst)

        # Verify extra switches sync with download/subtitle options
        app.burn_sub_var.set(True)
        app._on_burn_sub_toggle()
        assert app.dashboard_subtitle_mode.get() == "burn"

        app.mkv_save_var.set(True)
        app._on_mkv_save_toggle()
        assert app.format_var.get() == "MKV"
        assert app.dashboard_subtitle_mode.get() == "embed"

        for tab in ("Downloads", "History", "Settings", "Translation", "Convert", "Dashboard"):
            app.show_tab(tab)
        app.toggle_language()
        app.toggle_language()
    finally:
        app._on_close()


def test_trusted_keys_load_rejects_malformed(tmp_path):
    key = Ed25519PrivateKey.generate()
    raw = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    store = tmp_path / "keys.json"
    store.write_text(json.dumps({"good": raw, "short": base64.b64encode(b"short").decode(), "bad": "not-base64!"}), encoding="utf8")
    keys = core.load_trusted_keys(store)
    assert keys == {"good": raw}


def test_trusted_keys_missing_or_invalid_file(tmp_path):
    assert core.load_trusted_keys(tmp_path / "absent.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("[not json", encoding="utf8")
    assert core.load_trusted_keys(broken) == {}
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf8")
    assert core.load_trusted_keys(array) == {}


def test_sign_and_verify_update_end_to_end(monkeypatch, tmp_path):
    from tools import sign_update, update_keys

    store = tmp_path / "trusted_keys.json"
    store.write_text("{}\n", encoding="utf8")
    monkeypatch.setattr(core, "TRUSTED_KEYS_PATH", store)

    priv_key = tmp_path / "outside-private.pem"
    assert update_keys.main(["generate", "--key-id", "test-2026", "--private-key", str(priv_key)]) == 0
    assert priv_key.is_file()
    enrolled = core.load_trusted_keys(store)
    assert "test-2026" in enrolled

    installer = tmp_path / "Veyora-Pro-Setup-2.0.0.exe"
    installer.write_bytes(b"INERT INSTALLER PAYLOAD FOR SIGNATURE VERIFICATION")
    assert sign_update.main([str(installer), "--key", str(priv_key), "--key-id", "test-2026", "--tag", "v2.0.0"]) == 0
    assert sign_update.main([str(installer), "--tag", "v2.0.0", "--verify"]) == 0


def test_failed_download_card_shows_error_and_log_action():
    """A failed item must never abort the entire Downloads render."""
    app = DesktopApp()
    try:
        app.show_tab("Downloads")
        task = {
            "id": "failed-card-regression",
            "title": "Video with an error",
            "status": "Failed",
            "progress": 0,
            "settings": {"quality": "1080p", "format": "MP4", "download_subs": False},
            "error": "تحقق من بداية القص ونهايته",
        }
        app.create_download_card(task, 0)
        app._update_download_card(task)
        assert app._card_info_labels[task["id"]].cget("text") == task["error"]
        assert app._card_buttons[task["id"]]["errorlog"].winfo_manager() == "pack"
        assert app._card_buttons[task["id"]]["retry"].winfo_manager() == "pack"
    finally:
        app._on_close()
