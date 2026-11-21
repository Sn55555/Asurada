"""Run a bounded review analysis with a configured JSON planner command."""
import argparse
import json
from pathlib import Path
import shlex
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from asurada.analysis_agent import CommandAnalysisPlanner
from asurada.capability_executor import CapabilityExecutor
from asurada.capabilities.history import ReviewScope
from asurada.task_runtime import TaskContext
from asurada.workflow_store import WorkflowStore
from asurada.analysis_planner import HttpAnalysisPlanner
from asurada.durable_analysis import run_durable_analysis


def main():
    parser=argparse.ArgumentParser()
    for name in ('question','review-task-id','driver-id'):parser.add_argument('--'+name,required=True)
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--planner-command')
    choice.add_argument('--provider',choices=['openai-responses','doubao-responses','doubao-chat'])
    parser.add_argument('--review-store',type=Path,required=True);parser.add_argument('--scope',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--timeout-ms',type=int,default=15000)
    parser.add_argument('--analysis-id', default=None, help='Reuse this ID to recover the same analysis within its original deadline')
    args=parser.parse_args()
    if not args.review_store.is_file():parser.error('review store must already exist')
    scope=ReviewScope.from_payload(json.loads(args.scope.read_text()))
    executor=CapabilityExecutor(context=TaskContext.start('review-analysis',args.timeout_ms),permissions=frozenset({'read_session_history'}),
        historical=True,review_store=WorkflowStore(args.review_store),driver_id=args.driver_id)
    planner=CommandAnalysisPlanner(shlex.split(args.planner_command)) if args.planner_command else HttpAnalysisPlanner.from_env(args.provider)
    task_id='analysis:'+(args.analysis_id or uuid.uuid4().hex)
    identity={'command':shlex.split(args.planner_command)} if args.planner_command else {
        'provider':args.provider,'model':planner.provider.model,'base_url':planner.provider.base_url}
    result=run_durable_analysis(store=executor.review_store,task_id=task_id,planner=planner,
        planner_identity=identity,executor=executor,question=args.question,scope=scope,review_task_id=args.review_task_id)
    if isinstance(planner,HttpAnalysisPlanner):result['provider_calls']=planner.calls
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'task_id':task_id,'status':result['status'],'steps':len(result['steps'])}))
    return 0 if result['status']=='completed' else 2


if __name__=='__main__':raise SystemExit(main())
