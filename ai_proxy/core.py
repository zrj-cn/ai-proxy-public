from __future__ import annotations
import base64, contextlib, copy, fcntl, gzip, hashlib, http.client, ipaddress, json, os, pathlib, platform, re, secrets, shutil, socket, ssl, subprocess, tempfile, time, threading, urllib.parse, urllib.request
P = pathlib.Path
ROOT = P(__file__).resolve().parent.parent
HOME = P.home()
C = P(os.environ.get('AI_PROXY_CONFIG', HOME/'.config/ai-proxy'))
D = P(os.environ.get('AI_PROXY_DATA', HOME/'.local/share/ai-proxy'))
S = P(os.environ.get('AI_PROXY_STATE', HOME/'.local/state/ai-proxy'))
UNIT = HOME/'.config/systemd/user/ai-proxy.service'
BIN = D/'mihomo'
PROXY_KEYS = ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','WS_PROXY','WSS_PROXY','ws_proxy','wss_proxy']
class Error(Exception): pass
_ISOLATED={}

def private_dir(p):
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    if p.is_symlink() or p.stat().st_uid != os.getuid(): raise Error('目录必须属于当前账号且不能为符号链接')
    p.chmod(0o700)

def write(p, data, mode=0o600):
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if p.parent.is_symlink() or p.parent.stat().st_uid!=os.getuid():raise Error('输出目录必须属于当前用户且不能为符号链接')
    fd, name = tempfile.mkstemp(dir=p.parent, prefix='.new-')
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),mode)
            f.write(data.encode() if isinstance(data,str) else data);f.flush();os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name): os.unlink(name)

