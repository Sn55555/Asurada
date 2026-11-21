import json
import ast
import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import train_tyre_degradation_trend_baseline as tyre_module
import train_short_horizon_risk_forecast_baseline as risk_module
import pandas as pd
from regression_support import emit_result
from asurada.training_windows import future_windows
from train_tyre_degradation_trend_baseline import build_future_targets as tyre_targets
from train_short_horizon_risk_forecast_baseline import build_future_targets as risk_targets


def sample():
    return pd.DataFrame([dict(session_uid='18446744073709551614',session_epoch=0,split='train',record_id=f'r{i}',session_time_s=float(i),frame_identifier=i,
        tyre_compound='C3',tyre_age_laps=1,tyre_wear_pct=float(i),recent_front_overload_ratio=.1,
        wheel_slip_ratio_fl=.1,wheel_slip_ratio_fr=.1,wheel_slip_ratio_rl=.1,wheel_slip_ratio_rr=.1,
        current_risk_score=float(i),track_segment='entry' if i<2 else 'exit') for i in range(7)])


def run():
    data=sample();tyre=tyre_targets(df=data,horizon_s=3.,pd_module=pd);risk=risk_targets(df=data,horizon_s=3.,pd_module=pd)
    checks={'full_horizon_required':tyre['record_id'].tolist()==risk['record_id'].tolist()==['r0','r1','r2','r3'],
            'observed_tyre_delta':tyre['future_tyre_wear_delta'].tolist()==[3.,3.,3.,3.],
            'observed_risk_inside_horizon':risk['risk_forecast_3s'].tolist()==[3.,4.,5.,6.],
            'next_zone_not_invented':pd.isna(risk.iloc[-1]['risk_forecast_next_zone']),
            'provenance_has_interval':json.loads(tyre.iloc[0]['target_window'])['end_record_id']=='r3'}
    gap=data[data.session_time_s!=3.]
    checks['gap_not_bridged']=not list(future_windows(gap,horizon_s=3.))
    short=data.iloc[:3]
    checks['short_tail_not_labeled']=risk_targets(df=short,horizon_s=3.,pd_module=pd).empty
    for field,value in [('tyre_compound','C4'),('tyre_age_laps',0),('tyre_wear_pct',0.)]:
        changed=data.copy();changed.loc[3:,field]=value
        result=tyre_targets(df=changed,horizon_s=3.,pd_module=pd)
        checks['tyre_boundary_'+field]=all(i>=3 for i in result['session_time_s'])
    epochs=data.copy();epochs.loc[3:,'session_epoch']=1
    checks['epoch_not_crossed']=all(row['session_time_s']>=3 for row,_,_ in future_windows(epochs,horizon_s=3.))
    rewound=pd.concat([data.iloc[:3],data.iloc[:3]],ignore_index=True).drop(columns='session_epoch')
    checks['legacy_rewind_not_sorted_away']=not list(future_windows(rewound,horizon_s=3.))
    nulls=data.copy();nulls.loc[3,'tyre_wear_pct']=float('nan')
    checks['missing_wear_breaks_window']=tyre_targets(df=nulls,horizon_s=3.,pd_module=pd).empty
    for horizon in (0.,float('nan'),float('inf')):
        try:list(future_windows(data,horizon_s=horizon));checks['invalid_horizon_'+str(horizon)]=False
        except ValueError:checks['invalid_horizon_'+str(horizon)]=True
    with TemporaryDirectory() as temp:
        root=Path(temp)
        for module in (tyre_module,risk_module):
            extra=set()
            for node in ast.walk(ast.parse(Path(module.__file__).read_text())):
                if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('numeric_features','categorical_features') for t in node.targets):extra.update(ast.literal_eval(node.value))
            frame=pd.concat([sample().assign(session_uid='driver-session-'+s,split=s) for s in ('train','val','test')],ignore_index=True)
            for column in extra:
                if column not in frame:frame[column]=0
            frame['timing_support_level']='official_preferred';frame['session_type']='SprintRaceLike'
            frame['record_id']=[f'record-{i}' for i in range(len(frame))]
            label_fields=['fuel_risk_label','tyre_risk_label','ers_risk_label','race_control_risk_label','dynamics_risk_label','attack_opportunity_label','defend_risk_label','primary_action_label']
            labels=pd.DataFrame({'record_id':frame['record_id'],'session_uid':frame['session_uid'],'split':frame['split'],**{c:([1]*len(frame) if c!='primary_action_label' else ['NONE']*len(frame)) for c in label_fields}})
            frame=frame.drop(columns=[c for c in label_fields if c in frame])
            source=root/'features.csv';label_path=root/'labels.csv';frame.to_csv(source,index=False);labels.to_csv(label_path,index=False)
            received=[]
            def learner(**kwargs):
                received.append(kwargs['df'].copy());return {}
            args=SimpleNamespace(dataset=source,features=source,labels=label_path,output_dir=root/Path(module.__file__).stem,horizon_s=3.)
            with patch.object(module,'parse_args',return_value=args),patch.object(module,'train_single_model',side_effect=learner),contextlib.redirect_stdout(io.StringIO()):code=module.main()
            checks[Path(module.__file__).stem+'_main_passes_complete_windows']=code==0 and bool(received) and all(all(json.loads(w)['end_s']-json.loads(w)['start_s']>=3. for w in df['target_window']) for df in received)
            saved=pd.read_csv(args.output_dir/'target_windows.csv')
            checks[Path(module.__file__).stem+'_target_intervals_persisted']=len(saved)==len(received[0]) and 'target_window' in saved.columns
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
