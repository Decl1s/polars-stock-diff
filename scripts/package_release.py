"""Я собираю воспроизводимый архив только из явно разрешённых UTF-8 исходников."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
NAME='polars-stock-diff-0.1.1-sources.zip'

def sources():
    names=(ROOT/'PUBLIC_FILES.txt').read_text(encoding='utf-8').splitlines()
    if names!=sorted(set(names)) or 'PUBLIC_FILES.txt' not in names:raise ValueError('MANIFEST_ORDER')
    result={}
    forbidden=[r'/ho'+'me/',r'gh'+'p_[A-Za-z0-9]{20,}',r'github'+r'_pat_[A-Za-z0-9_]{20,}',r'-----BE'+'GIN [A-Z ]*PRIVATE KEY-----',r'[A-Za-z0-9._%+-]+@'+r'[A-Za-z0-9.-]+\.[A-Za-z]{2,}']
    for name in names:
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or str(path)!=name or not path.parts:raise ValueError('MANIFEST_PATH')
        file=ROOT/name
        if any(parent.is_symlink() for parent in [file,*file.parents] if parent!=ROOT.parent):raise ValueError('MANIFEST_SYMLINK')
        raw=file.read_bytes();value=raw.decode('utf-8')
        if len(raw)>500_000 or any(re.search(pattern,value) for pattern in forbidden):raise ValueError('SOURCE_PRIVACY:'+name)
        if any(part in {'.git','.venv','workspace','artifacts','__pycache__','AGENTS.md'} for part in path.parts):raise ValueError('SOURCE_PRIVATE_PATH')
        result[name]=raw
    return result

def archive(output=None):
    contents=sources();folder=Path(output) if output is not None else ROOT/'artifacts'
    folder.mkdir(parents=True,exist_ok=True);target=folder/NAME
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_STORED) as bundle:
        for name,raw in contents.items():
            info=zipfile.ZipInfo(name,date_time=(2026,10,27,0,0,0));info.create_system=3;info.external_attr=0o100644<<16
            bundle.writestr(info,raw)
    with zipfile.ZipFile(target) as bundle:
        if bundle.namelist()!=list(contents) or any(bundle.read(name)!=raw for name,raw in contents.items()):raise ValueError('ZIP_MISMATCH')
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (folder/'SHA256SUMS').write_bytes((digest+'  '+NAME+'\n').encode())
    return {'archive':NAME,'sha256':digest,'files':len(contents),'size':target.stat().st_size}

if __name__=='__main__':print(json.dumps(archive(),sort_keys=True))
