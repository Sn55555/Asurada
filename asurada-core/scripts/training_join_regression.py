from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import pandas as pd
from regression_support import emit_result
from asurada.training_join import join_training_labels


def run():
    features=pd.DataFrame([dict(record_id=f'r{i}',session_uid=str(18446744073709551610+i),split=s,x=i) for i,s in enumerate(('train','val','test'))])
    labels=features.drop(columns='x').assign(target=[1,2,3])
    merged,manifest=join_training_labels(features,labels.iloc[::-1],targets=['target'])
    checks={'one_to_one_preserves_feature_order':merged.record_id.tolist()==['r0','r1','r2'] and merged.target.tolist()==[1,2,3],
            'identity_manifest':manifest['rows']==3 and len(manifest['identity_sha256'])==64,
            'order_independent_manifest':join_training_labels(features.iloc[::-1],labels,targets=['target'])[1]==manifest}
    cases={'duplicate':pd.concat([labels,labels.iloc[:1]],ignore_index=True),'missing':labels.iloc[:2],
        'wrong_uid':labels.assign(session_uid=['wrong',*labels.session_uid.tolist()[1:]]),
        'wrong_split':labels.assign(split=['val','val','test'])}
    for name,bad in cases.items():
        try:join_training_labels(features,bad,targets=['target']);checks[name+'_rejected']=False
        except ValueError:checks[name+'_rejected']=True
    with TemporaryDirectory() as temp:
        root=Path(temp);source=root/'features.csv';target=root/'labels.csv';features.to_csv(source,index=False)
        bad=cases['wrong_uid'].copy()
        for column in ('primary_action_label','fuel_risk_label','ers_risk_label','tyre_risk_label','dynamics_risk_label','race_control_risk_label','attack_opportunity_label','defend_risk_label'):
            bad[column]='NONE' if column=='primary_action_label' else 1
        bad.to_csv(target,index=False)
        for name in ('resource_risk_baselines','defence_cost_baseline','rival_pressure_baseline','short_horizon_risk_forecast_baseline'):
            script=Path(__file__).resolve().parent/('train_'+name+'.py')
            result=subprocess.run([sys.executable,str(script),'--features',str(source),'--labels',str(target),'--output-dir',str(root/name)],capture_output=True,text=True,timeout=30)
            checks[name+'_entry_rejects_foreign_label']=result.returncode!=0 and 'training_label_identity_mismatch: session_uid' in result.stderr
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
