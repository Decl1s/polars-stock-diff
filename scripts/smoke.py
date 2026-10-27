"""Я проверяю команды отдельными процессами и сохранённый Parquet."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory(prefix='stock-cli-') as tmp:
    folder = Path(tmp)
    def cli(*args, expected=0):
        result = subprocess.run([sys.executable, '-m', 'stock_diff', *map(str, args)], cwd=ROOT, capture_output=True, text=True, timeout=30)
        if result.returncode != expected:
            raise AssertionError(result.stderr[-1000:] + result.stdout[-1000:])
        return json.loads(result.stdout)
    demo = cli('demo', '--directory', folder / 'demo')
    assert demo['first']['counts'] == {'INSERT': 1, 'DELETE': 1, 'UPDATE': 2, 'UNCHANGED': 2}
    assert demo['partial_blocked'] and demo['failure_kept_output_absent'] and demo['replay_reused']
    shown = cli('inspect', '--output', folder / 'demo/report')
    assert len(shown['changes']) == 4 and shown['summary']['totals']['delta_on_hand'] == -3
    assert cli('demo', '--directory', folder / 'demo', expected=2)['error'] == 'DEMO_REQUIRES_NEW_DIRECTORY'
    for scenario, code in [('duplicate', 'DUPLICATE_KEY'), ('reserved', 'QUANTITY_RANGE')]:
        cli('generate', '--directory', folder / scenario, '--scenario', scenario)
        result = cli('compare', '--before', folder / scenario / 'before', '--after', folder / scenario / 'after', '--output', folder / ('out-' + scenario), expected=2)
        assert result['error'] == code
        assert not (folder / ('out-' + scenario)).exists()
    print(json.dumps({'cli': True, 'changed_rows': 4, 'parquet_roundtrip': True, 'replay': True, 'partial_blocked': True, 'staging_failure_recovered': True, 'invalid_inputs_no_output': True}))
