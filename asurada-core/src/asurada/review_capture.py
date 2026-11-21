"""Evidence-linked compact review projection from the canonical packet decoder."""
from collections import Counter
import fcntl
import hashlib
import json
from pathlib import Path
import tempfile

from .capture_ingest import CaptureJsonlSource
from .decode import decode_snapshot
from .packet_snapshot import CaptureSnapshotAssembler
from .packet_decode_diagnostics import PacketDecodeDiagnostics
from .pdu_decoder import F125PacketDecoder, PacketDecodeError
from .state import UnifiedStateStore

PROJECTION_VERSION = "review-projection-v4"


def file_digest(path, context):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):
            context.remaining();digest.update(chunk)
    return digest.hexdigest()


def project_capture(source: Path, destination: Path, *, context):
    source,destination=source.resolve(),destination.resolve()
    if source==destination:
        raise ValueError('capture_projection_cannot_replace_source')
    digest=file_digest(source,context)
    decoder,assembler,store=F125PacketDecoder(),CaptureSnapshotAssembler(),UnifiedStateStore()
    decode_diagnostics=PacketDecodeDiagnostics()
    counts=Counter();destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    latest_rows={}
    finish_rows={}
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=destination.parent,delete=False) as output:
            temporary=Path(output.name)
            for ordinal,packet in enumerate(CaptureJsonlSource(source),1):
                context.remaining();counts['packets']+=1
                try:envelope=decoder.decode_raw(packet)
                except PacketDecodeError as exc:
                    decode_diagnostics.record(exc)
                    counts['decode_errors']+=1;continue
                body=envelope.payload['body']
                header=envelope.payload['header']
                # Finish LapData may be the last packet: no complete physics frame follows.
                if envelope.kind == 'LapData' and body.get('result_status') == 3:
                    previous=latest_rows.get(envelope.session_uid)
                    if previous is not None:
                        row=dict(previous)
                        row['lap_number']=body['current_lap_num']
                        row['source_timestamp_ms']=packet.received_at_ms
                        row['player']={}  # No invented physics sample at the finish.
                        row['raw']={key:body.get(key) for key in ('lap_distance_m','current_lap_time_ms','last_lap_time_ms','current_lap_invalid','result_status','pit_status')}
                        row['raw']['session_time_s']=header['session_time_s']
                        row['provenance']={'capture_sha256':digest,'packet_ordinal':ordinal,'projection_version':PROJECTION_VERSION,'kind':'official_finish_lap_data'}
                        key=(row['session_uid'],row['session_epoch'],row['lap_number'])
                        if key not in finish_rows:
                            finish_rows[key]=row
                            output.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
                            counts['completion_records']+=1
                snapshot=assembler.push(envelope)
                if snapshot is None:continue
                state=decode_snapshot(snapshot)
                if not store.update(state):
                    counts['state_rejected']+=1;continue
                raw=state.raw
                row=dict(session_uid=state.session_uid,session_epoch=state.session_epoch,track=state.track,
                         lap_number=state.lap_number,source_timestamp_ms=state.source_timestamp_ms,
                         weather=state.weather,safety_car=state.safety_car,
                         player={'speed_kph':state.player.speed_kph,'tyre':{'compound':state.player.tyre.compound}},
                         raw={key:raw.get(key) for key in ('lap_distance_m','current_lap_time_ms','last_lap_time_ms',
                             'current_lap_invalid','result_status','pit_status','brake','throttle','gear','session_time_s')},
                         provenance={'capture_sha256':digest,'packet_ordinal':ordinal,'projection_version':PROJECTION_VERSION})
                latest_rows[state.session_uid]=row
                output.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
                counts['snapshots']+=1
        if file_digest(source,context)!=digest:
            raise ValueError('capture_changed_during_projection')
        # Mark only transitional rows proven by a nearby official finish packet.
        # Consumers omit these rows from both lap indexing and corner traversal.
        with temporary.open() as source_rows, tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=destination.parent,delete=False) as cleaned:
            cleaned_path=Path(cleaned.name)
            try:
                for line in source_rows:
                    context.remaining()
                    row=json.loads(line);raw=row.get('raw') or {}
                    finish=finish_rows.get((row['session_uid'],row['session_epoch'],row['lap_number']))
                    if (finish and raw.get('result_status') != 3
                            and isinstance(raw.get('current_lap_time_ms'),(int,float))
                            and 0 <= raw['current_lap_time_ms'] <= 1000
                            and raw.get('last_lap_time_ms') == finish['raw'].get('last_lap_time_ms')
                            and 0 <= finish['source_timestamp_ms']-row['source_timestamp_ms'] <= 1000):
                        row['raw']['review_exclude_reason']='official_finish_transition'
                        counts['finish_transition_rows']+=1
                    cleaned.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            except BaseException:
                cleaned_path.unlink(missing_ok=True)
                raise
        temporary.unlink();temporary=cleaned_path
        context.remaining()
        temporary.replace(destination);temporary=None
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return dict(version=PROJECTION_VERSION,source=str(source),capture_sha256=digest,projection=str(destination),
                projection_sha256=file_digest(destination,context),counts=dict(counts),
                decode_diagnostics=decode_diagnostics.snapshot(),
                rejected_receive_times=assembler.cache_freshness.rejected,
                rejected_pre_rewind_packets=assembler.epoch_rejections)


def project_capture_cached(source: Path, destination: Path, manifest: Path, *, context):
    if len({source.resolve(),destination.resolve(),manifest.resolve()}) != 3:
        raise ValueError('projection_paths_must_be_distinct')
    manifest.parent.mkdir(parents=True,exist_ok=True)
    with manifest.with_suffix(manifest.suffix+'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        context.remaining()
        return _project_capture_cached(source,destination,manifest,context=context)


def _project_capture_cached(source: Path, destination: Path, manifest: Path, *, context):
    """Resume a published projection only when both input and output hashes match.

    The manifest is committed last. A projection without its manifest is an
    unfinished attempt and can be rebuilt; a committed pair is immutable here.
    """
    if manifest.exists():
        report=json.loads(manifest.read_text())
        if report.get('version') != PROJECTION_VERSION:
            raise ValueError('capture_projection_version_conflict')
        if report.get('source') != str(source.resolve()) or report.get('capture_sha256') != file_digest(source,context):
            raise ValueError('capture_projection_input_conflict')
        if report.get('projection') != str(destination.resolve()) or report.get('projection_sha256') != file_digest(destination,context):
            raise ValueError('capture_projection_integrity_failure')
        context.remaining()
        return report
    report=project_capture(source,destination,context=context)
    temporary=None
    try:
        manifest.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=manifest.parent,delete=False) as handle:
            temporary=Path(handle.name)
            json.dump(report,handle,ensure_ascii=False,indent=2,allow_nan=False)
        context.remaining()
        temporary.replace(manifest);temporary=None
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return report
