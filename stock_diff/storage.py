"""Я публикую готовый каталог целиком; существующий результат не перезаписываю."""
from contextlib import contextmanager
import io
import os
from pathlib import Path
import shutil
import tempfile

import polars as pl

from .core import ContractError, canonical, json_document, read_limited, sha256

NAMES = {'bundle.json', 'summary.json', 'diff.parquet'}

@contextmanager
def destination_lock(output):
    lock = output.parent / ('.' + output.name + '.lock')
    try:
        lock.mkdir()
    except FileExistsError:
        raise ContractError('OUTPUT_BUSY') from None
    try:
        yield
    finally:
        lock.rmdir()

def inspect(output):
    output = Path(output)
    if output.is_symlink() or not output.is_dir() or {p.name for p in output.iterdir()} != NAMES:
        raise ContractError('BUNDLE_LAYOUT')
    manifest = json_document(read_limited(output / 'bundle.json', 8192))
    if not isinstance(manifest, dict) or set(manifest) != {'bundle_version', 'report_id', 'files'} or type(manifest['bundle_version']) is not int or manifest['bundle_version'] != 1:
        raise ContractError('BUNDLE_MANIFEST')
    files = manifest['files']
    if not isinstance(files, dict) or set(files) != {'summary.json', 'diff.parquet'}:
        raise ContractError('BUNDLE_FILES')
    payload = {}
    for name in sorted(files):
        raw = read_limited(output / name, 8_000_000)
        if files[name] != {'sha256': sha256(raw), 'bytes': len(raw)}:
            raise ContractError('BUNDLE_HASH_MISMATCH')
        payload[name] = raw
    summary = json_document(payload['summary.json'])
    if not isinstance(summary, dict) or summary.get('report_id') != manifest['report_id']:
        raise ContractError('BUNDLE_IDENTITY')
    diff = pl.read_parquet(io.BytesIO(payload['diff.parquet']))
    if diff.height != summary.get('changed_rows'):
        raise ContractError('BUNDLE_ROW_COUNT')
    return {'summary': summary, 'changes': diff.to_dicts()}

def publish(output, summary, diff, *, simulate_failure=False):
    output = Path(output)
    if not output.name or output.is_symlink() or output.parent.is_symlink():
        raise ContractError('OUTPUT_PATH')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Parquet остаётся типизированным даже для нуля изменений; нулевой остаток != NULL.
    stream = io.BytesIO()
    diff.write_parquet(stream, compression='uncompressed', row_group_size=10_000)
    payload = {'diff.parquet': stream.getvalue(), 'summary.json': canonical(summary)}
    manifest = {'bundle_version': 1, 'report_id': summary['report_id'], 'files': {name: {'sha256': sha256(raw), 'bytes': len(raw)} for name, raw in payload.items()}}
    payload['bundle.json'] = canonical(manifest)
    with destination_lock(output):
        if output.exists():
            inspect(output)
            if any((output / name).read_bytes() != raw for name, raw in payload.items()):
                raise ContractError('OUTPUT_CONFLICT')
            return {'report_id': summary['report_id'], 'reused': True, 'counts': summary['counts'], 'totals': summary['totals']}
        stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.pending-', dir=output.parent))
        try:
            for name, raw in payload.items():
                with (stage / name).open('xb') as file:
                    file.write(raw)
                    file.flush()
                    os.fsync(file.fileno())
            inspect(stage)
            if simulate_failure:
                raise ContractError('SIMULATED_BEFORE_RENAME')
            # Оба каталога на одной filesystem. Согласованные writers используют lock.
            os.rename(stage, output)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return {'report_id': summary['report_id'], 'reused': False, 'counts': summary['counts'], 'totals': summary['totals']}
