"""One-to-one feature/label joins with explicit identity agreement."""
import hashlib
import json
from .training_partition import validate_session_frame


def join_training_labels(features, labels, *, targets):
    features=validate_session_frame(features)
    labels=validate_session_frame(labels)
    for data in (features,labels):
        if 'record_id' not in data or data['record_id'].isna().any() or (data['record_id'].astype(str).str.strip()=='').any():
            raise ValueError('training_record_id_required')
        data['record_id']=data['record_id'].astype(str)
        if data['record_id'].duplicated().any():
            raise ValueError('duplicate_training_record_id')
    if set(features['record_id'])!=set(labels['record_id']):
        raise ValueError('training_feature_label_coverage_mismatch')
    identity=['session_uid','split']
    identity += [c for c in ('session_epoch','frame_identifier','sample_name') if c in features and c in labels]
    left=features.set_index('record_id')
    right=labels.set_index('record_id').reindex(left.index)
    for column in identity:
        if left[column].isna().any() or right[column].isna().any():
            raise ValueError('training_label_identity_missing: '+column)
        if not left[column].equals(right[column]):
            # CSV integer widths need not match, but null identities never agree.
            if left[column].isna().any() or right[column].isna().any() or not (left[column]==right[column]).all():
                raise ValueError('training_label_identity_mismatch: '+column)
    if len(targets)!=len(set(targets)) or any(c not in labels or c in features for c in targets):
        raise ValueError('invalid_training_target_columns')
    merged=features.merge(labels[['record_id',*targets]],on='record_id',how='inner',validate='one_to_one',sort=False)
    identities=left[identity].reset_index().sort_values('record_id').to_dict(orient='records')
    manifest=dict(version='training-join-v1',rows=len(merged),identity_columns=identity,
        identity_sha256=hashlib.sha256(json.dumps(identities,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),targets=list(targets))
    return merged,manifest
