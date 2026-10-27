"""Я отделяю входной контракт и выражения Polars от записи результата."""
import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re

import polars as pl

ENGINE = 'stock-diff-v1'
FIELDS = ('warehouse', 'sku', 'on_hand', 'reserved')
KEYS = ['warehouse', 'sku']
METRICS = ('on_hand', 'reserved', 'available')
MAX_BYTES = 1_000_000
MAX_ROWS = 10_000
MANIFEST_FIELDS = {'schema_version', 'snapshot_id', 'as_of', 'warehouses', 'complete', 'row_count', 'csv_sha256'}

class ContractError(ValueError):
    """Я возвращаю короткий код без исходных строк и локальных путей."""

def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')

def sha256(raw):
    return hashlib.sha256(raw).hexdigest()

def json_document(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('non-finite constant')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, UnicodeError):
        raise ContractError('JSON_INVALID') from None

def read_limited(path, limit):
    path = Path(path)
    if path.is_symlink():
        raise ContractError('INPUT_SYMLINK')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ContractError('INPUT_TOO_LARGE')
    return raw

def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value):
        raise ContractError('UTC_TIMESTAMP')
    try:
        result = datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError:
        raise ContractError('UTC_TIMESTAMP') from None
    if not 2020 <= result.year <= 2099:
        raise ContractError('UTC_TIMESTAMP_RANGE')
    return result

@dataclass(frozen=True)
class Snapshot:
    manifest: dict
    manifest_sha256: str
    frame: pl.DataFrame

def read_snapshot(folder):
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise ContractError('SNAPSHOT_DIRECTORY')
    manifest_raw = read_limited(folder / 'snapshot.json', 8192)
    manifest = json_document(manifest_raw)
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise ContractError('MANIFEST_FIELDS')
    if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1:
        raise ContractError('SCHEMA_VERSION')
    if not isinstance(manifest['snapshot_id'], str) or not re.fullmatch(r'SNAP-[A-Z0-9-]{1,24}', manifest['snapshot_id']):
        raise ContractError('SNAPSHOT_ID')
    timestamp(manifest['as_of'])
    scope = manifest['warehouses']
    if not isinstance(scope, list) or not 1 <= len(scope) <= 20 or any(not isinstance(w, str) or not re.fullmatch(r'WH-[A-Z0-9]{1,8}', w) for w in scope):
        raise ContractError('WAREHOUSE_SCOPE')
    if scope != sorted(set(scope)):
        raise ContractError('WAREHOUSE_SCOPE_ORDER')
    # Я отказываю до full join: отсутствие строки в частичном пакете не является DELETE.
    if manifest['complete'] is not True:
        raise ContractError('INCOMPLETE_SNAPSHOT')
    if type(manifest['row_count']) is not int or not 0 <= manifest['row_count'] <= MAX_ROWS:
        raise ContractError('ROW_COUNT')
    digest = manifest['csv_sha256']
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        raise ContractError('CSV_DIGEST')
    raw = read_limited(folder / 'stock.csv', MAX_BYTES)
    if sha256(raw) != digest:
        raise ContractError('CSV_HASH_MISMATCH')
    # Ограниченный CSV я разбираю stdlib, чтобы строго проверить ширину каждой строки.
    # Числа сначала оставляю строками: "001" в количестве не должно незаметно стать 1.
    try:
        reader = csv.reader(io.StringIO(raw.decode('utf-8'), newline=''), strict=True)
        if tuple(next(reader, [])) != FIELDS:
            raise ContractError('CSV_HEADER')
        rows = []
        for row in reader:
            if len(row) != len(FIELDS):
                raise ContractError('CSV_COLUMNS')
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ContractError('TOO_MANY_ROWS')
    except (UnicodeError, csv.Error):
        raise ContractError('CSV_ENCODING_OR_SYNTAX') from None
    if len(rows) != manifest['row_count']:
        raise ContractError('ROW_COUNT_MISMATCH')
    frame = pl.DataFrame(rows, schema={key: pl.String for key in FIELDS}, orient='row')
    valid = (
        pl.col('warehouse').is_in(scope)
        & pl.col('sku').str.contains(r'^SKU-[A-Z0-9]{1,16}$')
        & pl.col('on_hand').str.contains(r'^(0|[1-9][0-9]{0,9})$')
        & pl.col('reserved').str.contains(r'^(0|[1-9][0-9]{0,9})$')
    ).fill_null(False)
    if frame.filter(~valid).height:
        raise ContractError('ROW_VALUE')
    frame = frame.with_columns(pl.col('on_hand', 'reserved').cast(pl.Int64, strict=True))
    if frame.filter((pl.col('on_hand') > 1_000_000_000) | (pl.col('reserved') > pl.col('on_hand'))).height:
        raise ContractError('QUANTITY_RANGE')
    if frame.select(pl.struct(KEYS).n_unique()).item() != frame.height:
        raise ContractError('DUPLICATE_KEY')
    frame = frame.with_columns((pl.col('on_hand') - pl.col('reserved')).alias('available'))
    return Snapshot(manifest, sha256(manifest_raw), frame)

