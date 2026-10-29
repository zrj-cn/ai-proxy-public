import contextlib,io,pathlib,sys,subprocess,json,hashlib,tempfile
from unittest import mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
if '--live' not in sys.argv:raise SystemExit('此验收会短暂重启本项目服务；显式运行 python3 tests/acceptance_live.py --live。不要用于承担当前模型连接的实例。')
from ai_proxy import core as c
results={}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
files=[c.C/x for x in ['credentials.json','settings.json','nodes.json','custom-rules.json','subscriptions.json']]+[c.S/'runtime.json']
before={str(p):digest(p) for p in files}
r=subprocess.run(['./install.sh','--non-interactive'],cwd=c.ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40)
results['重复安装保持设置节点密钥配置']='通过' if r.returncode==0 and before=={str(p):digest(p) for p in files} else '失败'
old=c.snapshot();old_runtime=digest(c.S/'runtime.json')
def bad_inputs():
 ns=c.read(c.C/'nodes.json');ns[c.settings()['entry']]['port']=0;c.save(c.C/'nodes.json',ns)
try:c.transaction(bad_inputs);failed=False
except c.Error:failed=True
results['非法输入回滚']='通过' if failed and c.snapshot()==old and digest(c.S/'runtime.json')==old_runtime else '失败'
with tempfile.TemporaryDirectory(dir=c.S) as td:
 td=pathlib.Path(td);bad=td/'invalid.json';c.save(bad,{'proxies':[{'name':'bad','type':'invalid'}],'rules':['MATCH,bad']})
 try:c.api('/configs?force=true','PUT',{'path':str(bad)});rejected=False
 except c.Error:rejected=True
 c.ready_api();results['失败API重载旧实例保持可用']='通过' if rejected and digest(c.S/'runtime.json')==old_runtime else '失败'
 old_binary=c.BIN.resolve();fake=td/'broken-mihomo'
 c.write(fake,'#!/bin/sh\nif [ "$1" = "-t" ]; then exit 0; fi\nexit 1\n',0o700)
 try:
  with mock.patch.object(c,'download_version',return_value=fake):c.upgrade('v0.0.0')
  rejected=False
 except c.Error:rejected=True
 c.ready_api();results['新核心启动失败自动恢复旧核心']='通过' if rejected and c.BIN.resolve()==old_binary and c.active() else '失败'
 c.systemctl('reset-failed','ai-proxy.service')
r=c.systemctl('restart','ai-proxy.service');c.ready_api();results['服务实际重启']='通过' if r.returncode==0 and c.active() else '失败'
c.save(c.S/'acceptance.json',results)
print(json.dumps(results,ensure_ascii=False,indent=2))