def save(p,obj): write(p,json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def read(p,default=None): return json.loads(p.read_text()) if p.exists() else copy.deepcopy(default)
@contextlib.contextmanager
def lock():
    private_dir(C)
    with (C/'lock').open('a') as f:
        os.chmod(f.name,0o600);fcntl.flock(f,fcntl.LOCK_EX);yield

def init(port=17890,api_port=19090):
    for p in [C,D,S,S/'backups']:private_dir(p)
    if not (C/'settings.json').exists():save(C/'settings.json',{'port':port,'api_port':api_port,'entry':None,'exit':None,'dev_rules':False,'applications':[]})
    if not (C/'credentials.json').exists():save(C/'credentials.json',{'username':'ai'+secrets.token_hex(5),'password':secrets.token_urlsafe(32),'api_secret':secrets.token_urlsafe(40)})
    for name,default in [('nodes.json',{}),('subscriptions.json',{}),('custom-rules.json',[])]:
        if not (C/name).exists():save(C/name,default)
    for f in C.iterdir():
        if f.is_file() and not f.is_symlink():f.chmod(0o600)
    for f in S.rglob('*'):
        if f.is_file() and not f.is_symlink(): f.chmod(0o600)

def settings():
    d=read(C/'settings.json')
    if d is None:raise Error('尚未安装，请执行 install.sh')
    return d

def clean_node(n):
    if not isinstance(n,dict):raise Error('节点必须为映射')
    n=copy.deepcopy(n);n.pop('name',None)
    allowed={'type','server','port','username','password','cipher','uuid','alterId','udp','tls','sni','servername','network','skip-cert-verify','client-fingerprint','alpn','packet-encoding'}
    if set(n)-allowed:raise Error('节点含未支持字段；禁止外部 dialer、路由、远程文件与复杂传输。请导入简化的 TCP 节点')
    if n.get('type') not in ['http','socks5','ss','vmess','trojan','vless']:raise Error('支持 HTTP、SOCKS5、SS、VMess、Trojan、VLESS 的 TCP 简单节点')
    host=n.get('server','')
    if not isinstance(host,str) or not host or len(host)>253 or re.search(r'[\s/@,#]',host):raise Error('节点地址不合法')
    if host.endswith('.invalid'):raise Error('示例节点不可用于实际部署')
    if isinstance(n.get('port'),bool) or not isinstance(n.get('port'),int) or not 1<=n['port']<=65535:raise Error('节点端口无效')
    if n.get('network','tcp') not in ['tcp','']:raise Error('此工具仅验证 TCP 传输，不接受 ws/grpc/QUIC')
    if 'skip-cert-verify' in n and not isinstance(n['skip-cert-verify'],bool):raise Error('skip-cert-verify 必须为布尔值')
    for k in ['username','password','cipher','uuid','sni','servername','client-fingerprint']:
        if k in n and (not isinstance(n[k],str) or any(ord(c)<32 for c in n[k])):raise Error('节点字符串字段无效')
    if n['type']=='ss' and not all(n.get(k) for k in ['cipher','password']):raise Error('SS 缺少 cipher/password')
    if n['type'] in ['vmess','vless'] and not n.get('uuid'):raise Error('节点缺少 uuid')
    if n['type']=='trojan' and not n.get('password'):raise Error('Trojan 缺少 password')
    n['udp']=False
    return n

def normalize_rule(r):
    r=copy.deepcopy(r)
    if r.get('type') not in ['DOMAIN','DOMAIN-SUFFIX','IP-CIDR','IP-CIDR6']:raise Error('规则类型应为 DOMAIN / DOMAIN-SUFFIX / IP-CIDR / IP-CIDR6')
    if r.get('action') not in ['CHAIN','DIRECT','FALLBACK']:raise Error('动作应为 CHAIN、DIRECT 或 FALLBACK')
    if r['action']=='FALLBACK' and r['type'] not in ['DOMAIN','DOMAIN-SUFFIX']:raise Error('可回退规则只支持明确的非 AI 域名，不支持 IP 网段')
    v=r.get('value','').strip().lower().rstrip('.')
    if r['type'].startswith('IP-'):
        try:net=ipaddress.ip_network(v,strict=False)
        except ValueError:raise Error('IP 网段无效')
        if (net.version==6)!=(r['type']=='IP-CIDR6'):raise Error('IP 规则类型与地址不符')
        v=str(net)
    else:
        try:v=v.encode('idna').decode()
        except UnicodeError:raise Error('域名无效')
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',v) or '..' in v:raise Error('请输入域名，不含协议、通配符、端口或路径')
    r['value']=v;r.setdefault('source','custom');return r

def rules(st=None):
    st=st or settings();ai=read(ROOT/'rules/ai.json',[]);custom=read(C/'custom-rules.json',[])
    packs=ai+[r for r in custom if r['action']=='CHAIN']+read(ROOT/'rules/local.json',[])+[r for r in custom if r['action']=='DIRECT']+[r for r in custom if r['action']=='FALLBACK']+read(ROOT/'rules/direct.json',[])
    if st.get('dev_rules'):packs+=read(ROOT/'rules/dev-optional.json',[])
    return [normalize_rule(r) for r in packs]

def overlaps(a,b):
    if a['type'].startswith('IP-') or b['type'].startswith('IP-'):
        return a['type'].startswith('IP-') and b['type'].startswith('IP-') and ipaddress.ip_network(a['value']).overlaps(ipaddress.ip_network(b['value']))
    av,bv=a['value'],b['value']
    return av==bv or (a['type']=='DOMAIN-SUFFIX' and bv.endswith('.'+av)) or (b['type']=='DOMAIN-SUFFIX' and av.endswith('.'+bv))

def conflicts(rs=None):
    rs=rs or rules();out=[]
    for j,b in enumerate(rs):
        for i,a in enumerate(rs[:j]):
            if a['action']!=b['action'] and overlaps(a,b):out.append({'winner':i+1,'shadowed':j+1,'first':a,'later':b})
    return out

def explain(address):
    host=urllib.parse.urlsplit(address).hostname if '://' in address else address
    host=(host or '').lower().rstrip('.')
    try:ip=ipaddress.ip_address(host.strip('[]'))
    except ValueError:ip=None
    for i,r in enumerate(rules(),1):
        t,v=r['type'],r['value'];hit=False
        if t=='DOMAIN':hit=host==v
        elif t=='DOMAIN-SUFFIX':hit=host==v or host.endswith('.'+v)
        elif ip:hit=ip in ipaddress.ip_network(v)
        if hit:return {'priority':i,**r}
    return {'priority':len(rules())+1,'type':'MATCH','value':'*','action':'CHAIN','source':'default external; DNS IP rules use no-resolve'}

def generate(st=None,nodes=None,port=None,api_port=None,forced=None):
    st=st or settings();nodes=read(C/'nodes.json',{}) if nodes is None else nodes;cred=read(C/'credentials.json')
    ready=bool(st.get('entry') in nodes and st.get('exit') in nodes)
    proxies=[]
    if ready:
        a=clean_node(nodes[st['entry']]);b=clean_node(nodes[st['exit']])
        if b['type'] not in ['http','socks5','ss','vmess']:raise Error('落地 B 仅支持 HTTP、SOCKS5、SS、VMess TCP；UDP/Reality 链路未验证，不接受')
        if st['entry']==st['exit'] or (a['server'],a['port'])==(b['server'],b['port']):raise Error('A 与 B 必须是不同节点')
        a['name']='ENTRY_A';b.update({'name':'EXIT_B','dialer-proxy':'ENTRY_A'});proxies=[a,b]
    route='EXIT_B' if ready else 'REJECT'
    rs=rules(st)
    ai=[normalize_rule(r) for r in read(ROOT/'rules/ai.json',[])]
    if any(r['action']=='FALLBACK' and any(overlaps(a,r) for a in ai) for r in rs):raise Error('AI 强制规则不允许回退直连，请缩小可回退规则范围')
    target={'CHAIN':route,'DIRECT':'DIRECT','FALLBACK':'CHAIN_OR_DIRECT' if ready else 'REJECT'}
    rr=[f"{r['type']},{r['value']},{target[r['action']]}"+(',no-resolve' if r['type'].startswith('IP-') else '') for r in rs]
    rr.append('MATCH,'+route)
    if forced:
        target={'A':'ENTRY_A','B':'EXIT_B','chain':'EXIT_B'}[forced]
        if not ready:raise Error('缺少真实 A/B，无法检测链路')
        if forced=='B':proxies[1].pop('dialer-proxy',None)
        rr=['MATCH,'+target]
    config={'port':port or st['port'],'socks-port':0,'mixed-port':0,'redir-port':0,'tproxy-port':0,'allow-lan':False,'bind-address':'127.0.0.1','authentication':[cred['username']+':'+cred['password']],'skip-auth-prefixes':[],'mode':'rule','log-level':'silent','ipv6':True,'external-controller':f"127.0.0.1:{api_port or st['api_port']}",'secret':cred['api_secret'],'tun':{'enable':False},'dns':{'enable':False},'profile':{'store-selected':False,'store-fake-ip':False},'proxies':proxies,'rules':rr}
    if ready and not forced and any(r['action']=='FALLBACK' for r in rs):
        config['proxy-groups']=[{'name':'CHAIN_OR_DIRECT','type':'fallback','proxies':['EXIT_B','DIRECT'],'url':'https://www.gstatic.com/generate_204','interval':120,'timeout':4000,'lazy':True,'max-failed-times':1,'expected-status':204}]
    return config

def run(args,**kw):return subprocess.run([str(x) for x in args],capture_output=True,timeout=kw.pop('timeout',30),**kw)
def systemctl(*args):return run(['systemctl','--user',*args])
def active():return systemctl('is-active','ai-proxy.service').returncode==0

def api(path='/version',method='GET',data=None,port=None):
    st=settings();cred=read(C/'credentials.json')
    req=urllib.request.Request(f"http://127.0.0.1:{port or st['api_port']}"+path,method=method,headers={'Authorization':'Bearer '+cred['api_secret'],'Content-Type':'application/json'},data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=4) as f:
            b=f.read(2*1024*1024);return json.loads(b) if b else {}
    except Exception:raise Error('控制 API 不可达或拒绝请求；检查 status、端口、核心版本') from None

def validate(config,binary=BIN):
    if not binary.exists():raise Error('mihomo 尚未下载')
    with tempfile.TemporaryDirectory(dir=S) as tmp:
        p=P(tmp)/'candidate.json';save(p,config)
        r=run([binary,'-t','-d',tmp,'-f',p])
        if r.returncode:raise Error('mihomo 配置检查失败（原始输出可能含节点信息，已隐藏）；检查节点协议和规则')

def ready_api(port=None):
    for _ in range(40):
        try:api(port=port);return
        except Error:time.sleep(.1)
    raise Error('核心启动后 API 健康检查失败')

FILES=['settings.json','nodes.json','custom-rules.json','subscriptions.json']
def snapshot():return {n:read(C/n) for n in FILES}
def restore(x):
    for n,v in x.items():save(C/n,v)

def apply(close_connections=True):
    cfg=generate();validate(cfg)
    old=(S/'runtime.json').read_bytes() if (S/'runtime.json').exists() else None
    running=active()
    try:
        save(S/'runtime.json',cfg)
        if running:
            api('/configs?force=true','PUT',{'path':str(S/'runtime.json')});ready_api()
            # Old authenticated connections could retain the previous path: close on explicit reload.
            if close_connections:api('/connections','DELETE')
        if old:write(S/'previous-runtime.json',old)
        save(S/'events.json',{'time':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'event':'validated config applied','chain_ready':len(cfg['proxies'])==2})
    except BaseException:
        if old:
            write(S/'runtime.json',old)
            if running:
                try:api('/configs?force=true','PUT',{'path':str(S/'runtime.json')})
                except Error:systemctl('restart','ai-proxy.service')
        raise

def transaction(change):
    with lock():
        old=snapshot()
        try:
            change();apply()
            save(S/'previous-inputs.json',old)
        except BaseException:
            restore(old);raise

def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def port_free(p):
    try:
        with socket.socket() as s:s.bind(('127.0.0.1',p))
    except OSError:raise Error(f'端口 {p} 已占用或无权绑定；未修改占用者')

def direct_fetch(url,limit=8*1024*1024):
    class HTTPSOnly(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            if urllib.parse.urlsplit(newurl).scheme!='https':raise Error('拒绝 HTTPS 降级重定向')
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    if urllib.parse.urlsplit(url).scheme!='https':raise Error('下载仅支持 HTTPS')
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}),HTTPSOnly()).open(urllib.request.Request(url,headers={'User-Agent':'mihomo/1.19.32'}),timeout=30) as f:
            b=f.read(limit+1)
        if len(b)>limit:raise Error('下载超出大小限制')
        return b
    except Error:raise
    except Exception:raise Error('HTTPS 直连下载失败；URL 与凭证已隐藏') from None

