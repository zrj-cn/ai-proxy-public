#!/usr/bin/env python3
"""Real pinned mihomo against local recording HTTP proxies, no Internet needed.
Credentials are ephemeral in memory and private files; stdout contains only verdicts.
"""
import base64, concurrent.futures, contextlib, http.client, json, os, pathlib, select, socket, socketserver, subprocess, sys, tempfile, threading, time
from unittest import mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_proxy import core as c

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True;daemon_threads=True

class Proxy(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(4)
        line=self.rfile.readline(4096).decode().strip();headers={}
        while True:
            l=self.rfile.readline(4096)
            if l in [b'',b'\r\n']:break
            k,_,v=l.decode().partition(':');headers[k.lower()]=v.strip()
        expected='Basic '+base64.b64encode(self.server.auth.encode()).decode()
        if headers.get('proxy-authorization')!=expected:
            self.wfile.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="test"\r\nContent-Length: 0\r\n\r\n');return
        parts=line.split()
        if len(parts)<2 or parts[0]!='CONNECT':return
        host,port=parts[1].rsplit(':',1)
        self.server.targets.append((host,int(port)))
        try:up=socket.create_connection(('127.0.0.1' if host.endswith('.fixture.test') else host,int(port)),3)
        except OSError:
            self.wfile.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n');return
        with up:
            self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n');self.wfile.flush()
            for _ in range(200):
                ready,_,_=select.select([self.connection,up],[],[],.1)
                for src in ready:
                    data=src.recv(65536)
                    if not data:return
                    (up if src is self.connection else self.connection).sendall(data)

class Target(socketserver.StreamRequestHandler):
    def handle(self):
        self.server.hits+=1
        self.rfile.readline()
        while self.rfile.readline() not in [b'',b'\r\n']:pass
        self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK')

@contextlib.contextmanager
def server(cls,auth=''):
    s=Server(('127.0.0.1',0),cls);s.auth=auth;s.targets=[];s.hits=0
    t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
    try:yield s
    finally:s.shutdown();s.server_close();t.join()

def request(p,target,kind='valid',host='127.0.0.1'):
    cred=c.read(c.C/'credentials.json');headers={}
    if kind!='none':
        v=cred['username']+':'+cred['password'] if kind=='valid' else 'wrong:wrong'
        headers['Proxy-Authorization']='Basic '+base64.b64encode(v.encode()).decode()
    con=http.client.HTTPConnection('127.0.0.1',p,timeout=5);con.set_tunnel(host,target,headers)
    try:
        con.request('GET','/');r=con.getresponse();return r.status==200 and r.read(2)==b'OK'
    except Exception:return False
    finally:con.close()

def main():
    binary=c.BIN.resolve()
    if not binary.exists():raise SystemExit('先运行 install.sh 下载官方核心')
    results=[]
    def check(name,value):
        results.append({'check':name,'result':'通过' if value else '失败'})
        if not value:raise AssertionError(name)
    with tempfile.TemporaryDirectory() as td:
        old={k:getattr(c,k) for k in ['C','D','S','BIN']}
        try:
            p=pathlib.Path(td)
            c.C=p/'config';c.D=p/'data';c.S=p/'state';c.BIN=binary;c.init()
            with server(Proxy,'a:local-test-a') as a,server(Proxy,'b:local-test-b') as b,server(Target) as target:
                nodes={'a':{'type':'http','server':'127.0.0.1','port':a.server_address[1],'username':'a','password':'local-test-a'},'b':{'type':'http','server':'127.0.0.1','port':b.server_address[1],'username':'b','password':'local-test-b'}}
                st=c.settings();st.update(entry='a',exit='b');c.save(c.C/'settings.json',st);c.save(c.C/'nodes.json',nodes)
                p,ap=c.free_port(),c.free_port();cfg=c.generate(port=p,api_port=ap,forced='chain');tp=target.server_address[1]
                c.validate(cfg)
                with c.isolated(cfg):
                    check('无凭证拒绝',not request(p,tp,'none'))
                    check('错误凭证拒绝',not request(p,tp,'wrong'))
                    check('有效凭证完成真实 A→B 请求',request(p,tp))
                    check('A 实际拨号 B',a.targets==[('127.0.0.1',b.server_address[1])])
                    check('B 实际拨号目标',b.targets==[('127.0.0.1',tp)] and target.hits==1)
                    c.save(c.S/'bad.json',{'proxies':[{'name':'bad','type':'not-valid'}],'rules':['MATCH,bad']})
                    with mock.patch.object(c,'settings',return_value=dict(st,api_port=ap)):
                        try:c.api('/configs?force=true','PUT',{'path':str(c.S/'bad.json')});failed=False
                        except c.Error:failed=True
                    check('API 拒绝非法重载',failed)
                    check('失败重载后旧链路仍可用',request(p,tp))
                for label in ['ENTRY_A','EXIT_B']:
                    before=(len(a.targets),len(b.targets),target.hits)
                    with socket.socket() as dead:
                        dead.bind(('127.0.0.1',0));p,ap=c.free_port(),c.free_port();bad=c.generate(port=p,api_port=ap,forced='chain')
                        n=next(x for x in bad['proxies'] if x['name']==label);n['server']='127.0.0.1';n['port']=dead.getsockname()[1]
                        with c.isolated(bad):ok=request(p,tp)
                    check(label+' 不可用时请求失败',not ok)
                    check(label+' 不可用时目标没有收到绕过请求',target.hits==before[2])
                    if label=='ENTRY_A':check('A 不可用时没有直接拨号 B',len(b.targets)==before[1])
                for mode,expected in [('A',a),('B',b)]:
                    p,ap=c.free_port(),c.free_port();cfg=c.generate(port=p,api_port=ap,forced=mode)
                    with c.isolated(cfg):check('隔离单独检测 '+mode,request(p,tp))
                # Opt-in fallback uses the full chain first; known AI can never enter this group.
                c.save(c.C/'custom-rules.json',[{'type':'DOMAIN','value':'ordinary.fixture.test','action':'FALLBACK','source':'custom'}])
                for broken in [False,True]:
                    with socket.socket() as dead:
                        dead.bind(('127.0.0.1',0));p,ap=c.free_port(),c.free_port();fcfg=c.generate(port=p,api_port=ap)
                        fcfg['hosts']={'ordinary.fixture.test':'127.0.0.1','api.anthropic.com':'127.0.0.1','github.com':'127.0.0.1'}
                        group=fcfg['proxy-groups'][0];group.update(url='http://127.0.0.1:'+str(tp)+'/',interval=1,lazy=False,timeout=500,**{'expected-status':200})
                        if broken:fcfg['proxies'][0]['port']=dead.getsockname()[1]
                        with c.isolated(fcfg):
                            expected='DIRECT' if broken else 'EXIT_B';end=time.monotonic()+8
                            while time.monotonic()<end:
                                try:
                                    if c.api('/proxies/CHAIN_OR_DIRECT',port=ap).get('now')==expected:break
                                except c.Error:pass
                                time.sleep(.1)
                            check('健康链路优先完整A→B' if not broken else '坏A后健康检查切换可回退组为DIRECT',c.api('/proxies/CHAIN_OR_DIRECT',port=ap).get('now')==expected)
                            check('可回退域名实际请求成功',request(p,tp,host='ordinary.fixture.test'))
                            if broken:
                                check('可回退组已直连时AI仍失败不回退',not request(p,tp,host='api.anthropic.com'))
                                check('明确DIRECT域名不依赖代理链',request(p,tp,host='github.com'))
        finally:
            for k,v in old.items():setattr(c,k,v)
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
