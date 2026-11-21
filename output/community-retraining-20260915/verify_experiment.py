import json
from pathlib import Path
import pandas as pd,numpy as np
from sklearn.metrics import r2_score
O=Path('/Users/sn5/Asurada/output/community-retraining-20260915/community-experiment');d=json.loads((O/'report.json').read_text());f=pd.read_csv(O/'test-predictions.csv');e=np.abs(f.future_speed_50m-f.predicted_future_speed)
assert len(f)==d['rows']['test'] and np.isfinite(f.select_dtypes('number')).all().all()
assert set(f.track)==set(d['tracks']['test'])
a={'prediction_rows_verified':len(f),'delta_r2':float(r2_score(f.speed_delta_50m,f.predicted_future_speed-f.speed_lag0)),'absolute_error_p95_kph':float(np.quantile(e,.95)),'large_deceleration_gt30kph':{'rows':int((f.speed_delta_50m < -30).sum()),'mae_kph':float(e[f.speed_delta_50m < -30].mean())},'all_test_tracks_beat_persistence':all(v['metrics']['model']['mae_kph']<v['metrics']['persistence']['mae_kph'] for v in d['per_track'].values()),'scope':'Offline heldout-lap numerical checks, not runtime integration or live driving acceptance'}
(O/'verification.json').write_text(json.dumps(a,indent=2));print(json.dumps(a,indent=2))
