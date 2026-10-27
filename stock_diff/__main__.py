"""Я даю команды generate/compare/inspect/demo без внешнего сервера."""
import argparse
import json
from pathlib import Path

import polars as pl

from .core import ContractError, compare, read_snapshot
from .storage import inspect, publish
from .synthetic import generate

def run(before, after, output, *, simulate_failure=False):
    # Я запрещаю создавать отчёт внутри входа, чтобы не изменять источник побочным файлом.
    target = Path(output).resolve()
    if any(target.is_relative_to(Path(source).resolve()) for source in (before, after)):
        raise ContractError('OUTPUT_IN_SOURCE')
    summary, diff = compare(read_snapshot(before), read_snapshot(after))
    return publish(output, summary, diff, simulate_failure=simulate_failure)

def demo(directory):
    directory = Path(directory)
    if directory.exists():
        raise ContractError('DEMO_REQUIRES_NEW_DIRECTORY')
    generate(directory / 'input')
    args = (directory / 'input/before', directory / 'input/after')
    first = run(*args, directory / 'report')
    replay = run(*args, directory / 'report')
    generate(directory / 'partial', 'partial')
    try:
        run(directory / 'partial/before', directory / 'partial/after', directory / 'invalid-report')
    except ContractError as error:
        if str(error) != 'INCOMPLETE_SNAPSHOT':
            raise
    else:
        raise ContractError('DEMO_PARTIAL_NOT_BLOCKED')
    try:
        run(*args, directory / 'recovered-report', simulate_failure=True)
    except ContractError as error:
        if str(error) != 'SIMULATED_BEFORE_RENAME':
            raise
    else:
        raise ContractError('DEMO_FAILURE_NOT_TRIGGERED')
    if (directory / 'invalid-report').exists() or (directory / 'recovered-report').exists():
        raise ContractError('DEMO_PARTIAL_PUBLICATION')
    recovered = run(*args, directory / 'recovered-report')
    if not replay['reused'] or first['report_id'] != recovered['report_id']:
        raise ContractError('DEMO_REPLAY')
    return {'first': first, 'replay_reused': replay['reused'], 'partial_blocked': True, 'failure_kept_output_absent': True, 'recovery': recovered, 'changes': inspect(directory / 'report')['changes']}

def main():
    parser = argparse.ArgumentParser(description='Я сравниваю два полных снимка складских остатков')
    sub = parser.add_subparsers(dest='command', required=True)
    gen = sub.add_parser('generate', help='Я создаю синтетические входы в новом каталоге')
    gen.add_argument('--directory', type=Path, required=True)
    gen.add_argument('--scenario', choices=('valid', 'partial', 'duplicate', 'reserved'), default='valid')
    cmp = sub.add_parser('compare', help='Я публикую INSERT/DELETE/UPDATE в новый каталог')
    cmp.add_argument('--before', type=Path, required=True)
    cmp.add_argument('--after', type=Path, required=True)
    cmp.add_argument('--output', type=Path, required=True)
    cmp.add_argument('--simulate-failure', action='store_true', help='Я моделирую сбой перед rename')
    show = sub.add_parser('inspect', help='Я проверяю hashes и читаю JSON/Parquet')
    show.add_argument('--output', type=Path, required=True)
    example = sub.add_parser('demo', help='Я показываю сравнение, повтор, отказ и восстановление')
    example.add_argument('--directory', type=Path, default=Path('workspace/demo'))
    args = parser.parse_args()
    try:
        if args.command == 'generate':
            result = generate(args.directory, args.scenario)
        elif args.command == 'compare':
            result = run(args.before, args.after, args.output, simulate_failure=args.simulate_failure)
        elif args.command == 'inspect':
            result = inspect(args.output)
        else:
            result = demo(args.directory)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, pl.exceptions.PolarsError) as error:
        print(json.dumps({'success': False, 'error': str(error) if isinstance(error, ContractError) else type(error).__name__}))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
