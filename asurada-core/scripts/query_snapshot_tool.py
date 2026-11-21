"""Execute registered read-only capabilities against a versioned snapshot."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from asurada.decode import decode_snapshot
from asurada.capability_executor import CapabilityExecutor
from asurada.task_runtime import TaskContext
from asurada.workflow_store import WorkflowStore
from asurada.capabilities.history import ReviewScope
from asurada.capability_definitions import CAPABILITIES


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot',required=True,type=Path)
    parser.add_argument('--capability',required=True,action='append')
    parser.add_argument('--historical',action='store_true')
    parser.add_argument('--arguments-json',default='{}')
    parser.add_argument('--review-store',type=Path)
    parser.add_argument('--driver-id')
    args=parser.parse_args()
    payload=json.loads(args.snapshot.read_text())
    scope_only=args.historical and all(name in CAPABILITIES and CAPABILITIES[name].lane=='analysis_tool' for name in args.capability)
    state=ReviewScope.from_payload(payload) if scope_only else decode_snapshot(payload)
    if args.review_store is not None and not args.review_store.is_file():parser.error('review store must already exist')
    runner=CapabilityExecutor(context=TaskContext.start('snapshot-query',3000),
                              permissions=frozenset({'read_session_history' if args.historical else 'read_race_state'}),
                              historical=args.historical,driver_id=args.driver_id,
                              review_store=WorkflowStore(args.review_store) if args.review_store else None)
    print(json.dumps([runner.execute(name,state=state,arguments=json.loads(args.arguments_json)) for name in args.capability],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
