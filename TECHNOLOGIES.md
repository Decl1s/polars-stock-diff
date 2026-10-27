# Какие технологии я использую

27.10.2026 · polars-stock-diff 0.1.0. Я проверил официальный PyPI: текущая стабильная
Polars 2.1.0 опубликована 25.10.2026. API join дополнительно сверил с установленной
версией через inspect.signature, а поведение подтвердил тестами.

| Компонент | Версия | Назначение и причина выбора | Официальный источник |
| --- | --- | --- | --- |
| CPython | локально 3.12.15; CI Linux 3.12.15, Windows 3.12.10 | CLI, строгий CSV/JSON, файлы и тесты; диапазон приложения >=3.12,<3.13 | [Python 3.12](https://docs.python.org/3.12/) |
| polars | 2.1.0 | Прямая dependency: DataFrame, expressions, full join, group_by, Parquet | [PyPI](https://pypi.org/project/polars/2.1.0/), [join](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.join.html) |
| polars-runtime-32 | 2.1.0 | Единственная транзитивная dependency: готовый native runtime; Rust toolchain не устанавливаю | [PyPI](https://pypi.org/project/polars-runtime-32/2.1.0/) |
| Parquet | формат, writer/reader Polars 2.1.0 | Типизированные nullable колонки, без PyArrow/pandas | [Polars IO](https://docs.pola.rs/user-guide/io/parquet/), [Parquet](https://parquet.apache.org/docs/) |
| CSV/JSON | UTF-8, contract v1 | Обмен со снимками и читаемая сводка | [csv](https://docs.python.org/3.12/library/csv.html), [json](https://docs.python.org/3.12/library/json.html) |
| SHA-256 | stdlib hashlib | Проверка согласованности файлов и identity; не аутентификация | [hashlib](https://docs.python.org/3.12/library/hashlib.html) |
| uv | 0.13.1 локально | Venv, universal lock с hashes, установка и pip check | [uv compile](https://docs.astral.sh/uv/pip/compile/) |
| Git | 2.53.0 локально | Собственный корень и ветки codex/ | [Git](https://git-scm.com/docs) |
| GitHub Actions | hosted Ubuntu 24.04 / Windows 2025 | Матрица проверок и ограниченный выпуск source-only | [Actions](https://docs.github.com/en/actions) |
| actions/checkout | 7.0.1, SHA 3d3c42e5aac5ba805825da76410c181273ba90b1 | Checkout без сохранения credentials | [Официальный репозиторий](https://github.com/actions/checkout) |
| actions/setup-python | 7.0.0, SHA 5fda3b95a4ea91299a34e894583c3862153e4b97 | Явные версии Python | [Официальный репозиторий](https://github.com/actions/setup-python) |

Все runtime distributions перечислены в этой таблице: их ровно две. Полные hashes
колёс разных платформ закреплены в requirements.lock; requirements.in содержит
только прямую dependency. Я не использую необязательные extras и не добавляю numpy,
pandas, PyArrow или отдельную базу. Наличие macOS wheel не является моим тестом macOS.

Я использую stdlib argparse,csv,dataclasses,datetime,hashlib,io,json,pathlib,re,
contextlib,os,shutil,tempfile,subprocess,sys,unittest,zipfile,urllib и tomllib при
подготовке материалов. pip в CI входит в установленный Python, не является runtime
dependency приложения. Локальный uv venv не содержит pip; обычный python -m venv из
README содержит его. ZIP собираю stdlib ZIP_STORED по allowlist, с фиксированными
временем и атрибутами. Временные файлы flush/fsync, затем каталог rename в той же FS;
это не обещание долговечности при потере питания.

VS Code tasks.json — необязательная конфигурация редактора без расширений и сервисов.
Я проверяю соответствующие команды; графическую IDE отдельно не проверял.
Workflow вызывает один scripts/ci.py, а каждый subprocess использует check=True:
[договор subprocess](https://docs.python.org/3.12/library/subprocess.html#subprocess.run).
Фактические CI/ОС результаты фиксирую в VALIDATION и Actions.
