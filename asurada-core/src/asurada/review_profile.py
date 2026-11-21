"""Explicit local profile commands and evidence-preserving review presentation."""
import argparse
import json
from pathlib import Path

from .capabilities.history import completed_review
from .task_runtime import TaskContext
from .training_memory import TrainingMemory
from .workflow_store import WorkflowStore


def record_performance(*, store, memory, driver, task_id):
    """Verify arithmetic against live scoped facts; never infer causal improvement."""
    context = TaskContext.start('profile-performance', 3000)
    task = completed_review(store, driver, task_id, context)
    indexed = next(item['result'] for item in task['results'] if item['step']=='index_official_laps')
    report = next(item['result'] for item in task['results'] if item['step']=='review_report')
    persisted = next(item['result'] for item in task['results'] if item['step']=='persist_session_facts')
    allowed_ids = set(persisted['memory_ids'])
    groups = {}
    for row in indexed:
        groups.setdefault((row['session_uid'],row['epoch'],row['track']), []).append(row)
    ids = []
    for (uid, epoch, track), rows in groups.items():
        context.remaining()
        recent = sorted(rows, key=lambda row: row['lap'])[-3:]
        if len(recent) < 2:
            continue
        facts = memory.query(driver=driver,kind='session_fact',session_uid=uid,epoch=epoch)
        evidence_ids = []
        for lap in (recent[0], recent[-1]):
            expected = {'track':track,'lap':lap['lap'],'time_ms':lap['time_ms']}
            matches = [fact for fact in facts if fact['id'] in allowed_ids and fact['value']==expected
                       and any(item.get('source_sha256')==report['source_sha256'] for item in fact['evidence'])]
            if len(matches)!=1:
                raise ValueError('performance_scoped_fact_unavailable')
            evidence_ids.append(matches[0]['id'])
        value = dict(track=track,baseline_time_ms=recent[0]['time_ms'],
                     observed_time_ms=recent[-1]['time_ms'],
                     delta_ms=recent[-1]['time_ms']-recent[0]['time_ms'])
        ids.append(memory.put(driver=driver,kind='verified_performance',
            key=f'review:{task_id}:scope:{uid}:{epoch}:{track}',value=value,
            evidence=[{'review_task_id':task_id,'source_sha256':report['source_sha256'],
                       'session_uid':uid,'epoch':epoch,'laps':[recent[0]['lap'],recent[-1]['lap']],
                       'interpretation':'observed_lap_delta_not_causal_effect'}],
            verification={'method':'official_lap_delta_v1','evidence_ids':evidence_ids},
            ttl_s=30*86400,context=context))
    return {'task_id':task_id,'driver_id':driver,'memory_ids':ids,
            'status':'recorded' if ids else 'insufficient_laps'}


def present_review(*, store, memory, driver, task_id):
    task = completed_review(store, driver, task_id, TaskContext.start('profile-read', 3000))
    report = next(item['result'] for item in task['results'] if item['step']=='review_report')
    preferences = [item for item in memory.query(driver=driver, kind='user_preference')
                   if item['key']=='review_detail' and item['value'] in ('brief','detailed')]
    preference = preferences[0] if preferences else None
    detail = preference['value'] if preference else 'detailed'
    result = {'task_id':task_id, 'driver_id':driver, 'detail':detail,
              'preference':preference, 'source_sha256':report['source_sha256'],
              'limitation':report['limitation']}
    result['verified_observations'] = [
        item for item in memory.query(driver=driver,kind='verified_performance')
        if any(ref.get('review_task_id')==task_id and ref.get('source_sha256')==report['source_sha256']
               for ref in item['evidence'])]
    habits = memory.brake_habits(driver=driver)
    if habits:
        result['driver_brake_references'] = habits
    if detail == 'detailed':
        result['report'] = report
    else:
        # Preserve the actual recommendation, outcomes and original report locator.
        result.update(comparisons=report['comparisons'],
                      training_recommendation=report['training_recommendation'],
                      training_outcomes=report['training_outcomes'],
                      full_report={'database':str(store.path.resolve()), 'task_id':task_id, 'step':'review_report'})
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path, help='Existing review workflow database')
    parser.add_argument('--driver-id', required=True, help='Explicit local profile, not authenticated identity')
    sub=parser.add_subparsers(dest='command', required=True)
    setting=sub.add_parser('set-detail')
    setting.add_argument('detail', choices=('brief','detailed'))
    setting.add_argument('--ttl-days', type=float, default=30)
    sub.add_parser('preferences')
    sub.add_parser('revoke-detail')
    show=sub.add_parser('show')
    show.add_argument('--task-id', required=True)
    record=sub.add_parser('record-performance')
    record.add_argument('--task-id', required=True)
    args=parser.parse_args(argv)
    if not args.driver_id.strip():parser.error('driver-id cannot be blank')
    if not args.database.is_file():parser.error('review database must exist')
    memory=TrainingMemory(args.database.with_suffix('.memory.sqlite3'))
    try:
        if args.command=='set-detail':
            memory.set_review_detail(driver=args.driver_id, detail=args.detail, ttl_s=args.ttl_days*86400)
        elif args.command=='revoke-detail':
            memory.revoke_review_detail(driver=args.driver_id)
        if args.command=='record-performance':
            result=record_performance(store=WorkflowStore(args.database),memory=memory,driver=args.driver_id,task_id=args.task_id)
        elif args.command=='show':
            result=present_review(store=WorkflowStore(args.database), memory=memory, driver=args.driver_id, task_id=args.task_id)
        else:
            result={'driver_id':args.driver_id, 'preferences':memory.query(driver=args.driver_id, kind='user_preference')}
    except (ValueError, KeyError, PermissionError, TimeoutError) as error:
        print(json.dumps({'status':'failed','error':type(error).__name__,'message':str(error)},ensure_ascii=False))
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
