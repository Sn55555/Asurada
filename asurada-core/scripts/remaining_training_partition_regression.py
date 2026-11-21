import ast
import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import subprocess
import sys
import pandas as pd
from regression_support import emit_result
import train_driver_style_baseline as style
from train_tyre_degradation_trend_baseline import assign_trend_split
from train_short_horizon_risk_forecast_baseline import assign_forecast_split
from train_rival_pressure_baseline import derive_split
from train_defence_cost_baseline import derive_defence_cost_split

NAMES=('driver_style','tyre_degradation_trend','short_horizon_risk_forecast','rival_pressure','defence_cost','strategy_action')


def run():
    checks={};scripts=Path(__file__).resolve().parent
    with TemporaryDirectory() as temp:
        root=Path(temp);leaked=root/'leaked.csv'
        pd.DataFrame([dict(session_uid='18446744073709551614',split=s) for s in ('train','val','test')]).to_csv(leaked,index=False)
        for name in NAMES:
            flag='--dataset' if name in ('driver_style','tyre_degradation_trend') else '--features'
            result=subprocess.run([sys.executable,str(scripts/('train_'+name+'_baseline.py')),flag,str(leaked),'--output-dir',str(root/name)],capture_output=True,text=True,timeout=30)
            checks[name+'_rejects_leak_before_transform']=result.returncode!=0 and 'session_crosses_exported_partitions' in result.stderr
        checks['derived_splits_ignore_laps_and_types']=all(fn(dict(split=s,session_type=t,lap_number=n))==s for fn in (assign_trend_split,assign_forecast_split,derive_split,derive_defence_cost_split) for s in ('train','val','test') for t in ('FeatureRaceLike','SprintRaceLike') for n in (1,2,3))
        source=scripts/'train_driver_style_baseline.py';columns=set()
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node,ast.Assign):
                names={t.id for t in node.targets if isinstance(t,ast.Name)}
                if 'numeric_columns' in names:columns.update(ast.literal_eval(node.value))
                if 'agg_map' in names:columns.update(ast.literal_eval(node.value))
        columns.update(('drs_available','timing_support_level'))
        rows=[]
        for group,s in enumerate(('train','val','test')):
            for n in range(6):
                row={c:0 for c in columns}
                row.update(session_uid=str(18446744073709551610+group),split=s,session_time_s=n*10.,speed_kph=150+n,session_type='SprintRaceLike',track='Suzuka',sample_name=s,timing_support_level='official_preferred')
                rows.append(row)
        dataset=root/'style.csv';pd.DataFrame(rows).to_csv(dataset,index=False)
        received=[]
        def learner(**kwargs):
            received.append({s:set(kwargs[s+'_df']['session_uid']) for s in ('train','val','test')});return {}
        with patch.object(style,'parse_args',return_value=SimpleNamespace(dataset=dataset,output_dir=root/'style-fit',window_s=20.)),patch.object(style,'train_regressor',side_effect=learner),patch.object(style,'train_classifier',side_effect=learner),contextlib.redirect_stdout(io.StringIO()):
            code=style.main()
        expected={s:{str(18446744073709551610+i)} for i,s in enumerate(('train','val','test'))}
        checks['window_aggregation_preserves_full_session_scope']=code==0 and len(received)==3 and all(item==expected for item in received)
        saved=json.loads((root/'style-fit/driver_style_baseline_report.json').read_text())
        checks['style_report_manifest']=saved['partition']['unit']=='session_uid' and saved['partition']['rows']=={'train':3,'val':3,'test':3}
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
