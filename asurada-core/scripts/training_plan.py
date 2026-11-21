"""Inspect, activate or cancel a local practice draft; never starts playback."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from asurada.training_plans import TrainingPlanStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True,type=Path,help='Review workflow database; uses its .training.sqlite3 sibling')
    parser.add_argument('--driver-id',default='local-driver')
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('list')
    activate=commands.add_parser('activate')
    activate.add_argument('--plan-id',required=True)
    activate.add_argument('--after-lap',required=True,type=int,help='Current completed lap; only later laps can be observed')
    cancel=commands.add_parser('cancel')
    cancel.add_argument('--plan-id',required=True)
    args=parser.parse_args()
    store=TrainingPlanStore(args.database.with_suffix('.training.sqlite3'))
    if args.command=='activate':store.activate(driver=args.driver_id,plan_id=args.plan_id,after_lap=args.after_lap)
    elif args.command=='cancel':store.cancel(driver=args.driver_id,plan_id=args.plan_id)
    print(json.dumps(store.list(args.driver_id),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
