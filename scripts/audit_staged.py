#!/usr/bin/env python3
"""Inspect actual index blobs, including known local secret values; never print matches."""
import json, os, pathlib, re, subprocess, sys, urllib.parse
ROOT=pathlib.Path(__file__).resolve().parents[1]
def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args])
secret_values=set()
def collect(obj):
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k in ['password','username','uuid','api_secret','server','url'] and isinstance(v,str):
                if len(v)>=6:secret_values.add(v)
                if k=='url':
                    for values in urllib.parse.parse_qs(urllib.parse.urlsplit(v).query).values():
                        secret_values.update(x for x in values if len(x)>=6)
            else:collect(v)
    elif isinstance(obj,list):
        for v in obj:collect(v)
config=pathlib.Path(os.environ.get('AI_PROXY_CONFIG',pathlib.Path.home()/'.config/ai-proxy'))
for name in ['credentials.json','nodes.json','subscriptions.json']:
    p=config/name
    if p.exists():collect(json.loads(p.read_text()))
entries=[];bad=[]
for row in git('ls-files','--stage','-z').split(b'\0'):
    if not row:continue
    metadata,path=row.split(b'\t',1);mode,sha,stage=metadata.decode().split();name=path.decode()
    if stage!='0' or mode not in ['100644','100755']:bad.append((name,'unsupported index entry'));continue
    raw=git('show',':'+name)
    try:text=raw.decode()
    except UnicodeError:bad.append((name,'binary file not permitted'));continue
    if any(v.encode() in raw for v in secret_values):bad.append((name,'contains known local secret'))
    if re.search(r'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,})|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}',text):bad.append((name,'credential pattern'))
    if name.split('/')[-1] in ['runtime.json','credentials.json','nodes.json','subscriptions.json','settings.json','custom-rules.json','info.txt']:bad.append((name,'sensitive runtime filename'))
    entries.append({'path':name,'mode':mode,'type':'blob','content':text})
if bad:
    print(json.dumps({'result':'FAILED','files':bad},ensure_ascii=False),file=sys.stderr);sys.exit(1)
if '--manifest' in sys.argv:print(json.dumps(entries,ensure_ascii=False))
else:print(json.dumps({'result':'PASS','staged_files':len(entries),'known_secret_values_checked':len(secret_values),'index_blobs_inspected':True}))
