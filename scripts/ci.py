"""Я останавливаю CI при первом nonzero независимо от оболочки Linux/Windows."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    # Один внешний процесс на workflow step: PowerShell не может скрыть предыдущий
    # nonzero успешной следующей командой. check=True распространяет любой отказ.
    for args in (
        ['-m','pip','install','--require-hashes','-r','requirements.lock'],
        ['-m','pip','check'],
        ['-m','unittest','discover','-s','tests','-v'],
        ['scripts/smoke.py'],
        ['scripts/zip_smoke.py'],
    ):
        subprocess.run([sys.executable,*args],cwd=ROOT,check=True)

if __name__=='__main__':main()
