import json
from pathlib import Path
from tempfile import TemporaryDirectory
from asurada.training_provenance import training_provenance
from regression_support import emit_result


def run():
    with TemporaryDirectory() as directory:
        root=Path(directory); features=root/'features.csv'; labels=root/'labels.csv'
        features.write_text('x\n1\n'); labels.write_text('y\n2\n')
        missing=training_provenance(features,labels)
        checks={'legacy_metadata_not_invented':missing['export_metadata_status']=='missing' and 'context_window_version' not in missing}
        manifest={'features_path':str(features),'labels_path':str(labels),
                  'context_window_version':'source-time-weighted-v1','label_provenance':{'human_validated':False}}
        (root/'manifest.json').write_text(json.dumps(manifest))
        first=training_provenance(features,labels)
        checks['metadata_captured']=first['context_window_version']=='source-time-weighted-v1' and first['label_provenance']['human_validated'] is False
        single=training_provenance(features)
        checks['single_table_does_not_invent_labels']=single['labels_sha256'] is None and single['labels_path'] is None
        specialized={**manifest,'strategy_action_features_path':str(features)}
        (root/'manifest.json').write_text(json.dumps(specialized))
        checks['specialized_table_uses_declared_key']=training_provenance(features,feature_key='strategy_action_features_path')['export_metadata_status']=='recorded'
        (root/'manifest.json').write_text(json.dumps(manifest))
        features.write_text('x\n3\n')
        checks['data_change_has_distinct_hash']=first['features_sha256']!=training_provenance(features,labels)['features_sha256']
        manifest['labels_path']=str(root/'other.csv');(root/'manifest.json').write_text(json.dumps(manifest))
        try:
            training_provenance(features,labels);checks['wrong_input_rejected']=False
        except ValueError:checks['wrong_input_rejected']=True
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