def download_version(version):
    if not re.fullmatch(r'v\d+\.\d+\.\d+',version):raise Error('版本格式必须为 vX.Y.Z，不接受 latest')
    arch={'x86_64':'amd64','aarch64':'arm64','arm64':'arm64'}.get(platform.machine())
    if platform.system()!='Linux' or not arch:raise Error('仅支持 Linux amd64/arm64')
    pins=read(ROOT/'versions.json');pin=pins.get(version,{}).get(arch)
    if pin:asset,digest=pin['asset'],pin['sha256']
    else:
        rel=json.loads(direct_fetch('https://api.github.com/repos/MetaCubeX/mihomo/releases/tags/'+version))
        asset=f'mihomo-linux-{arch}'+('-compatible' if arch=='amd64' else '')+f'-{version}.gz'
        match=next((a for a in rel['assets'] if a['name']==asset),None)
        if not match or not re.fullmatch('sha256:[a-f0-9]{64}',match.get('digest') or ''):raise Error('官方发布未提供 SHA256，不进行未验证安装')
        digest=match['digest'].split(':')[1]
    dest=D/'versions'/version/'mihomo'
    # Always verify the installed uncompressed binary against the stored receipt.
    receipt=read(dest.parent/'receipt.json',{})
    if dest.exists() and receipt.get('sha256')==digest and receipt.get('binary_sha256')==hashlib.sha256(dest.read_bytes()).hexdigest():return dest
    b=direct_fetch(f'https://github.com/MetaCubeX/mihomo/releases/download/{version}/{asset}',64*1024*1024)
    if hashlib.sha256(b).hexdigest()!=digest:raise Error('官方 SHA256 校验失败；当前版本保持不变')
    raw=gzip.decompress(b)
    if len(raw)>160*1024*1024:raise Error('核心大小异常')
    write(dest,raw,0o700)
    if run([dest,'-v']).returncode:raise Error('下载的核心无法执行')
    save(dest.parent/'receipt.json',{'version':version,'asset':asset,'sha256':digest,'binary_sha256':hashlib.sha256(raw).hexdigest(),'source':'MetaCubeX/mihomo GitHub Release'})
    return dest

