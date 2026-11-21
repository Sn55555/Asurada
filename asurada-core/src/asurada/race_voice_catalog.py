"""Whole utterances for the cache-only race radio backend."""
from pathlib import Path
import hashlib
import re
from .wheel_telemetry import WHEEL_NAMES, TYRE_DAMAGE_WARNING_PCT, spoken_percent
from .wing_damage import FRONT_WING_WARNING_PCT, SIDES, wing_radio_text

def key(text):
    # Ignore layout differences, retain punctuation, digits and word order.
    return hashlib.sha256(re.sub(r'\s+', '', text).encode()).hexdigest()

def phrases():
    for line in Path(__file__).with_name('voice_assets').joinpath('radio.tsv').read_text().splitlines():
        yield tuple(line.split('\t'))
    for i, word in enumerate('一二三',1):
        yield 'brake_countdown', word, ['いち','に','さん'][i-1]
    for i, side in enumerate(SIDES):
        jp = ['左','右'][i]
        for pct in sorted(set(range(30,101,5)) | {31,54,55,59,88}):
            zh = wing_radio_text([side], levels={side:pct})
            yield 'wing', zh, f'{jp}フロントウイングに損傷。損傷率{pct}パーセント。フロントのグリップが低下する可能性がある。'
    for wheel, jp in zip(WHEEL_NAMES.values(), ['左リア','右リア','左フロント','右フロント']):
        for pct in range(TYRE_DAMAGE_WARNING_PCT,101,5):
            yield 'tyre_damage',f'轮胎受损。{wheel}，{spoken_percent(pct)}。', f'タイヤに損傷。{jp}、{pct}パーセント。'
            yield 'tyre_wear',f'{wheel[:-1]}这条胎，磨损{spoken_percent(pct)}。', f'{jp}タイヤ、摩耗率{pct}パーセント。'
    for name,jp in [('加斯利','ガスリー'),('安东内利','アントネッリ'),('科拉平托','コラピント'),('比尔曼','ベアマン'),('勒克莱尔','ルクレール'),('劳森','ローソン')]:
        for place,loc in [('直道末端','ストレートエンド'),('主直道尽头','メインストレートの終端')]:
            yield 'attack',f'{place}找机会，前面是{name}。',f'{loc}で仕掛けろ。前は{jp}だ。'
            yield 'attack',f'{place}找机会，你在追近{name}。',f'{loc}で仕掛けろ。{jp}との差が縮んでいる。'
        yield 'defence',f'防{name}，直道末端。',f'{jp}に注意。ストレートエンドを守れ。'
        yield 'defence',f'防{name}，直道末端，追得快。',f'{jp}に注意。ストレートエンドだ。急速に接近している。'
