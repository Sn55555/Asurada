"""Inspect or cancel a persistent review task from another local process."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from asurada.workflow_store import WorkflowStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True,type=Path)
    parser.add_argument('--task-id',required=True)
    parser.add_argument('command',choices=('status','cancel'))
    args=parser.parse_args()
    if not args.database.is_file():parser.error('database does not exist')
    store=WorkflowStore(args.database)
    try:
        store.get(args.task_id)
        if args.command=='cancel':store.cancel(args.task_id)
        result=store.get(args.task_id)
    except KeyError:
        print(json.dumps({'status':'not_found','task_id':args.task_id}));return 1
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
