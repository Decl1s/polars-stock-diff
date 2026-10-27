# Как я разбираю и меняю проект

Я начинаю с README demo, затем прохожу файлы в таком порядке:

| Файл | Что я в нём делаю | Почему отделил |
| --- | --- | --- |
| stock_diff/synthetic.py | Создаю два CSV и manifests, обновляю hashes | Примеры воспроизводимы и не требуют документов |
| stock_diff/core.py: read_snapshot | Проверяю схему, область, типы, hash и уникальность | Невалидный снимок не доходит до сравнения |
| stock_diff/core.py: compare | Full join, статус, delta и итоги | Правила не зависят от CLI и filesystem записи |
| stock_diff/storage.py | Пишу staging, проверяю Parquet/JSON и публикую каталог | Ошибка не оставляет половину отчёта под итоговым именем |
| stock_diff/__main__.py | Связываю параметры, команды и JSON-ответы | Для автоматизации важны короткие коды ошибок |
| tests/test_stock_diff.py | Проверяю инварианты и существенные отказы | Новое поле не должно менять смысл старых состояний |
| scripts/ci.py | Выполняю установку и проверки с check=True | Первый nonzero останавливает CI в обеих ОС |

## Какие параметры я передаю

Я выбираю before и after как папки, output как новый каталог результата.
As_of и scope лежат в manifests: не беру дату из имени файла или часов компьютера.
Флаг simulate-failure нужен только для учебного отказа перед публикацией.

Пример snapshot.json я получаю командой generate. Если вручную изменил stock.csv,
я обновляю manifest таким скриптом из корня проекта:

```python
from pathlib import Path
import csv, hashlib, io, json
folder = Path('workspace/input/after')
raw = (folder / 'stock.csv').read_bytes()
manifest = json.loads((folder / 'snapshot.json').read_text(encoding='utf-8'))
manifest['csv_sha256'] = hashlib.sha256(raw).hexdigest()
manifest['row_count'] = len(list(csv.reader(io.StringIO(raw.decode('utf-8'))))) - 1
(folder / 'snapshot.json').write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding='utf-8')
```

Я не ставлю complete=true для неполной реальной выгрузки, чтобы обойти отказ.
Для нового склада добавляю его в warehouses обоих manifests, соблюдая сортировку,
и добавляю синтетические строки. Для нового правила меняю ENGINE и соответствующие
проверки/ожидания; для новой версии Polars пересобираю lock и проверяю Parquet заново.

## Где я ставлю остановку в отладчике

Я смотрю frame после проверки типов, joined сразу после full join, diff перед publish.
Для WH-A/SKU-001 ожидаю old/new on_hand=10/8, reserved=2/3, available=8/5.
Для WH-A/SKU-003 new значения равны NULL, для WH-B/SKU-005 old значения NULL.
В summary сверяю delta_on_hand=-3. Эти ориентиры помогают увидеть ошибку раньше записи.

Я открываю папку проекта либо общий FreeCode-DE.code-workspace в VS Code. Меню
Terminal → Run Task содержит demo, tests и smoke. Demo спрашивает новый каталог;
при существующем каталоге я выбираю другое имя. IDE и отладчик не являются
обязательными компонентами: команды из README дают тот же результат.
