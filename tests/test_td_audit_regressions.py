"""Source-audit regressions for clip parsing, FFmpeg pause and subtitle cache."""
import math
from types import SimpleNamespace

import pytest

from media_clipping import clip_interval, time_seconds
from translator.subtitle_generator import generate_srt, parse_srt
from translator.video_renderer import get_ffprobe_info, run_ffmpeg


@pytest.mark.parametrize("value", [
    "1e1", "1E1", "1_0", "+5", "-5", "1.5:00", "1:3.5:00",
    " 1 :20", "00:1e1", "01::12", "10:60", "00:60:00", "NaN", "inf",
    "", "12:", "0:00:60", "00:00:00,1", "1:2:3:4",
])
def test_clip_time_rejects_float_syntax_and_invalid_fields(value):
    with pytest.raises(ValueError, match='Invalid clip time'):
        time_seconds(value)


@pytest.mark.parametrize("value,expected", [
    ("13", 13), ("00:00:13", 13), ("2:13", 133), ("01:02:03", 3723),
    ("01:02:03.25", 3723.25), ("١٢:٣٤", 754), ("00:00:١٣", 13),
])
def test_clip_time_supports_normal_and_arabic_indic_digits(value,expected):
    assert time_seconds(value) == expected


@pytest.mark.parametrize("duration", [float('nan'), float('inf'), -1, 0, "unavailable"])
def test_clip_interval_rejects_missing_or_invalid_media_duration(duration):
    with pytest.raises(ValueError, match='Media duration is invalid'):
        clip_interval('00:00:01', '00:00:03', duration)


def test_clip_ffmpeg_keeps_actual_precise_timing(tmp_path):
    """Real local FFmpeg integration, not simulated processing."""
    from media_clipping import clip_media
    source = tmp_path / 'source.mp4'
    run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=20:d=4',
                '-f', 'lavfi', '-i', 'sine=frequency=450:duration=4',
                '-c:v', 'libx264', '-threads', '2', '-c:a', 'aac', source])
    result = clip_media(source, tmp_path / 'clips', '00:00:01', '00:00:02.5')
    info = get_ffprobe_info(result)
    assert result.is_file() and source.is_file()
    assert math.isclose(float(info['format']['duration']), 1.5, abs_tol=.3)
    assert {'video', 'audio'} <= {stream['codec_type'] for stream in info['streams']}
    assert source.stat().st_size > 0


def test_srt_invalid_export_does_not_clobber_prior_good_file(tmp_path):
    output = tmp_path / 'existing.srt'
    generate_srt([SimpleNamespace(start=0, end=1, text='مرحبا')], output)
    original = output.read_bytes()
    with pytest.raises(ValueError):
        generate_srt([SimpleNamespace(start=1, end=1, text='invalid')], output)
    assert output.read_bytes() == original
    assert parse_srt(output)[0].text == 'مرحبا'


def test_long_pause_does_not_trigger_false_ffmpeg_stall(monkeypatch):
    """Synthetic subprocess timing check; actual FFmpeg is tested separately."""
    import io
    import time
    from translator import video_renderer

    class FakeProcess:
        stdout = io.StringIO('')
        returncode = 0
        polls = 0
        def poll(self):
            self.polls += 1
            return None if self.polls == 1 else 0

    monkeypatch.setattr(video_renderer.subprocess, 'Popen', lambda *_a, **_kw: FakeProcess())
    checkpoint_calls = 0

    def pause_once():
        nonlocal checkpoint_calls
        checkpoint_calls += 1
        if checkpoint_calls == 2:
            time.sleep(.25)

    video_renderer.run_ffmpeg([], checkpoint=pause_once, stall_timeout=.15)
    assert checkpoint_calls >= 3


def test_user_concurrency_settings_cannot_exceed_actual_queue_limit():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).parents[1] / 'desktop_ui.py').read_text(encoding='utf8'))
    desktop = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'DesktopApp')
    for method_name in ('save_settings_action', 'show_advanced'):
        method = next(node for node in desktop.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
        clamps = [node.args[0].value for node in ast.walk(method)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == 'min' and len(node.args) == 2
                  and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, int)]
        assert 5 in clamps and 8 not in clamps


@pytest.mark.parametrize("segments", [
    [dict(start=3,end=4,text='late'),dict(start=1,end=2,text='early')],
    [dict(start=True,end=2,text='boolean start')],
    [dict(start=0,end=0,text='zero duration')],
    [dict(start=0,end=2,text='')],
    [dict(start=0,end=float('inf'),text='infinite end')],
])
def test_invalid_saved_transcript_is_not_reused(segments, tmp_path):
    import json
    from translator.pipeline import _read_cache
    path = tmp_path / 'transcript.json'
    path.write_text(json.dumps({'segments':segments}),encoding='utf8')
    assert _read_cache(path) is None


def test_valid_chronological_cached_transcript_is_preserved(tmp_path):
    import json
    from translator.pipeline import _read_cache
    path = tmp_path / 'transcript.json'
    path.write_text(json.dumps({'segments':[
        dict(start=0,end=3,text='مرحبا'),
        dict(start=2.5,end=4,text='overlap allowed'),
    ]}),encoding='utf8')
    items = _read_cache(path)
    assert [(x.start,x.end,x.text) for x in items] == [
        (0,3,'مرحبا'),(2.5,4,'overlap allowed')]
