"""Observed future windows, bounded by continuity and session/stint identity."""
from bisect import bisect_left
import math
from .training_partition import validate_session_frame

WINDOW_VERSION='observed-future-window-v1'


def future_windows(df, *, horizon_s, max_gap_s=1.0, stable_columns=(), reset_columns=()):
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (horizon_s,max_gap_s)):
        raise ValueError('invalid_future_window_budget')
    data=validate_session_frame(df)
    stable=tuple(c for c in ('session_epoch',*stable_columns) if c in data.columns)
    resets=tuple(c for c in reset_columns if c in data.columns)
    def finite(value):
        try:return not isinstance(value,bool) and math.isfinite(float(value))
        except (TypeError,ValueError):return False
    for uid,group in data.groupby('session_uid',sort=False):
        # Source order matters: sorting would hide a rewind when epoch is absent.
        group=group.reset_index(drop=True)
        runs=[];run=[];previous=None
        for position,row in group.iterrows():
            time=row['session_time_s']
            invalid=not finite(time) or float(time)<0
            invalid=invalid or any(not finite(row[c]) for c in resets)
            invalid=invalid or any(row[c] is None or str(row[c]) in ('nan','<NA>','') for c in stable)
            if 'session_epoch' in stable and not invalid:
                epoch=row['session_epoch']
                invalid=not finite(epoch) or float(epoch)<0 or not float(epoch).is_integer()
            boundary=invalid
            if previous is not None and not invalid:
                delta=float(time)-float(previous['session_time_s'])
                boundary=delta<=0 or delta>max_gap_s
                boundary=boundary or any(row[c]!=previous[c] for c in stable)
                boundary=boundary or any(float(row[c])<float(previous[c]) for c in resets)
            if boundary:
                if run:runs.append(run)
                run=[];previous=None
            if not invalid:
                run.append(position);previous=row
        if run:runs.append(run)
        for run_id,positions in enumerate(runs):
            continuous=group.iloc[positions].reset_index(drop=True)
            times=continuous['session_time_s'].astype(float).tolist()
            for start,row in continuous.iterrows():
                end=bisect_left(times,times[start]+horizon_s,lo=start+1)
                if end>=len(times):continue
                evidence=dict(version=WINDOW_VERSION,session_uid=uid,run_id=run_id,
                    session_epoch=int(row['session_epoch']) if 'session_epoch' in stable else None,start_s=times[start],end_s=times[end],
                    horizon_s=horizon_s,max_gap_s=max_gap_s,
                    start_record_id=row.get('record_id'),end_record_id=continuous.iloc[end].get('record_id'),
                    stable_columns=list(stable),reset_columns=list(resets))
                yield row,continuous.iloc[start+1:end+1],evidence


def write_target_windows(frame, *, output_dir, targets, split_column, sources):
    """Preserve target intervals separately from model features for audit."""
    import hashlib
    from pathlib import Path
    path=Path(output_dir)/'target_windows.csv'
    columns=[c for c in ('record_id','session_uid','session_epoch',split_column,'target_window',*targets) if c in frame.columns]
    frame[columns].to_csv(path,index=False)
    def digest(source):
        value=hashlib.sha256()
        with Path(source).open('rb') as handle:
            for chunk in iter(lambda:handle.read(1024*1024),b''):value.update(chunk)
        return value.hexdigest()
    return dict(version=WINDOW_VERSION,path=path.name,sha256=digest(path),rows=len(frame),
        sources=[dict(path=str(Path(source).resolve()),sha256=digest(source)) for source in sources])