def switch_binary(target):
    tmp=D/('.binary-'+secrets.token_hex(8));tmp.symlink_to(target);os.replace(tmp,BIN)

def upgrade(version):
    with lock():
        candidate=download_version(version);validate(generate(),candidate)
        old=BIN.resolve() if BIN.exists() else None;running=active()
        if old==candidate.resolve():return '已是指定且校验通过的版本'
        try:
            switch_binary(candidate)
            if running:
                if systemctl('restart','ai-proxy.service').returncode:raise Error('新核心重启失败')
                ready_api()
            if old:save(S/'previous-version.json',{'binary':str(old)})
        except BaseException:
            if old:switch_binary(old)
            if running:systemctl('restart','ai-proxy.service');ready_api()
            raise
    return '核心版本已验证并切换'

@contextlib.contextmanager
def isolated(config):
    # No persistent changes, no signals to the production instance.
    with tempfile.TemporaryDirectory(prefix='test-',dir=S) as tmp:
        cfg=P(tmp)/'config.json';save(cfg,config)
        validate(config)
        proc=subprocess.Popen([str(BIN),'-d',tmp,'-f',str(cfg)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        _ISOLATED[config['port']]={'pid':proc.pid,'config':config}
        try:ready_api(int(config['external-controller'].rsplit(':',1)[1]));yield config['port']
        finally:
            _ISOLATED.pop(config['port'],None)
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()

def socket_observer(port):
    info=_ISOLATED.get(port)
    if info is None:
        r=systemctl('show','ai-proxy.service','--property=MainPID','--value')
        try:pid=int(r.stdout.strip())
        except ValueError:pid=0
        info={'pid':pid,'config':read(S/'runtime.json',{})}
    endpoints={}
    for n in info['config'].get('proxies',[]):
        if n['name'] not in ['ENTRY_A','EXIT_B']:continue
        try:
            addresses={r[4][0] for r in socket.getaddrinfo(n['server'],n['port'],type=socket.SOCK_STREAM)}
            endpoints[n['name']]={(v,n['port']) for v in addresses}
        except OSError:endpoints[n['name']]=set()
    result={'entry_socket_seen':False,'direct_B_socket_seen':False,'proc_observation_available':False}
    def sample():
        try:
            inodes=set()
            for f in (P('/proc')/str(info['pid'])/'fd').iterdir():
                try:target=os.readlink(f)
                except OSError:continue
                if target.startswith('socket:['):inodes.add(target[8:-1])
            result['proc_observation_available']=True
            for file in ['/proc/net/tcp','/proc/net/tcp6']:
                for row in P(file).read_text().splitlines()[1:]:
                    fields=row.split()
                    if fields[9] not in inodes:continue
                    addr,prt=fields[2].split(':')
                    raw=bytes.fromhex(addr)
                    if len(raw)==4:ip=socket.inet_ntop(socket.AF_INET,raw[::-1])
                    else:ip=socket.inet_ntop(socket.AF_INET6,b''.join(raw[i:i+4][::-1] for i in range(0,16,4)))
                    remote=(ip,int(prt,16))
                    if remote in endpoints.get('ENTRY_A',set()):result['entry_socket_seen']=True
                    if remote in endpoints.get('EXIT_B',set()):result['direct_B_socket_seen']=True
        except (OSError,ValueError,IndexError):pass
    return result,sample

def probe(url,port=None,auth='valid',max_bytes=1024,redirects=6,api_port=None,want_ip=False):
    """HTTP CONNECT + TLS, bounded reads, observe each redirect separately; no credential argv."""
    st=settings();cred=read(C/'credentials.json');history=[];observed=[]
    socket_evidence,sample_sockets=socket_observer(port or st['port'])
    if max_bytes<0 or max_bytes>65536:raise Error('请求字节数超出限制')
    for _ in range(redirects+1):
        u=urllib.parse.urlsplit(url)
        if u.scheme!='https' or not u.hostname or u.username or u.password:raise Error('验证仅支持不含认证的 HTTPS URL')
        # Prevent sending user-supplied secrets in diagnostics; only sanitized host/path are returned.
        h={}
        if auth!='none':
            user,pw=(cred['username'],cred['password']) if auth=='valid' else ('wrong','wrong')
            h['Proxy-Authorization']='Basic '+base64.b64encode((user+':'+pw).encode()).decode()
        conn=http.client.HTTPSConnection('127.0.0.1',port or st['port'],timeout=15,context=ssl.create_default_context())
        conn.set_tunnel(u.hostname,u.port or 443,h)
        stop=threading.Event()
        def monitor():
            while not stop.is_set():
                sample_sockets()
                try:
                    for item in (api('/connections',port=api_port).get('connections') or []):
                        m=item.get('metadata',{})
                        if m.get('host')==u.hostname:
                            obs={'host':m.get('host'),'rule':item.get('rule'),'rule_payload':item.get('rulePayload'),'chains':item.get('chains',[])}
                            if obs not in observed:observed.append(obs)
                except Error:pass
                stop.wait(.025)
        thread=threading.Thread(target=monitor,daemon=True);thread.start()
        try:
            conn.request('GET',urllib.parse.urlunsplit(('', '',u.path or '/',u.query,'')),headers={'Host':u.netloc,'Range':f'bytes=0-{max_bytes-1}','User-Agent':'ai-proxy-doctor/1'})
            res=conn.getresponse();body=res.read(max_bytes)
            history.append({'host':u.hostname,'status':res.status,'route':explain(u.hostname)['action']})
            loc=res.getheader('Location')
            if res.status in [301,302,303,307,308] and loc:url=urllib.parse.urljoin(url,loc);continue
            result={'ok':200<=res.status<300,'history':history,'observed':observed,'socket_evidence':socket_evidence}
            if want_ip:
                try:result['exit_ip']=str(ipaddress.ip_address(body.decode().strip()))
                except ValueError:result['ok']=False;result['error']='出口响应不是 IP 地址'
            return result
        except Exception:
            return {'ok':False,'history':history,'observed':observed,'socket_evidence':socket_evidence,'error':'CONNECT/TLS/HTTP 请求失败（详情隐藏）'}
        finally:stop.set();thread.join(timeout=5);conn.close()
    return {'ok':False,'history':history,'error':'重定向超出限制'}

def env_proxy():
    st=settings();c=read(C/'credentials.json')
    url=f"http://{urllib.parse.quote(c['username'],safe='')}:{urllib.parse.quote(c['password'],safe='')}@127.0.0.1:{st['port']}"
    e={k:url for k in PROXY_KEYS};e.update({'NO_PROXY':'localhost,127.0.0.1,::1','no_proxy':'localhost,127.0.0.1,::1'});return e

def redact(text):
    # Logs are disabled at the core; this is a second guard for journal/exception metadata.
    text=re.sub(r'https?://\S+','[URL 隐藏]',text)
    text=re.sub(r'(?i)(password|token|secret|authorization)\s*[:=]\s*\S+',r'\1=[隐藏]',text)
    for fn in ['credentials.json','nodes.json','subscriptions.json']:
        obj=read(C/fn,{})
        def visit(x):
            nonlocal text
            if isinstance(x,dict):
                for k,v in x.items():
                    if k in ['password','username','uuid','server','url','api_secret','cipher'] and isinstance(v,str) and len(v)>3:text=text.replace(v,'[隐藏]')
                    else:visit(v)
            elif isinstance(x,list):
                for v in x:visit(v)
        visit(obj)
    return text


def evidence_signature():
    st=settings();nodes=read(C/'nodes.json',{})
    intent={'entry':st.get('entry'),'exit':st.get('exit'),'nodes':[nodes.get(st.get('entry')),nodes.get(st.get('exit'))],'rules':rules(),'port':st['port']}
    return hashlib.sha256(json.dumps(intent,sort_keys=True).encode()).hexdigest()
