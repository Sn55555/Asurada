"""Durable evidence-bound practice drafts and subsequent-lap observations.

These records are experiments, not verified driver traits or causal claims.
The caller supplies a trusted segment review from the deterministic pipeline.
"""
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from statistics import median
import time


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def choose_focus(review):
    candidates = []
    for comparison in review['comparisons']:
        laps = comparison['laps']
        if len(laps) != 3 or len({row['lap'] for row in laps}) != 3:
            continue
        scope = ('session_uid', 'epoch', 'track', 'segment', 'conditions', 'start_m', 'end_m')
        if any(any(row[key] != laps[0][key] for key in scope) for row in laps):
            continue
        durations = [row['duration_ms'] for row in laps]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in durations):
            continue
        spread = round(max(durations) - min(durations), 3)
        if spread < 50:
            continue
        candidates.append((spread, laps[0]['segment'], laps))
    if not candidates:
        return None
    spread, _, laps = max(candidates, key=lambda item: (item[0], item[1]))
    first = laps[0]
    return dict(version='segment-consistency-v1', session_uid=first['session_uid'],
        epoch=first['epoch'], track=first['track'], segment=first['segment'],
        conditions=first['conditions'], start_m=first['start_m'], end_m=first['end_m'],
        baseline_laps=laps, baseline_last_lap=max(row['lap'] for row in laps),
        baseline_median_ms=median(row['duration_ms'] for row in laps), baseline_spread_ms=spread,
        focus=f"下一圈关注 {first['segment']} 的通过稳定性，尽量重复自己的驾驶动作；圈后比较同距离区段耗时。",
        selection='largest_observed_three_lap_spread_at_least_50ms',
        limitation='50 ms 是工程筛选阈值；本任务不建议改变制动点，不推断耗时波动原因，单圈结果不证明训练效果。')


class TrainingPlanStore:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS training_plans (id TEXT PRIMARY KEY, driver TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, after_lap INTEGER, outcome TEXT)')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=1)
        try:
            with db:
                yield db
        finally:
            db.close()

    def list(self, driver):
        with self._connect() as db:
            rows = db.execute('SELECT id,payload,status,created,expires,after_lap,outcome FROM training_plans WHERE driver=? ORDER BY created,id', (driver,)).fetchall()
        return [dict(id=r[0], draft=json.loads(r[1]), status='expired' if r[2] in ('draft','active') and r[4]<=self.clock() else r[2],
            created_at=r[3], expires_at=r[4], after_lap=r[5], outcome=json.loads(r[6]) if r[6] else None) for r in rows]

    def activate(self, *, driver, plan_id, after_lap):
        if isinstance(after_lap, bool) or not isinstance(after_lap, int):
            raise ValueError('activation_requires_current_completed_lap')
        with self._connect() as db:
            row=db.execute('SELECT payload,status,expires,after_lap FROM training_plans WHERE id=? AND driver=?',(plan_id,driver)).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if row[2]<=self.clock() or row[1] not in ('draft','active'):
                raise ValueError('plan_not_activatable')
            if after_lap<json.loads(row[0])['baseline_last_lap']:
                raise ValueError('activation_predates_baseline')
            if row[1]=='active':
                if row[3]!=after_lap:raise ValueError('activation_identity_conflict')
                return
            db.execute("UPDATE training_plans SET status='active',after_lap=? WHERE id=?",(after_lap,plan_id))

    def cancel(self, *, driver, plan_id):
        with self._connect() as db:
            changed=db.execute("UPDATE training_plans SET status='cancelled' WHERE id=? AND driver=? AND status IN ('draft','active')",(plan_id,driver)).rowcount
        return bool(changed)

    def process_review(self, *, driver, review, context):
        if not isinstance(driver,str) or not driver:
            raise ValueError('driver_required')
        context.remaining()
        draft=choose_focus(review)
        draft_record=None
        now=self.clock()
        with self._connect() as db:
            if draft is not None:
                payload=encoded(draft)
                plan_id=hashlib.sha256(encoded([driver,draft]).encode()).hexdigest()
                context.remaining()
                db.execute("INSERT OR IGNORE INTO training_plans VALUES (?,?,?,'draft',?,?,NULL,NULL)",(plan_id,driver,payload,now,now+7*86400))
                draft_record=dict(id=plan_id,**draft)
            active=db.execute("SELECT id,payload,after_lap FROM training_plans WHERE driver=? AND status='active' AND expires>?",(driver,now)).fetchall()
            for plan_id,payload,after_lap in active:
                context.remaining()
                plan=json.loads(payload)
                matches=[s for s in review['segments'] if s['lap']>after_lap and all(s[k]==plan[k] for k in
                    ('session_uid','epoch','track','segment','conditions','start_m','end_m'))]
                if not matches:continue
                observed=min(matches,key=lambda s:s['lap'])
                # One observation, immutable across later reports or retries.
                outcome=dict(plan_id=plan_id, observed=observed, baseline_median_ms=plan['baseline_median_ms'],
                    delta_ms=round(observed['duration_ms']-plan['baseline_median_ms'],3),
                    report_sha256=review['source_sha256'], interpretation='subsequent_lap_observation_not_causal_effect')
                db.execute("UPDATE training_plans SET status='observed',outcome=? WHERE id=? AND status='active'",(encoded(outcome),plan_id))
            outcomes=[json.loads(row[0]) for row in db.execute("SELECT outcome FROM training_plans WHERE driver=? AND status='observed' ORDER BY id",(driver,))]
            context.remaining()
        return dict(draft=draft_record, outcomes=[o for o in outcomes if o['report_sha256']==review['source_sha256']])
