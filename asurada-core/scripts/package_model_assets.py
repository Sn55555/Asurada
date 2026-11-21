"""Seal colocated trained models before admission; integrity is not quality approval."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from asurada.model_assets import seal_report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('reports',nargs='+',type=Path)
    args=parser.parse_args()
    for report in args.reports:
        seal_report(report)
        print(json.dumps({'report':str(report),'sealed':True}))

if __name__=='__main__':main()
