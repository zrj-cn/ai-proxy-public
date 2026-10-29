#!/usr/bin/env python3
"""Observe real mihomo final destinations and route counters using local slow HTTP targets."""
import concurrent.futures, http.client, json, pathlib, sys, tempfile, time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_proxy import core as c
from ai_proxy.traffic import TrafficModel
from integration import server,Proxy
import socketserver,base64

class SlowTarget(socketserver.StreamRequestHandler):
    def handle(self):
        self.rfile.readline()
        while self.rfile.readline() not in [b'',b'\r\n']:pass
        try:
            self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: 131072\r\nConnection: close\r\n\r\n')
            for _ in range(16):self.wfile.write(b'x'*8192);self.wfile.flush();time.sleep(.08)
        except OSError:pass

def request(port,target,host):
    cred=c.read(c.C/'credentials.json');auth=base64.b64encode((cred['username']+':'+cred['password']).encode()).decode()
    con=http.client.HTTPConnection('127.0.0.1',port,timeout=5);con.set_tunnel(host,target,{'Proxy-Authorization':'Basic '+auth})
    try:con.request('GET','/');r=con.getresponse();return r.status==200 and len(r.read())==131072
    finally:con.close()

def main():
    binary=c.BIN.resolve();old={k:getattr(c,k) for k in ['C','D','S','BIN']};verdicts=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        verdicts.append({'check':name,'result':'通过'})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);c.C=root/'config';c.D=root/'data';c.S=root/'state';c.BIN=binary;c.init()
            with server(Proxy,'a:local-a') as a,server(Proxy,'b:local-b') as b,server(SlowTarget) as target:
                nodes={'a':{'type':'http','server':'127.0.0.1','port':a.server_address[1],'username':'a','password':'local-a'},'b':{'type':'http','server':'127.0.0.1','port':b.server_address[1],'username':'b','password':'local-b'}}
                st=c.settings();st.update(entry='a',exit='b');c.save(c.C/'settings.json',st);c.save(c.C/'nodes.json',nodes)
                c.save(c.C/'custom-rules.json',[{'type':'DOMAIN','value':'ordinary.fixture.test','action':'FALLBACK'}])
                port,ap=c.free_port(),c.free_port();cfg=c.generate(port=port,api_port=ap)
                cfg['rules']=[r for r in cfg['rules'] if not r.startswith(('IP-CIDR,','IP-CIDR6,'))]
                hosts=['api.anthropic.com','raw.githubusercontent.com','ordinary.fixture.test'];cfg['hosts']={h:'127.0.0.1' for h in hosts}
                # Deterministic outbound selection tests display attribution, not the health checker (covered separately).
                cfg['proxy-groups']=[{'name':'CHAIN_OR_DIRECT','type':'select','proxies':['DIRECT','EXIT_B']}]
                with c.isolated(cfg):
                    m=TrafficModel();m.update(c.api('/connections',port=ap))
                    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                        fs=[pool.submit(request,port,target.server_address[1],h) for h in hosts]
                        seen=set();had_speed=False;internal_types=set();deadline=time.monotonic()+4
                        while time.monotonic()<deadline and not all(f.done() for f in fs):
                            snapshot=c.api('/connections',port=ap);internal_types.update(x.get('metadata',{}).get('type','') for x in snapshot.get('connections') or [] if not x.get('metadata',{}).get('host'));m.update(snapshot);seen.update((r['target'],r['channel']) for r in m.view());had_speed|=any(r['down_rate']>0 for r in m.view());time.sleep(.05)
                        check('三个最终目标请求完成',all(f.result() for f in fs))
                    check('Claude实际完整代理与最终域名',('Claude','CHAIN') in seen and any('api.anthropic.com' in r['hosts'] for r in m.view()))
                    check('GitHub实际DIRECT',('GitHub','DIRECT') in seen)
                    check('可回退组实际DIRECT单独归类',('ordinary.fixture.test','FALLBACK_DIRECT') in seen)
                    check('实时采样获得正下载速率与业务字节',had_speed and m.route_summary('CHAIN')['down']>0)
                    check('真实Inner中转连接存在且列表已剔除',internal_types=={'Inner'} and all(r['target'] not in ['ENTRY_A','EXIT_B','127.0.0.1'] for r in m.view()))
                    time.sleep(.15);m.update(c.api('/connections',port=ap))
                    check('结束连接保留近期记录且速率归零',all(r['active']==0 and r['down_rate']==0 for r in m.view()))
    finally:
        for k,v in old.items():setattr(c,k,v)
    print(json.dumps(verdicts,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
