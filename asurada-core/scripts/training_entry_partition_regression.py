import ast
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
from regression_support import emit_result

NAMES=('attack_opportunity','front_attack_commit','rear_threat','yield_vs_defend','event_impact','counterattack_window')


def run():
    checks={};scripts=Path(__file__).resolve().parent
    with TemporaryDirectory() as temp:
        root=Path(temp)
        for name in NAMES:
            script=scripts/('train_'+name+'_baseline.py')
            columns=set();targets=set()
            for node in ast.walk(ast.parse(script.read_text())):
                if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('numeric_features','categorical_features') for t in node.targets):
                    columns.update(ast.literal_eval(node.value))
                if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='target_column' for t in node.targets):targets.add(ast.literal_eval(node.value))
            columns.update(targets);columns.update(('split','session_uid','primary_action_label','yield_vs_fight_proxy_label','timing_support_level','session_type','official_gap_confidence_behind','event_code'))
            path=root/(name+'.csv')
            with path.open('w') as handle:
                writer=csv.DictWriter(handle,fieldnames=sorted(columns));writer.writeheader()
                for index,split in enumerate(('train','val','test')):
                    row={c:0 for c in columns}
                    row.update(split=split,session_uid='18446744073709551614',primary_action_label='DEFEND_WINDOW',yield_vs_fight_proxy_label='defend',timing_support_level='official_preferred',session_type='SprintRaceLike',official_gap_confidence_behind='high',event_code='COLL')
                    for target in targets:row[target]=index%2
                    writer.writerow(row)
            result=subprocess.run([sys.executable,str(script),'--dataset',str(path),'--output-dir',str(root/name)],capture_output=True,text=True,timeout=30)
            checks[name+'_rejects_same_session_holdout']=result.returncode!=0 and 'session_crosses_exported_partitions' in result.stderr
            if name=='attack_opportunity':
                with path.open('w') as handle:
                    writer=csv.DictWriter(handle,fieldnames=sorted(columns));writer.writeheader()
                    for group,split in enumerate(('train','val','test')):
                        for index in range(100):
                            row={c:0 for c in columns}
                            row.update(split=split,session_uid=str(18446744073709551610+group),primary_action_label='DEFEND_WINDOW',yield_vs_fight_proxy_label='defend',timing_support_level='official_preferred',session_type='SprintRaceLike',official_gap_confidence_behind='high',event_code='COLL')
                            for target in targets:row[target]=index%2
                            if 'speed_kph' in row:row['speed_kph']=100+(index%2)*100
                            writer.writerow(row)
                fitted=subprocess.run([sys.executable,str(script),'--dataset',str(path),'--output-dir',str(root/'fitted')],capture_output=True,text=True,timeout=30)
                import json
                reports=list((root/'fitted').glob('*report.json'))
                saved=json.loads(reports[0].read_text()) if reports else {}
                checks['disjoint_data_trains_and_records_uid_manifest']=fitted.returncode==0 and saved.get('partition',{}).get('sessions')=={'train':['18446744073709551610'],'val':['18446744073709551611'],'test':['18446744073709551612']}
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
