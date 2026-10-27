"""Я генерирую два маленьких воспроизводимых снимка без реальных данных."""
import csv
import io
from pathlib import Path

from .core import ContractError, FIELDS, canonical, sha256

def write_snapshot(folder, rows, *, snapshot_id, as_of, complete=True, warehouses=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(FIELDS)
    writer.writerows(rows)
    raw = stream.getvalue().encode('utf-8')
    manifest = {'schema_version': 1, 'snapshot_id': snapshot_id, 'as_of': as_of, 'warehouses': ['WH-A', 'WH-B'] if warehouses is None else warehouses, 'complete': complete, 'row_count': len(rows), 'csv_sha256': sha256(raw)}
    (folder / 'stock.csv').write_bytes(raw)
    (folder / 'snapshot.json').write_bytes(canonical(manifest))

def generate(folder, scenario='valid'):
    folder = Path(folder)
    if folder.exists():
        raise ContractError('GENERATE_REQUIRES_NEW_DIRECTORY')
    if scenario not in ('valid', 'partial', 'duplicate', 'reserved'):
        raise ContractError('SCENARIO')
    before = [['WH-A', 'SKU-001', 10, 2], ['WH-A', 'SKU-002', 5, 0], ['WH-A', 'SKU-003', 7, 1], ['WH-B', 'SKU-001', 4, 1], ['WH-B', 'SKU-004', 0, 0]]
    after = [['WH-A', 'SKU-001', 8, 3], ['WH-A', 'SKU-002', 5, 0], ['WH-B', 'SKU-001', 4, 2], ['WH-B', 'SKU-004', 0, 0], ['WH-B', 'SKU-005', 6, 1]]
    if scenario == 'duplicate':
        after.append(after[0].copy())
    if scenario == 'reserved':
        after[0][3] = 9
    write_snapshot(folder / 'before', before, snapshot_id='SNAP-BEFORE', as_of='2026-10-25T23:00:00Z')
    write_snapshot(folder / 'after', after, snapshot_id='SNAP-AFTER', as_of='2026-10-26T23:00:00Z', complete=scenario != 'partial')
    return {'scenario': scenario, 'before_rows': len(before), 'after_rows': len(after)}
