"""Я публикую проверенный source-only release из ограниченного CI job."""
import hashlib
import json
import os
import re
import subprocess
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from package_release import ROOT,archive

REPOSITORY='Decl1s/polars-stock-diff'
TAG='v0.1.1'

def main():
    if os.environ.get('GITHUB_REPOSITORY')!=REPOSITORY or os.environ.get('GITHUB_REF')!='refs/heads/main' or os.environ.get('GITHUB_EVENT_NAME')!='push':raise ValueError('RELEASE_CONTEXT')
    sha=os.environ['GITHUB_SHA']
    if not re.fullmatch('[a-f0-9]{40}',sha):raise ValueError('RELEASE_SHA')
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()!=sha:raise ValueError('RELEASE_CHECKOUT')
    subprocess.run(['git','diff','--exit-code','HEAD','--'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    evidence=archive();base=ROOT/'artifacts';token=os.environ['GITHUB_TOKEN']
    def api(path,*,method='GET',value=None,raw=None):
        url='https://api.github.com/repos/'+REPOSITORY+path
        if path.startswith('/upload/'):url='https://uploads.github.com/repos/'+REPOSITORY+'/releases/'+path.removeprefix('/upload/')
        data=raw if raw is not None else json.dumps(value).encode() if value is not None else None
        request=Request(url,method=method,data=data,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/octet-stream' if raw is not None else 'application/json'})
        with urlopen(request,timeout=90) as response:return json.load(response)
    try:
        ref=api('/git/ref/tags/'+TAG)
        if ref['object']['type']!='commit' or ref['object']['sha']!=sha:raise ValueError('RELEASE_TAG_CONFLICT')
    except HTTPError as error:
        if error.code!=404:raise
    try:release=api('/releases/tags/'+TAG)
    except HTTPError as error:
        if error.code!=404:raise
        drafts=[r for r in api('/releases?per_page=100') if r['tag_name']==TAG]
        if len(drafts)>1:raise ValueError('RELEASE_AMBIGUOUS_DRAFT')
        release=drafts[0] if drafts else api('/releases',method='POST',value={'tag_name':TAG,'target_commitish':sha,'name':'Разница складских снимков 0.1.1','draft':True,'prerelease':False,'body':'Я обновил навигацию документации и согласовал patch-версию исходного архива. Бизнес-правила и зависимости я сохранил. Я выпускаю учебное сравнение полных складских снимков на Polars 2.1.0: составной full join, INSERT/DELETE/UPDATE, nullable Parquet и проверяемая сводка JSON. Я блокирую partial и дубли, сохраняю старые и новые значения, показываю повтор и восстановление публикации. Подробный разбор и задания — NOTES.md, проверки — VALIDATION и Actions. Архив содержит только PUBLIC_FILES, без входных файлов, результатов, окружения и контактов.'})
    if release['target_commitish']!=sha:raise ValueError('RELEASE_TARGET_CONFLICT')
    rid=release['id'];existing={v['name']:v for v in api('/releases/'+str(rid)+'/assets')}
    for name in (evidence['archive'],'SHA256SUMS'):
        raw=(base/name).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if name in existing:
            if existing[name].get('digest')!='sha256:'+digest:raise ValueError('RELEASE_ASSET_CONFLICT')
        else:
            item=api('/upload/'+str(rid)+'/assets?name='+name,method='POST',raw=raw)
            if item.get('digest')!='sha256:'+digest:raise ValueError('RELEASE_ASSET_DIGEST')
    if release['draft']:release=api('/releases/'+str(rid),method='PATCH',value={'draft':False,'make_latest':'true'})
    ref=api('/git/ref/tags/'+TAG)
    if ref['object']['sha']!=sha or release['draft'] or release['prerelease']:raise ValueError('RELEASE_POSTCONDITION')
    print(json.dumps({'release':release['html_url'],'commit':sha,**evidence}))

if __name__=='__main__':main()
