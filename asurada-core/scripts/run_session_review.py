from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from asurada.workflow_store import WorkflowStore
from asurada.session_review_workflow import run_session_review
from asurada.review_command import execute_review


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--database',required=True,type=Path)
    parser.add_argument('--task-id',required=True)
    parser.add_argument('--driver-id',default='local-driver')
    args=parser.parse_args()
    store=WorkflowStore(args.database)
    result,code=execute_review(lambda:run_session_review(store,task_id=args.task_id,source=args.source,driver_id=args.driver_id),store=store,task_id=args.task_id)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return code

if __name__=='__main__':raise SystemExit(main())
