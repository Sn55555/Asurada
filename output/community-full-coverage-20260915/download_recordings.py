"""Download public recordings without materializing uncompressed copies.

Only downloads data. Never runs the provider's replay application or sends UDP.
Completed gzip archives preserve every source byte; reports include raw SHA-256.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import requests

ROOT = Path(__file__).resolve().parent

def download(row, destination, reserve):
    target = destination / (row['name'] + '.gz')
    receipt = target.with_suffix(target.suffix + '.json')
    if target.exists() and receipt.exists():
        return json.loads(receipt.read_text())
    if shutil.disk_usage(destination).free < reserve:
        raise RuntimeError('disk_reserve_reached')
    part = target.with_suffix(target.suffix + '.part')
    url = 'https://drive.usercontent.google.com/download'
    digest = hashlib.sha256()
    count = 0
    with requests.get(url, params={'id': row['drive_id'], 'export':'download', 'confirm':'t'},
                      stream=True, timeout=(20, 60)) as response:
        response.raise_for_status()
        length = response.headers.get('Content-Length')
        started = time.monotonic()
        last_progress = started
        with part.open('wb') as raw_out:
            with gzip.GzipFile(filename='', fileobj=raw_out, mode='wb', compresslevel=6, mtime=0) as out:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    if count == 0 and not chunk.startswith(b'F1UDP\0'):
                        raise ValueError('Expected F1UDP binary; server returned ' + repr(chunk[:80]))
                    if shutil.disk_usage(destination).free < reserve:
                        raise RuntimeError('disk_reserve_reached')
                    digest.update(chunk)
                    count += len(chunk)
                    out.write(chunk)
                    if time.monotonic() - last_progress > 20:
                        print(json.dumps({'progress':row['name'], 'downloaded_bytes':count}), flush=True)
                        last_progress = time.monotonic()
        if length is not None and count != int(length):
            raise ValueError('HTTP content length mismatch')
    # Re-read the archive to verify lossless retention and the gzip checksum.
    check = hashlib.sha256()
    with gzip.open(part, 'rb') as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b''):
            check.update(chunk)
    if check.hexdigest() != digest.hexdigest():
        raise ValueError('archive roundtrip mismatch')
    part.replace(target)
    result = {**row, 'status':'downloaded_hash_verified', 'archive_path':str(target.resolve()),
              'source_url':'https://drive.google.com/file/d/' + row['drive_id'] + '/view',
              'raw_bytes':count, 'stored_bytes':target.stat().st_size, 'raw_sha256':digest.hexdigest(),
              'download_seconds':round(time.monotonic()-started, 2),
              'source_checksum_available':False, 'training_qualified':False}
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, default=ROOT/'raw')
    parser.add_argument('--name', action='append')
    parser.add_argument('--reserve-mib', type=int, default=1024)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    rows = [r for r in json.loads((ROOT/'remote-files.json').read_text())
            if r['name'].startswith('f1_25_') and (not args.name or r['name'] in args.name)]
    # Short files establish format and access first; every listed F1 25 file remains in scope.
    def size(row):
        number, unit = row['display_size'].split()
        return float(number) * {'KB':1024, 'MB':1024**2, 'GB':1024**3}[unit]
    results = []
    def worker(row):
        try:
            result = download(row, args.destination, args.reserve_mib * 1024**2)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return result
        except Exception as exc:
            result = {**row, 'status':'failed', 'error':str(exc)}
            print(json.dumps(result, ensure_ascii=False), flush=True)
            # Never leave a partial file presented as a completed download.
            part = args.destination / (row['name']+'.gz.part')
            if part.exists():
                part.unlink()
            return result
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,3))) as pool:
        futures = [pool.submit(worker,row) for row in sorted(rows,key=size)]
        for future in as_completed(futures):
            results.append(future.result())
            (ROOT/'download-status.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'download-status.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')

if __name__ == '__main__':
    main()
