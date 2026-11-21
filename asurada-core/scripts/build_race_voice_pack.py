"""Build whole sentences using the existing candidate adapters. Resume an identical build safely."""
import argparse,json,shutil,subprocess,sys,hashlib
from pathlib import Path
core=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(core/'src'))
from asurada.race_voice_catalog import key,phrases
p=argparse.ArgumentParser()
p.add_argument('--candidates',type=Path,default=core.parent/'output/jp-voice-v1')
p.add_argument('--root',type=Path,required=True)
p.add_argument('--runtime',type=Path,default=Path.home()/'.asurada/voice/asurada-zh-v1')
args=p.parse_args()
root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
c=args.candidates
cfg={'base':str(args.runtime.resolve()/'model'),'python':str(args.runtime.resolve()/'.venv/bin/python')}
ja=next(r for r in map(json.loads,(c/'training/clean-corpus.jsonl').read_text().splitlines()) if r['audio'].endswith('/report-415.67.wav'))
for lang,weights,prompt,script in [('zh',c/'training/clean-31.safetensors',c/'training/pilot8-dev/development-explanation-2.wav','你的判断正确。刚才的数据已经更新。'),('ja',c/'japanese/asurada-ja-31.safetensors',Path(ja['audio']),ja['text'])]:
    spec={'adapter':lang+'.safetensors','prompt':lang+'-prompt.wav','transcript':script}
    for src,dst in [(weights,root/spec['adapter']),(prompt,root/spec['prompt'])]:
        if dst.exists() and dst.read_bytes()!=src.read_bytes():raise ValueError('use a new pack directory for changed voice')
        if not dst.exists():shutil.copyfile(src,dst)
    cfg[lang]=spec
(root/'voice.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
catalog={}
for category,zh,ja in phrases():
    record={'category':category,'zh':zh,'ja':ja}
    if key(zh) in catalog and catalog[key(zh)]!=record:raise ValueError(zh)
    catalog[key(zh)]=record
worker=core/'src/asurada/race_voice_render.py'
for lang in ('zh','ja'):
    batch=[[key(r[lang]),r[lang]] for r in catalog.values()]
    subprocess.run([cfg['python'],str(worker),str(root),lang],input=json.dumps(batch),text=True,check=True)
cache=root/'catalog.json.tmp'
cache.write_text(json.dumps(catalog,ensure_ascii=False,indent=2))
cache.replace(root/'catalog.json')
