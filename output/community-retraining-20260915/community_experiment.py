"""Exploratory distance-ahead speed forecast. No future features or full-lap-derived semantics."""
import os
os.environ['OMP_NUM_THREADS']='1'
import json,hashlib,collections
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
ROOT=Path('/Users/sn5/Asurada');OUT=ROOT/'output/community-retraining-20260915/community-experiment';OUT.mkdir(exist_ok=True)
P=ROOT/'asurada-core/data/community_telemetry/f1laps_f12025';M=json.loads((P/'manifest.json').read_text());channels=['speed','brake','throttle','steer','gear','drs']
# Physical circuits and their reverse variants share a split. Deterministic assignment before loading outcomes.
group=lambda s:s.removesuffix('_reverse')
groups=sorted({group(t['profile_slug']) for t in M['tracks']},key=lambda s:hashlib.sha256(('community-v1:'+s).encode()).hexdigest())
assignment={g:('test' if i<5 else 'val' if i<9 else 'train') for i,g in enumerate(groups)}
rows=[];manifest=[]
for t in M['tracks']:
 for lap in t['laps']:
  f=P/lap['file'];b=f.read_bytes();assert hashlib.sha256(b).hexdigest()==lap['sha256'];d=json.loads(b)['original'];series={}
  for c in channels:
   # Last observation at duplicate distances; restrict interpolation to measured domain.
   points={float(p['x']):float(p['y']) for p in d[c] if np.isfinite(float(p['x'])) and np.isfinite(float(p['y']))}
   x=np.array(sorted(points));y=np.array([points[v] for v in x]);series[c]=(x,y)
  lo=max(s[0][0] for s in series.values());hi=min(s[0][-1] for s in series.values());grid=np.arange(np.ceil((lo+30)/10)*10,hi-50,10)
  a={'track':t['profile_slug'],'lap_id':lap['lap_id'],'split':assignment[group(t['profile_slug'])],'distance_m':grid}
  # Use only samples at/before the query point for inputs; no interpolation using future observations.
  for c,(x,y) in series.items():
   for lag in [0,10,30]:a[c+'_lag'+str(lag)]=y[np.searchsorted(x,grid-lag,side='right')-1]
  x,y=series['speed'];a['future_speed_50m']=np.interp(grid+50,x,y);a['speed_delta_50m']=a['future_speed_50m']-a['speed_lag0'];rows.append(pd.DataFrame(a));manifest.append({'file':str(f),'sha256':lap['sha256'],'track':t['profile_slug'],'split':a['split'],'rows':len(grid)})
df=pd.concat(rows,ignore_index=True);features=[c for c in df if '_lag' in c];parts={s:df[df.split==s] for s in ['train','val','test']}
assert all(set(parts[a].lap_id).isdisjoint(parts[b].lap_id) for a,b in [('train','val'),('train','test'),('val','test')])
assert all({group(t) for t in parts[a].track}.isdisjoint({group(t) for t in parts[b].track}) for a,b in [('train','val'),('train','test'),('val','test')])
model=lgb.LGBMRegressor(objective='regression',n_estimators=600,learning_rate=.04,num_leaves=31,min_child_samples=60,n_jobs=1,random_state=42,verbosity=-1)
model.fit(parts['train'][features],parts['train'].speed_delta_50m,eval_set=[(parts['val'][features],parts['val'].speed_delta_50m)],callbacks=[lgb.early_stopping(40,verbose=False)])
model.booster_.save_model(str(OUT/'speed_delta_50m_lightgbm.txt'));test=parts['test'].copy();test['predicted_future_speed']=test.speed_lag0+model.predict(test[features]);test['persistence_speed']=test.speed_lag0
# A second simple baseline: project observed 30 m speed change linearly to 50 m.
test['linear_speed']=np.clip(test.speed_lag0+(test.speed_lag0-test.speed_lag30)*50/30,0,400)
def metrics(a):
 return {name:{'mae_kph':float(mean_absolute_error(a.future_speed_50m,a[col])),'rmse_kph':float(np.sqrt(mean_squared_error(a.future_speed_50m,a[col]))),'r2':float(r2_score(a.future_speed_50m,a[col]))} for name,col in [('model','predicted_future_speed'),('persistence','persistence_speed'),('linear','linear_speed')]}
report={'scope':'EXPERIMENTAL additional model, not one of the 14 runtime models; predicts recorded speed 50 m ahead, not optimal driving advice or causal action benefit. Best-lap selection limits generalization.', 'algorithm':'LightGBM regression, 18 current/past channel values, no future or track semantic features','features':features,'assignment':assignment,'best_iteration':model.best_iteration_,'rows':{s:len(d) for s,d in parts.items()},'tracks':{s:sorted(d.track.unique()) for s,d in parts.items()},'test':metrics(test),'per_track':{t:{'rows':len(a),'metrics':metrics(a)} for t,a in test.groupby('track')},'per_lap':{t:{'rows':len(a),'metrics':metrics(a)} for t,a in test.groupby('lap_id')},'source_files':manifest}
# Lap-cluster bootstrap describes uncertainty within heldout tracks, not unseen-population guarantees.
perlap=test.groupby('lap_id').apply(lambda a:pd.Series({'n':len(a),'gain':np.abs(a.future_speed_50m-a.persistence_speed).sum()-np.abs(a.future_speed_50m-a.predicted_future_speed).sum()}),include_groups=False)
rng=np.random.default_rng(42);arr=perlap[['n','gain']].to_numpy();boot=[]
for _ in range(2000):
 sample=arr[rng.integers(0,len(arr),len(arr))];boot.append(sample[:,1].sum()/sample[:,0].sum())
report['lap_bootstrap_mae_gain_vs_persistence_95pct_kph']=np.quantile(boot,[.025,.975]).tolist()
(OUT/'report.json').write_text(json.dumps(report,indent=2));test.to_csv(OUT/'test-predictions.csv',index=False);print(json.dumps({k:report[k] for k in ['rows','tracks','test','lap_bootstrap_mae_gain_vs_persistence_95pct_kph']},indent=2))
