"""Session-disjoint partitions; never fall back to random adjacent-row holdout."""
from __future__ import annotations
import hashlib
import math
from typing import Any


def session_partitions(frame: Any, *, split_column: str = 'split') -> tuple[Any, Any, Any, dict]:
    data = validate_session_frame(frame, split_column=split_column)
    if not (data[split_column] == 'val').any():
        sessions = sorted(data.loc[data[split_column] == 'train','session_uid'].unique(),
                          key=lambda uid: hashlib.sha256(('session-split-v1:'+uid).encode()).hexdigest())
        if len(sessions) < 2:
            raise ValueError('insufficient_sessions_for_validation')
        count = min(len(sessions)-1, max(1, math.ceil(len(sessions)*.2)))
        data.loc[data['session_uid'].isin(sessions[:count]), split_column] = 'val'
    parts = tuple(data[data[split_column] == split].copy() for split in ('train','val','test'))
    if any(part.empty for part in parts):
        raise ValueError('empty_session_partition')
    manifest = {'version':'session-split-v1', 'unit':'session_uid',
                'sessions':{split:sorted(part['session_uid'].unique()) for split,part in zip(('train','val','test'),parts)},
                'rows':{split:int(len(part)) for split,part in zip(('train','val','test'),parts)}}
    return (*parts, manifest)


def export_session_assignments(samples, sample_splits):
    """Resolve configured sample splits before labels or frame features exist."""
    assignments={}
    names={}
    for sample in samples:
        uid=sample.get('session_uid')
        if isinstance(uid,bool) or not isinstance(uid,(str,int)) or not str(uid).strip():
            raise ValueError('missing_session_identity')
        uid=str(uid)
        name=sample['sample_name']
        split=sample_splits.get(name,'train')
        if split not in {'train','val','test'}:raise ValueError('unknown_training_split')
        if uid in assignments and assignments[uid]!=split:
            raise ValueError('session_crosses_exported_partitions')
        if name in names and names[name]!=uid:
            raise ValueError('sample_name_session_conflict')
        names[name]=uid;assignments[uid]=split
    unknown=set(sample_splits)-set(names)
    if unknown:raise ValueError('unknown_split_sample_names: '+','.join(sorted(unknown)))
    return assignments


def exported_row_split(row):
    """Domain filters may choose rows, but never change their session split."""
    split=row.get('split')
    if split not in {'train','val','test'}:raise ValueError('unknown_training_split')
    return split


def validate_session_frame(frame, *, split_column="split"):
    """Validate identity before aggregation or target generation can hide leakage."""
    if 'session_uid' not in frame or split_column not in frame:
        raise ValueError('session_uid_and_split_required')
    if frame['session_uid'].isna().any() or (frame['session_uid'].astype(str).str.strip() == '').any():
        raise ValueError('missing_session_identity')
    data = frame.copy()
    data['session_uid'] = data['session_uid'].astype(str)
    if not set(data[split_column].unique()) <= {'train','val','test'}:
        raise ValueError('unknown_training_split')
    assignments = data.groupby('session_uid')[split_column].nunique()
    if (assignments > 1).any():
        raise ValueError('session_crosses_exported_partitions')
    return data
