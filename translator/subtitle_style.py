"""Resolution-aware ASS styling shared by preview and final export."""
import re
from pathlib import Path

DEFAULT = dict(size_percent=3.6, color='#FFFFFF', outline=1.0, margin_percent=5.0, position='bottom')


def normalize_style(value=None):
    value = {**DEFAULT, **(value or {})}
    result = {}
    for key, low, high in [('size_percent', 1, 10), ('outline', 0, 5), ('margin_percent', 0, 35)]:
        number = float(value[key])
        if not low <= number <= high:
            raise ValueError('Invalid subtitle style: ' + key)
        result[key] = number
    color = str(value['color'])
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Use a subtitle color like #FFFFFF')
    result['color'] = color.upper()
    result['position'] = value['position']
    if result['position'] not in ('bottom', 'top'):
        raise ValueError('Invalid subtitle position')
    return result


def make_ass(srt, destination, width, height, style=None):
    from .subtitle_generator import parse_srt
    style = normalize_style(style)
    rgb = style['color'][1:]
    color = '&H00' + rgb[4:6] + rgb[2:4] + rgb[:2]
    fontsize = max(8, round(height * style['size_percent'] / 100, 2))
    outline = height / 720 * style['outline']
    margin = round(height * style['margin_percent'] / 100)
    alignment = 2 if style['position'] == 'bottom' else 8
    text = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{fontsize},{color},{color},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{outline},0,{alignment},{round(width*.04)},{round(width*.04)},{margin},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    def timestamp(seconds):
        total = round(seconds * 100)
        h, rest = divmod(total, 360000)
        m, rest = divmod(rest, 6000)
        sec, cs = divmod(rest, 100)
        return f'{h}:{m:02}:{sec:02}.{cs:02}'
    for segment in parse_srt(srt):
        # Never interpret subtitle content as ASS overrides.
        cue = segment.text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', r'\N')
        text += f'Dialogue: 0,{timestamp(segment.start)},{timestamp(segment.end)},Default,,0,0,0,,{cue}\n'
    Path(destination).write_text(text, encoding='utf-8-sig')
