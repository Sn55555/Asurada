import json
from pathlib import Path
from tempfile import TemporaryDirectory
from regression_support import emit_result
from asurada.review_capture import project_capture
from asurada.task_runtime import TaskContext


def run():
    fixture=Path(__file__).resolve().parents[1]/'data/capture_samples/f1_25_udp_frame_fixture.jsonl'
    with TemporaryDirectory() as temp:
        root=Path(temp);source=root/'capture.jsonl';destination=root/'review.jsonl'
        source.write_bytes(fixture.read_bytes()+b'\n'+json.dumps({'received_at_ms':1,'source_host':'test','source_port':1,'payload_base64':'AA=='}).encode()+b'\n')
        report=project_capture(source,destination,context=TaskContext.start('projection',5000))
        rows=[json.loads(line) for line in destination.read_text().splitlines()]
        checks={'canonical_capture_produces_review_rows':len(rows)>0 and len(rows)==report['counts']['snapshots'],
                'raw_hash_bound_to_every_row':all(row['provenance']['capture_sha256']==report['capture_sha256'] for row in rows),
                'invalid_packet_counted':report['counts']['decode_errors']==1,
                'lap_clock_and_distance_projected':all('current_lap_time_ms' in row['raw'] and 'lap_distance_m' in row['raw'] for row in rows),
                'finish_status_projected':all('result_status' in row['raw'] for row in rows)}
        before=destination.read_bytes()
        try:project_capture(source,destination,context=TaskContext.start('expired',0));checks['expired_not_published']=False
        except TimeoutError:checks['expired_not_published']=destination.read_bytes()==before
        try:project_capture(source,source,context=TaskContext.start('same',1000));checks['source_preserved']=False
        except ValueError:checks['source_preserved']=source.exists()
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