def compare(before, after):
    if before.manifest['warehouses'] != after.manifest['warehouses']:
        raise ContractError('SCOPE_MISMATCH')
    if before.manifest['snapshot_id'] == after.manifest['snapshot_id']:
        raise ContractError('SNAPSHOT_ID_REUSED')
    if timestamp(after.manifest['as_of']) <= timestamp(before.manifest['as_of']):
        raise ContractError('SNAPSHOT_ORDER')
    def side(snapshot, prefix):
        return snapshot.frame.select(*KEYS, *[pl.col(m).alias(prefix + m) for m in METRICS]).with_columns(pl.lit(True).alias(prefix + 'present'))
    # Composite key и validate защищают от размножения строк при случайном дубле.
    joined = side(before, 'old_').join(side(after, 'new_'), on=KEYS, how='full', coalesce=True, validate='1:1')
    changed = (pl.col('old_on_hand') != pl.col('new_on_hand')) | (pl.col('old_reserved') != pl.col('new_reserved'))
    joined = joined.with_columns(
        pl.when(pl.col('old_present').is_null()).then(pl.lit('INSERT'))
        .when(pl.col('new_present').is_null()).then(pl.lit('DELETE'))
        .when(changed).then(pl.lit('UPDATE')).otherwise(pl.lit('UNCHANGED')).alias('change_type'),
        *[(pl.col('new_' + m).fill_null(0) - pl.col('old_' + m).fill_null(0)).alias('delta_' + m) for m in METRICS],
    ).sort(KEYS)
    columns = KEYS + ['change_type'] + [prefix + metric for metric in METRICS for prefix in ('old_', 'new_', 'delta_')]
    diff = joined.filter(pl.col('change_type') != 'UNCHANGED').select(columns)
    counts = {kind: joined.filter(pl.col('change_type') == kind).height for kind in ('INSERT', 'DELETE', 'UPDATE', 'UNCHANGED')}
    totals = {prefix + m: int(joined.get_column(prefix + m).sum() or 0) for m in METRICS for prefix in ('old_', 'new_', 'delta_')}
    aggregates = joined.group_by('warehouse').agg(*[pl.col(prefix + m).sum().alias(prefix + m) for m in METRICS for prefix in ('old_', 'new_', 'delta_')])
    # Полный пустой склад я показываю явно: все склады scope остаются в сводке.
    per_warehouse = (pl.DataFrame({'warehouse': before.manifest['warehouses']})
                     .join(aggregates, on='warehouse', how='left')
                     .with_columns(pl.all().exclude('warehouse').fill_null(0))
                     .sort('warehouse').to_dicts())
    # Я включаю версию движка в identity: формат Parquet может меняться между версиями.
    identity = {'engine': ENGINE, 'polars_version': pl.__version__, 'before_manifest_sha256': before.manifest_sha256, 'after_manifest_sha256': after.manifest_sha256}
    summary = {**identity, 'report_id': sha256(canonical(identity)), 'before': before.manifest, 'after': after.manifest, 'counts': counts, 'changed_rows': diff.height, 'totals': totals, 'warehouses': per_warehouse}
    return summary, diff
