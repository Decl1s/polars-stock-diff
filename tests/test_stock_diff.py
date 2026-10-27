"""Я проверяю бизнес-разницу, ошибки источника и границу публикации."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

import polars as pl

from stock_diff.__main__ import run
from stock_diff.core import ContractError, FIELDS, MAX_BYTES, canonical, compare, read_snapshot, sha256
from stock_diff.storage import destination_lock, inspect
from stock_diff.synthetic import generate, write_snapshot

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        generate(self.root / 'input')
        self.before = self.root / 'input/before'
        self.after = self.root / 'input/after'
        self.output = self.root / 'report'

    def manifest(self, folder, **changes):
        path = folder / 'snapshot.json'
        value = json.loads(path.read_bytes())
        value.update(changes)
        path.write_bytes(canonical(value))

    def csv_bytes(self, folder, raw):
        (folder / 'stock.csv').write_bytes(raw)
        self.manifest(folder, csv_sha256=sha256(raw))

    def result(self):
        return compare(read_snapshot(self.before), read_snapshot(self.after))

class ContractTests(Fixture):
    def test_expected_four_changes_and_stable_order(self):
        summary, diff = self.result()
        self.assertEqual(summary['counts'], {'INSERT': 1, 'DELETE': 1, 'UPDATE': 2, 'UNCHANGED': 2})
        self.assertEqual(diff.height, 4)
        self.assertEqual(diff.select('warehouse', 'sku').rows(), [('WH-A', 'SKU-001'), ('WH-A', 'SKU-003'), ('WH-B', 'SKU-001'), ('WH-B', 'SKU-005')])
        self.assertEqual(diff.filter(pl.col('change_type') == 'INSERT').get_column('old_on_hand').to_list(), [None])

    def test_totals_and_reconciliation(self):
        summary, diff = self.result()
        self.assertEqual(summary['totals']['old_on_hand'], 26)
        self.assertEqual(summary['totals']['new_on_hand'], 23)
        self.assertEqual(summary['totals']['delta_reserved'], 2)
        self.assertEqual(summary['totals']['delta_available'], -5)
        for metric in ('on_hand', 'reserved', 'available'):
            self.assertEqual(diff['delta_' + metric].sum(), summary['totals']['new_' + metric] - summary['totals']['old_' + metric])
        self.assertEqual(summary['warehouses'][0]['delta_on_hand'], -9)

    def test_zero_is_present_not_a_delete(self):
        raw = (self.after / 'stock.csv').read_bytes().replace(b'WH-A,SKU-001,8,3', b'WH-A,SKU-001,0,0')
        self.csv_bytes(self.after, raw)
        _, diff = self.result()
        row = diff.filter((pl.col('warehouse') == 'WH-A') & (pl.col('sku') == 'SKU-001')).to_dicts()[0]
        self.assertEqual(row['change_type'], 'UPDATE')
        self.assertEqual(row['new_on_hand'], 0)
        self.assertEqual(row['delta_on_hand'], -10)

    def test_same_rows_produce_typed_empty_parquet(self):
        self.csv_bytes(self.after, (self.before / 'stock.csv').read_bytes())
        run(self.before, self.after, self.output)
        shown = inspect(self.output)
        self.assertEqual(shown['summary']['counts']['UNCHANGED'], 5)
        self.assertEqual(shown['changes'], [])
        frame = pl.read_parquet(self.output / 'diff.parquet')
        self.assertEqual(frame.schema['new_on_hand'], pl.Int64)
        self.assertEqual(frame.schema['sku'], pl.String)

    def test_both_empty_still_show_every_declared_warehouse(self):
        header = ','.join(FIELDS).encode() + b'\n'
        for folder in (self.before, self.after):
            self.csv_bytes(folder, header)
            self.manifest(folder, row_count=0)
        summary, diff = self.result()
        self.assertEqual(diff.height, 0)
        self.assertEqual(summary['warehouses'], [{'warehouse': w, **{p + m: 0 for m in ('on_hand', 'reserved', 'available') for p in ('old_', 'new_', 'delta_')}} for w in ('WH-A', 'WH-B')])

    def test_composite_key_and_duplicate_detection(self):
        # Один SKU на двух складах допустим, повтор пары недопустим.
        self.assertEqual(read_snapshot(self.after).frame.height, 5)
        raw = (self.after / 'stock.csv').read_bytes() + b'WH-A,SKU-001,8,3\n'
        self.csv_bytes(self.after, raw)
        self.manifest(self.after, row_count=6)
        with self.assertRaisesRegex(ContractError, 'DUPLICATE_KEY'):
            self.result()

    def test_partial_snapshots_never_imply_deletes(self):
        for folder in (self.before, self.after):
            self.manifest(folder, complete=False)
            with self.assertRaisesRegex(ContractError, 'INCOMPLETE_SNAPSHOT'):
                self.result()
            self.assertFalse(self.output.exists())
            self.manifest(folder, complete=True)

    def test_scope_must_match_even_for_empty_warehouse(self):
        self.manifest(self.after, warehouses=['WH-A', 'WH-B', 'WH-C'])
        with self.assertRaisesRegex(ContractError, 'SCOPE_MISMATCH'):
            self.result()

    def test_time_and_snapshot_identity(self):
        for changes in ({'as_of': '2026-10-25T23:00:00Z'}, {'as_of': '2026-10-24T23:00:00Z'}, {'as_of': '2026-10-26T23:00:00+00:00'}, {'snapshot_id': 'SNAP-BEFORE'}):
            self.manifest(self.after, as_of='2026-10-26T23:00:00Z', snapshot_id='SNAP-AFTER')
            self.manifest(self.after, **changes)
            with self.assertRaises(ContractError):
                self.result()

    def test_strict_quantities_and_keys(self):
        original = (self.after / 'stock.csv').read_bytes()
        for old, new in ((b',8,3', b',-1,0'), (b',8,3', b',008,3'), (b',8,3', b',8,9'), (b',8,3', b',1000000001,3'), (b',8,3', b',8.0,3'), (b'WH-A', b'WH-X'), (b'SKU-001', b'')):
            with self.subTest(value=new):
                self.csv_bytes(self.after, original.replace(old, new))
                with self.assertRaises(ContractError):
                    self.result()

    def test_csv_grammar_encoding_and_columns(self):
        original = (self.after / 'stock.csv').read_bytes()
        for raw in (b'wrong\n', original.replace(b'on_hand', b'sku'), original.replace(b',8,3', b',8,3,extra'), original.replace(b',8,3', b',8'), original.replace(b'SKU-001', b'\xff'), original + b'"unclosed'):
            self.csv_bytes(self.after, raw)
            with self.assertRaises(ContractError):
                self.result()

    def test_manifest_types_and_duplicate_json_keys(self):
        original = (self.after / 'snapshot.json').read_bytes()
        for changes in ({'schema_version': True}, {'row_count': True}, {'warehouses': ['WH-B', 'WH-A']}, {'warehouses': ['WH-A', 'WH-A']}, {'extra': 1}, {'complete': 1}):
            (self.after / 'snapshot.json').write_bytes(original)
            self.manifest(self.after, **changes)
            with self.assertRaises(ContractError):
                self.result()
        (self.after / 'snapshot.json').write_bytes(b'{"schema_version":1,"schema_version":2}')
        with self.assertRaisesRegex(ContractError, 'JSON_INVALID'):
            self.result()

    def test_source_hash_and_declared_count(self):
        original = (self.after / 'stock.csv').read_bytes()
        (self.after / 'stock.csv').write_bytes(original + b'\n')
        with self.assertRaisesRegex(ContractError, 'CSV_HASH_MISMATCH'):
            self.result()
        (self.after / 'stock.csv').write_bytes(original)
        self.manifest(self.after, row_count=4)
        with self.assertRaisesRegex(ContractError, 'ROW_COUNT_MISMATCH'):
            self.result()

    def test_explicit_byte_and_row_limits(self):
        self.csv_bytes(self.after, b'x' * (MAX_BYTES + 1))
        with self.assertRaisesRegex(ContractError, 'INPUT_TOO_LARGE'):
            self.result()
        raw = b'warehouse,sku,on_hand,reserved\n' + b'WH-A,SKU-001,1,0\n' * 10_001
        self.csv_bytes(self.after, raw)
        self.manifest(self.after, row_count=10_000)
        with self.assertRaisesRegex(ContractError, 'TOO_MANY_ROWS'):
            self.result()

    def test_permuted_rows_same_business_result_new_file_identity(self):
        summary, diff = self.result()
        rows = (self.after / 'stock.csv').read_bytes().splitlines()
        self.csv_bytes(self.after, b'\n'.join([rows[0], *reversed(rows[1:])]) + b'\n')
        second, another = self.result()
        self.assertTrue(diff.equals(another))
        self.assertEqual(summary['counts'], second['counts'])
        self.assertNotEqual(summary['report_id'], second['report_id'])

class PublicationTests(Fixture):
    def test_roundtrip_replay_and_hashes(self):
        first = run(self.before, self.after, self.output)
        replay = run(self.before, self.after, self.output)
        self.assertFalse(first['reused'])
        self.assertTrue(replay['reused'])
        self.assertEqual(first['report_id'], replay['report_id'])
        self.assertEqual(len(inspect(self.output)['changes']), 4)
        self.assertEqual({p.name for p in self.output.iterdir()}, {'summary.json', 'bundle.json', 'diff.parquet'})

    def test_existing_foreign_directory_and_conflict_are_preserved(self):
        self.output.mkdir()
        (self.output / 'keep.txt').write_text('synthetic', encoding='utf-8')
        with self.assertRaisesRegex(ContractError, 'BUNDLE_LAYOUT'):
            run(self.before, self.after, self.output)
        self.assertEqual((self.output / 'keep.txt').read_text(), 'synthetic')
        target = self.root / 'other-report'
        run(self.before, self.after, target)
        old = (target / 'bundle.json').read_bytes()
        self.csv_bytes(self.after, (self.after / 'stock.csv').read_bytes().replace(b',8,3', b',9,3'))
        with self.assertRaisesRegex(ContractError, 'OUTPUT_CONFLICT'):
            run(self.before, self.after, target)
        self.assertEqual((target / 'bundle.json').read_bytes(), old)

    def test_staging_failure_then_retry(self):
        with self.assertRaisesRegex(ContractError, 'SIMULATED_BEFORE_RENAME'):
            run(self.before, self.after, self.output, simulate_failure=True)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.report*')), [])
        self.assertFalse(run(self.before, self.after, self.output)['reused'])

    def test_concurrent_destination_is_busy(self):
        with destination_lock(self.output):
            with self.assertRaisesRegex(ContractError, 'OUTPUT_BUSY'):
                run(self.before, self.after, self.output)
        self.assertFalse(self.output.exists())

    def test_damage_is_detected_without_overwriting(self):
        run(self.before, self.after, self.output)
        (self.output / 'diff.parquet').write_bytes(b'damaged')
        with self.assertRaisesRegex(ContractError, 'BUNDLE_HASH_MISMATCH'):
            inspect(self.output)
        with self.assertRaises(ContractError):
            run(self.before, self.after, self.output)
        self.assertEqual((self.output / 'diff.parquet').read_bytes(), b'damaged')

    def test_output_cannot_modify_source(self):
        with self.assertRaisesRegex(ContractError, 'OUTPUT_IN_SOURCE'):
            run(self.before, self.after, self.after / 'report')
        self.assertFalse((self.after / 'report').exists())
