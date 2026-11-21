import sys,json
from pathlib import Path
import pandas as pd
R=Path('/Users/sn5/Asurada');O=R/'output/community-retraining-20260915';sys.path.insert(0,str(R/'asurada-core/scripts'))
from train_rival_pressure_baseline import compute_front_pressure_target,filter_race_like_rows
f=pd.read_csv(O/'dataset/features.csv',dtype={'session_uid':'string'},low_memory=False);l=pd.read_csv(O/'dataset/labels.csv',dtype={'session_uid':'string'},low_memory=False)
a=f[(f.split=='test')&(f.timing_support_level=='official_preferred')];b=l[l.record_id.isin(a.record_id)];front=filter_race_like_rows(a).apply(compute_front_pressure_target,axis=1)
def stats(s):return {'rows':len(s),'unique':int(s.nunique()),'min':float(s.min()),'max':float(s.max()),'variance':float(s.var(ddof=0))}
d={'fuel_test_target':stats(b.fuel_risk_label),'front_test_target':stats(front),'front_official_gap_nonnull':int(a.official_gap_ahead_s.notna().sum()),'scope':'Matched current holdout records; constant-label R2 cannot measure risk discrimination.'}
(O/'label-diagnosis.json').write_text(json.dumps(d,indent=2));print(json.dumps(d,indent=2))
