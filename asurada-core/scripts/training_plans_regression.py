import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from regression_support import emit_result
from corner_review_regression import rows, analyze
from asurada.training_plans import TrainingPlanStore
from asurada.task_runtime import TaskContext
from asurada.session_review_workflow import run_session_review
from asurada.workflow_store import WorkflowStore


def run():
    checks={}
    with TemporaryDirectory() as temp:
        root=Path(temp);now=[1000.]
        store=TrainingPlanStore(root/'plans.db',clock=lambda:now[0])
        report=analyze(rows())
        def process(review,driver='one'):
            return store.process_review(driver=driver,review=review,context=TaskContext.start('plans',2000))
        result=process(report);draft=result['draft'];identity=draft['id']
        checks['three_lap_evidence_draft']=len(draft['baseline_laps'])==3 and draft['baseline_spread_ms']==200 and not result['outcomes']
        process(report)
        checks['draft_retry_idempotent']=len(store.list('one'))==1 and store.list('one')[0]['status']=='draft'
        checks['driver_isolation']=not store.list('two')
        try:store.activate(driver='two',plan_id=identity,after_lap=3);checks['other_driver_cannot_activate']=False
        except KeyError:checks['other_driver_cannot_activate']=True
        try:store.activate(driver='one',plan_id=identity,after_lap=2);checks['baseline_cannot_count_as_followup']=False
        except ValueError:checks['baseline_cannot_count_as_followup']=True
        store.activate(driver='one',plan_id=identity,after_lap=4)
        store.activate(driver='one',plan_id=identity,after_lap=4)
        checks['old_laps_do_not_assess']=not process(report)['outcomes']
        observation=copy.deepcopy(draft['baseline_laps'][-1]);observation.update(lap=5,duration_ms=1050)
        observation['evidence']['source_sha256']='next-capture'
        next_report=dict(source_sha256='next-capture',comparisons=[],segments=[observation])
        for key,value in [('session_uid','other'),('epoch',1),('conditions',['Rain','C3','NONE'])]:
            wrong=copy.deepcopy(next_report);wrong['segments'][0][key]=value
            checks['scope_gate_'+key]=not process(wrong)['outcomes']
        outcome=process(next_report)['outcomes'][0]
        checks['subsequent_lap_compared_to_baseline']=outcome['observed']['lap']==5 and outcome['delta_ms']==-50 and outcome['interpretation']=='subsequent_lap_observation_not_causal_effect'
        restored=TrainingPlanStore(root/'plans.db',clock=lambda:now[0])
        checks['outcome_persists_after_reopen']=restored.list('one')[0]['outcome']==outcome
        checks['retry_keeps_same_outcome']=process(next_report)['outcomes']==[outcome]
        other=process(report,driver='two')['draft']
        now[0]+=8*86400
        checks['expiry_visible']=store.list('two')[0]['status']=='expired'
        try:store.activate(driver='two',plan_id=other['id'],after_lap=3);checks['expired_cannot_activate']=False
        except ValueError:checks['expired_cannot_activate']=True
        source=root/'session.jsonl';source.write_text('\n'.join(json.dumps(r) for r in rows()))
        workflow=WorkflowStore(root/'review.db')
        first=run_session_review(workflow,task_id='draft',source=source,driver_id='driver')
        focus=first['results'][-1]['result']['training_recommendation']
        linked=TrainingPlanStore(root/'review.training.sqlite3')
        linked.activate(driver='driver',plan_id=focus['id'],after_lap=3)
        extended=rows()[:-1]
        for r in rows():
            if r['lap_number']==3:
                r=copy.deepcopy(r);r['lap_number']=4;r['source_timestamp_ms']+=10000
                r['raw']['current_lap_time_ms']=r['raw']['lap_distance_m']*10.5
                extended.append(r)
        extended.append(dict(session_uid='s',session_epoch=0,lap_number=5,track='Suzuka',source_timestamp_ms=60000,raw={'last_lap_time_ms':100000}))
        source.write_text('\n'.join(json.dumps(r) for r in extended))
        second=run_session_review(workflow,task_id='followup',source=source,driver_id='driver')
        final=second['results'][-1]['result']
        checks['production_workflow_observes_active_plan']=second['status']=='completed' and len(final['training_outcomes'])==1 and final['training_outcomes'][0]['observed']['lap']==4
        checks['workflow_recovery_idempotent']=run_session_review(workflow,task_id='followup',source=source,driver_id='driver')['results']==second['results']
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
