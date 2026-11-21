import json,hashlib,collections,shutil,subprocess,sys,base64,struct
from pathlib import Path
ROOT=Path('/Users/sn5/Asurada'); OUT=ROOT/'output/community-retraining-20260915'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
p=ROOT/'asurada-core/data/community_telemetry/f1laps_f12025';m=json.loads((p/'manifest.json').read_text()); audit={'tracks':[],'channel_lap_counts':{},'hash_failures':[],'training_eligibility':'No community lap contains the complete physical inputs and target evidence required by existing 14 models; do not zero-fill missing physics or invent race labels.'}; counts=collections.Counter()
for t in m['tracks']:
 a={'track':t['track_name'],'laps':[]}
 for l in t['laps']:
  f=p/l['file'];d=json.loads(f.read_text())['original'];channels={k:len(v) for k,v in d.items() if isinstance(v,list) and v};counts.update(channels.keys());actual=digest(f)
  if actual!=l['sha256']:audit['hash_failures'].append(str(f))
  a['laps'].append({'file':str(f),'sha256':actual,'channels':channels,'manifest_sample_count':l['sample_count']})
 audit['tracks'].append(a)
audit['channel_lap_counts']=dict(counts);audit['lap_count']=sum(len(t['laps']) for t in m['tracks']);audit['track_count']=len(m['tracks']);audit['manifest_sample_count']=sum(l['sample_count'] for t in m['tracks'] for l in t['laps'])
# Inventory original UDP files via their binary packet header; no extraction or workspace changes.
audit['raw_captures']=[]
for f in [ROOT/'tools/captures/f1_25_udp_capture_20260321_024707.jsonl',ROOT/'asurada-core/data/capture_samples/f1_25_udp_capture_20260329_190623/f1_25_udp_capture_20260329_190623.jsonl']:
 sessions={};errors=0
 with f.open() as h:
  for line in h:
   try:
    d=json.loads(line);b=base64.b64decode(d['payload_base64']);v=struct.unpack_from('<HBBBBBQfIIBB',b);uid=str(v[6]);a=sessions.setdefault(uid,{'packets':0,'track_ids':[],'session_types':[]});a['packets']+=1
    if v[5]==1:
     s=struct.unpack_from('<BbbBHBBBHHBBBBBBBB',b,29)
     for k,val in [('track_ids',s[6]),('session_types',s[5])]:
      if val not in a[k]:a[k].append(val)
   except (KeyError,ValueError,struct.error):errors+=1
 audit['raw_captures'].append({'path':str(f),'sessions':sessions,'errors':errors})
 print('inventoried',f.name,flush=True)
(OUT/'data-audit.json').write_text(json.dumps(audit,indent=2))
# Immutable local input copy: upstream data and active model artifacts are not modified.
src=ROOT/'output/architecture-implementation/a12-current-training-export';dst=OUT/'dataset';dst.mkdir(exist_ok=True);manifest=json.loads((src/'manifest.json').read_text()); hashes={}
for key,val in list(manifest.items()):
 if key.endswith('_path') and isinstance(val,str) and val.endswith('.csv'):
  original=Path(val); original=original if original.is_absolute() else ROOT/original
  target=dst/original.name;shutil.copy2(original,target);hashes[original.name]=digest(target);manifest[key]=str(target)
(dst/'manifest.json').write_text(json.dumps(manifest,indent=2));(OUT/'input-hashes.json').write_text(json.dumps(hashes,indent=2))
code={str(f.relative_to(ROOT)):digest(f) for folder in [ROOT/'asurada-core/scripts',ROOT/'asurada-core/src/asurada'] for f in folder.rglob('*.py')}
(OUT/'code-hashes-before.json').write_text(json.dumps(code,indent=2))
cmd=[str(ROOT/'asurada-core/.venv/bin/python'),str(ROOT/'asurada-core/scripts/retrain_current_models.py'),'--dataset',str(dst),'--output-dir',str(OUT/'models')]
with (OUT/'retrain.stdout.txt').open('w') as out,(OUT/'retrain.stderr.txt').open('w') as err:r=subprocess.run(cmd,cwd=ROOT,stdout=out,stderr=err)
changed=[name for name,h in code.items() if digest(ROOT/name)!=h];(OUT/'run-status.json').write_text(json.dumps({'exit_code':r.returncode,'changed_code_during_run':changed,'command':cmd},indent=2));print('retrain completed',r.returncode,'code changes',changed,flush=True)
