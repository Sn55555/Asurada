"""Read a completed analysis without initializing a model provider."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from asurada.capability_executor import CapabilityExecutor
from asurada.durable_analysis import read_analysis_result
from asurada.task_runtime import TaskContext
from asurada.workflow_store import WorkflowStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-id', required=True, help='Full analysis: task ID')
    parser.add_argument('--driver-id', required=True)
    parser.add_argument('--review-store', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not args.review_store.is_file():
        parser.error('review store must already exist')
    store = WorkflowStore(args.review_store)
    executor = CapabilityExecutor(context=TaskContext.start('analysis-read', 5000),
        permissions=frozenset({'read_session_history'}), historical=True,
        review_store=store, driver_id=args.driver_id)
    result = read_analysis_result(store=store, task_id=args.task_id, executor=executor)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'task_id': args.task_id, 'status': result['status']}))


if __name__ == '__main__':
    main()
