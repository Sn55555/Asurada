"""Isolated, cancellable MLX synthesis for a versioned Asurada voice pack."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import wave
from contextlib import contextmanager
import fcntl

def synthesize(root, language, requests):
    import mlx.core as mx
    import mlx.nn as nn
    import numpy as np
    from mlx_audio.tts.utils import load_model
    cfg=json.loads((root/'voice.json').read_text())
    spec=cfg[language]
    model=None
    class Projection(nn.Module):
        def __init__(self, base, a, b):
            super().__init__()
            self.base,self.a,self.b=base,a,b
        def __call__(self,x):
            return self.base(x)+((x@self.a)@self.b).astype(x.dtype)
    for asset,text in requests:
        if not text.strip() or len(asset)!=64 or any(c not in '0123456789abcdef' for c in asset):
            raise ValueError('invalid race voice asset')
        dest=root/language/(asset+'.wav')
        dest.parent.mkdir(exist_ok=True)
        with (dest.parent/(asset+'.lock')).open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if dest.is_file():continue
            if model is None:
                model=load_model(cfg['base'])
                w=mx.load(str(root/spec['adapter']))
                layer=model.talker.model.layers[-1].self_attn
                for proj in ('q_proj','v_proj'):
                    pre=f'talker.model.layers.{len(model.talker.model.layers)-1}.self_attn.{proj}.'
                    setattr(layer,proj,Projection(getattr(layer,proj),w[pre+'a'],w[pre+'b']))
                model.extract_speaker_embedding=lambda *a,**k:w['asurada_voice']
            limit=max(120,len(text)*10)
            for seed in (42,137,192):
                mx.random.seed(seed)
                parts=list(model.generate(text=text.replace('隼人','笋人') if language=='zh' else text,
                    ref_audio=str(root/spec['prompt']),ref_text=spec['transcript'],
                    lang_code='chinese' if language=='zh' else 'japanese',temperature=.5,max_tokens=limit))
                if not parts or any(p.token_count>=limit for p in parts):continue
                x=np.concatenate([np.asarray(p.audio).ravel() for p in parts])
                if np.isfinite(x).all() and len(x)>=model.sample_rate*.2 and np.max(np.abs(x))>.015:break
            else:raise ValueError(f'failed to render {text}')
            with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
                p=Path(tmp)/'clip.wav'
                with wave.open(str(p),'wb') as f:
                    f.setparams((1,2,model.sample_rate,0,'NONE',''))
                    f.writeframes(np.rint(np.clip(x,-1,1)*32767).astype('<i2').tobytes())
                os.replace(p,dest)
            print(language,asset,text,flush=True)
        mx.clear_cache()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    parser.add_argument('language',choices=['zh','ja'])
    parser.add_argument('--play')
    args=parser.parse_args()
    requests=json.load(sys.stdin)
    synthesize(args.root,args.language,requests)
    if args.play:
        if len(requests)!=1:raise ValueError('play requires one line')
        os.execl(args.play,args.play,str(args.root/args.language/(requests[0][0]+'.wav')))
