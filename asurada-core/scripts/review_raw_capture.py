from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from asurada.session_review_workflow import run_session_review
from asurada.workflow_store import WorkflowStore
from asurada.review_command import execute_review, review_summary


def main():
    parser=argparse.ArgumentParser(description='Project a raw capture and run evidence-bound session review.')
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--task-id',required=True)
    parser.add_argument('--driver-id',default='local-driver')
    parser.add_argument('--timeout','--projection-timeout',dest='timeout',type=float,default=300,help='Total task budget in seconds, including projection')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    store=WorkflowStore(args.output/'review.db')
    def run():
        return run_session_review(store,task_id=args.task_id,
                                 source=args.capture,driver_id=args.driver_id,capture_directory=args.output,timeout_s=args.timeout)
    result,code=execute_review(run,store=store,task_id=args.task_id)
    (args.output/'review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(review_summary(result),ensure_ascii=False))
    return code


if __name__=='__main__':raise SystemExit(main())
