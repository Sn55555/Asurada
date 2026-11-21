"""Exercise the local review profile through real CLI subprocesses and SQLite."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import asurada
from regression_support import emit_result

SCENARIO = r'''
import json, os, subprocess, sys
from pathlib import Path
from asurada.training_memory import TrainingMemory
from asurada.workflow_store import WorkflowStore
from asurada.session_review_workflow import run_session_review
base=Path(sys.argv[1]); now=[1000.]
memory=TrainingMemory(base/'expiry.db',clock=lambda:now[0])
memory.set_review_detail(driver='one',detail='brief',ttl_s=10)
original=memory.query(driver='one',kind='user_preference')
now[0]+=2
memory.set_review_detail(driver='one',detail='brief',ttl_s=10)
checks={'retry_preserves_expiry':memory.query(driver='one',kind='user_preference')==original,
        'driver_isolation':not memory.query(driver='two',kind='user_preference')}
memory.set_review_detail(driver='one',detail='detailed',ttl_s=10)
checks['explicit_update']=memory.query(driver='one',kind='user_preference')[0]['value']=='detailed'
now[0]+=11
checks['expired_unavailable']=not memory.query(driver='one',kind='user_preference')
source=base/'input.jsonl'
source.write_text('\n'.join(json.dumps({'session_uid':'s','session_epoch':0,'track':'Suzuka','lap_number':lap+1,'source_timestamp_ms':lap*1000,'raw':{'last_lap_time_ms':duration}}) for lap,duration in [(1,100000),(2,99000),(3,98500)]))
store=WorkflowStore(base/'review.db')
run_session_review(store,task_id='review',source=source,driver_id='one')
before=store.get('review')
def cli(*args,driver='one',success=True):
    p=subprocess.run([sys.executable,'-m','asurada.review_profile','--database',str(store.path),'--driver-id',driver,*args],env=os.environ,text=True,capture_output=True)
    assert (p.returncode==0)==success,(args,p.stdout,p.stderr)
    return json.loads(p.stdout)
default=cli('show','--task-id','review')
checks['default_detailed']=default['detail']=='detailed' and bool(default['report']['source_sha256'])
cli('set-detail','brief')
brief=cli('show','--task-id','review')
checks['cli_preference_consumed']=brief['detail']=='brief' and 'report' not in brief and brief['preference']['evidence'][0]['origin']=='explicit_user_input'
checks['brief_keeps_evidence']=brief['source_sha256']==default['source_sha256'] and brief['comparisons']==default['report']['comparisons'] and brief['limitation']==default['limitation'] and brief['full_report']['task_id']=='review'
checks['cli_other_driver_isolated']=not cli('preferences',driver='two')['preferences']
checks['other_driver_cannot_read_review']=cli('show','--task-id','review',driver='two',success=False)['status']=='failed'
cli('set-detail','detailed')
checks['cli_update']=cli('show','--task-id','review')['detail']=='detailed'
cli('revoke-detail'); cli('revoke-detail')
checks['cli_revoke']=not cli('preferences')['preferences'] and cli('show','--task-id','review')['preference'] is None
recorded=cli('record-performance','--task-id','review')
observations=cli('show','--task-id','review')['verified_observations']
checks['performance_saved_and_consumed']=len(recorded['memory_ids'])==1 and len(observations)==1 and observations[0]['value']['delta_ms']==-1500
checks['performance_has_bound_evidence']=observations[0]['evidence'][0]['source_sha256']==default['source_sha256'] and observations[0]['evidence'][0]['interpretation']=='observed_lap_delta_not_causal_effect' and len(observations[0]['verification']['evidence_snapshots'])==2
cli('record-performance','--task-id','review')
checks['performance_retry_preserves_record']=cli('show','--task-id','review')['verified_observations']==observations
checks['performance_owner_enforced']=cli('record-performance','--task-id','review',driver='two',success=False)['status']=='failed'
from asurada.review_profile import record_performance
expired=TrainingMemory(store.path.with_suffix('.memory.sqlite3'),clock=lambda:10**12)
try:
    record_performance(store=store,memory=expired,driver='one',task_id='review')
    checks['expired_fact_not_reverified']=False
except ValueError:
    checks['expired_fact_not_reverified']=True
empty=base/'empty.jsonl';empty.write_text('')
run_session_review(store,task_id='empty',source=empty,driver_id='one')
empty_record=cli('record-performance','--task-id','empty')
checks['no_data_no_performance']=empty_record['status']=='insufficient_laps' and not empty_record['memory_ids'] and not cli('show','--task-id','empty')['verified_observations']
checks['immutable_task_untouched']=store.get('review')==before
checks['invalid_ttl_rejected']=cli('set-detail','brief','--ttl-days','nan',success=False)['status']=='failed'
print(json.dumps({'passed':all(checks.values()),'checks':checks}))
raise SystemExit(0 if all(checks.values()) else 1)
'''


def run():
    with TemporaryDirectory(prefix='asurada-profile-regression-') as temporary:
        package_root = str(Path(asurada.__file__).resolve().parent.parent)
        env = dict(os.environ, PYTHONPATH=package_root, ASURADA_TTS_BACKEND='null',
                   ASURADA_RUNTIME_DIR=str(Path(temporary)/'runtime'))
        result = subprocess.run([sys.executable, '-c', SCENARIO, temporary],
                                env=env, cwd=temporary, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return json.loads(result.stdout)


if __name__ == '__main__':
    emit_result(run())
