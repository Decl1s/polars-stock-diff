"""Я проверяю запуск приложения после распаковки поставки без исходного checkout."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from package_release import ROOT, NAME, archive

archive()
with tempfile.TemporaryDirectory(prefix='stock-zip-') as tmp:
    folder = Path(tmp)
    with zipfile.ZipFile(ROOT / 'artifacts' / NAME) as bundle:
        bundle.extractall(folder)
    result = subprocess.run([sys.executable, '-m', 'stock_diff', 'demo', '--directory', 'workspace/demo'], cwd=folder, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise AssertionError(result.stderr[-1000:] + result.stdout[-1000:])
    payload = json.loads(result.stdout)
    assert payload['first']['counts'] == {'INSERT': 1, 'DELETE': 1, 'UPDATE': 2, 'UNCHANGED': 2}
    assert payload['partial_blocked'] and payload['replay_reused']
    print(json.dumps({'zip_round_trip': True, 'changed_rows': 4, 'partial_blocked': True}))
