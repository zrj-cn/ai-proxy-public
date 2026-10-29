"""Bounded, explicit evidence. Missing prerequisites are 未验证, never fake passes."""
import base64, concurrent.futures, http.client, json, os, pathlib, re, shutil, socket, subprocess, threading, time
from . import core as c

def auth_status(kind):
    st=c.settings();cred=c.read(c.C/'credentials.json');s=socket.create_connection(('127.0.0.1',st['port']),3)
    hdr=''
    if kind!='none':
        pair=cred['username']+':'+cred['password'] if kind=='valid' else 'wrong:wrong'
        hdr='Proxy-Authorization: Basic '+base64.b64encode(pair.encode()).decode()+'\r\n'
    try:
        # CONNECT to a controlled local target needs no Internet access.
        with socket.socket() as target:
            target.bind(('127.0.0.1',0));target.listen(1)
            dest=target.getsockname()[1]
            s.sendall((f'CONNECT 127.0.0.1:{dest} HTTP/1.1\r\nHost: 127.0.0.1:{dest}\r\n'+hdr+'\r\n').encode())
            s.settimeout(3);status=int(s.recv(1024).split(b' ',2)[1])
            return status
    finally:s.close()

def app_check():
    e=c.env_proxy();conflicts=[k for k in e if k in os.environ and os.environ[k]!=e[k]]
    result={'current_process_conflicting_env_keys':conflicts,'note':'只报告变量名，不输出值。父进程/已运行应用不会被子进程更改。'}
    for name in ['claude','codex']:
        exe=shutil.which(name)
        result[name]={'installed':bool(exe)}
        if exe:
            try:result[name]['version']=c.redact(c.run([exe,'--version']).stdout.decode().strip())[:160]
            except Exception:result[name]['version']='未验证'
    p=c.HOME/'.claude/settings.json'
    if p.exists():
        try:
            d=json.loads(p.read_text());env=d.get('env',{})
            result['claude_settings']={'merged_proxy_keys':sorted(k for k in e if env.get(k)==e[k]),'all_match':all(env.get(k)==v for k,v in e.items()),'private_permissions':p.stat().st_mode&0o077==0}
        except Exception:result['claude_settings']={'error':'无法解析'}
    result['running_app_processes']=[]
    for p in pathlib.Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if p.stat().st_uid!=os.getuid():continue
            comm=(p/'comm').read_text().strip()
            if not any(n in comm.lower() for n in ['codex','claude']):continue
            env={}
            for pair in (p/'environ').read_bytes().split(b'\0'):
                k,_,v=pair.partition(b'=')
                if k.decode(errors='ignore') in e:env[k.decode()]=v.decode(errors='replace')
            result['running_app_processes'].append({'pid':int(p.name),'name':comm[:40],'inherited_proxy_matches':all(env.get(k)==v for k,v in e.items()),'conflicting_keys':[k for k in e if k in env and env[k]!=e[k]]})
        except (OSError,ValueError):pass
    result['application_layer']='未验证；应用配置检查不能替代真实请求'
    return result

def chain_test(mode='chain',ip=True):
    if mode not in ['A','B','chain']:raise c.Error('test A|B|chain')
    if not c.generate()['proxies']:return {'result':'未验证','reason':'缺少真实入口 A 或落地 B'}
    p,ap=c.free_port(),c.free_port();cfg=c.generate(port=p,api_port=ap,forced=mode)
    with c.isolated(cfg):
        r=c.probe('https://api.ipify.org' if ip else 'https://api.openai.com/v1/models',port=p,api_port=ap,want_ip=ip)
    if ip and mode=='chain' and r['ok']:
        bp,bap=c.free_port(),c.free_port();bcfg=c.generate(port=bp,api_port=bap,forced='B')
        with c.isolated(bcfg):br=c.probe('https://api.ipify.org',port=bp,api_port=bap,want_ip=True)
        r['B_independent_exit_ip']=br.get('exit_ip');r['same_exit_as_B']=br.get('exit_ip')==r.get('exit_ip') and br.get('ok',False)
    r.update({'mode':mode,'forced_rule':'MATCH,'+('ENTRY_A' if mode=='A' else 'EXIT_B'),'scope':'B 单独检测会显式直接拨号 B；chain 检测 B 通过 A。隔离测试不改变生产实例。','result':'通过' if ip and r['ok'] and (mode!='chain' or r.get('same_exit_as_B') and r.get('socket_evidence',{}).get('entry_socket_seen') and not r.get('socket_evidence',{}).get('direct_B_socket_seen')) else '未验证','application_layer':'未验证（不发送 API 登录凭证；403/401/CONNECT 200 均不证明应用可用）'})
    return r

def negative_test():
    if not c.generate()['proxies']:return {'result':'未验证','reason':'缺少真实 A/B；可运行 tests/integration.py 证明核心链路语义'}
    results=[]
    # Keep an unused socket bound but not listening: guaranteed connection refusal without reusing another service's port.
    for name in ['ENTRY_A','EXIT_B']:
        with socket.socket() as dead:
            dead.bind(('127.0.0.1',0));p,ap=c.free_port(),c.free_port();cfg=c.generate(port=p,api_port=ap,forced='chain')
            n=next(n for n in cfg['proxies'] if n['name']==name);n['server']='127.0.0.1';n['port']=dead.getsockname()[1]
            with c.isolated(cfg):r=c.probe('https://api.ipify.org',port=p,api_port=ap)
        results.append({'disabled':name,'result':'通过' if not r['ok'] and not r['history'] else '失败','evidence':'隔离完整链路目标无法完成 CONNECT/TLS；未调整生产服务。真实 A/B 网络语义还应结合逐跳观测。'})
    return results

def listener_check():
    # Inspect /proc instead of global ss output; report only ports owned by this configuration.
    ports={c.settings()['port'],c.settings()['api_port']};items=[]
    for file in ['/proc/net/tcp','/proc/net/tcp6']:
        try:lines=pathlib.Path(file).read_text().splitlines()[1:]
        except OSError:continue
        for ln in lines:
            f=ln.split()
            if f[3]!='0A':continue
            addr,prt=f[1].split(':');port=int(prt,16)
            if port in ports:items.append({'port':port,'family':'IPv6' if file.endswith('6') else 'IPv4','loopback':addr=='0100007F'})
    return items

def doctor(network=False):
    results=[]
    def add(name,state,detail=''):results.append({'check':name,'result':state,'detail':detail})
    try:c.validate(c.generate());add('配置合法','通过')
    except c.Error as e:add('配置合法','失败',str(e))
    live=c.active();add('systemd 用户服务','通过' if live else '失败')
    try:
        ls=listener_check();ok=len(ls)==2 and all(v['loopback'] for v in ls)
        add('仅预期 IPv4 回环监听、无 IPv6 额外入口','通过' if ok else '失败',ls)
    except Exception:add('监听范围','未验证')
    for kind,expected in [('none',407),('wrong',407),('valid',200)]:
        try:code=auth_status(kind);add({'none':'无凭证被拒绝','wrong':'错误凭证被拒绝','valid':'正确凭证可用'}[kind],'通过' if (code==expected or kind=='wrong' and code==403) else '失败',{'http_status':code})
        except Exception:add({'none':'无凭证被拒绝','wrong':'错误凭证被拒绝','valid':'正确凭证可用'}[kind],'未验证','服务不可用或测试被环境限制')
    try:c.api();add('API 独立密钥访问','通过')
    except c.Error:add('API 独立密钥访问','失败')
    try:
        conn=http.client.HTTPConnection('127.0.0.1',c.settings()['api_port'],timeout=3);conn.request('GET','/version');res=conn.getresponse();code=res.status;conn.close()
        add('API 拒绝无密钥','通过' if code==401 else '失败')
    except Exception:add('API 拒绝无密钥','未验证')
    files=[c.C/'credentials.json',c.C/'nodes.json',c.C/'subscriptions.json',c.S/'runtime.json']
    perms=all(p.exists() and p.stat().st_mode&0o077==0 for p in files) and all(p.stat().st_mode&0o077==0 for p in [c.C,c.D,c.S])
    add('秘密目录 700、秘密文件 600','通过' if perms else '失败')
    add('真实两跳已配置','通过' if c.generate()['proxies'] else '未验证','配置存在不代表真实节点已可达')
    r=c.run(['loginctl','show-user',str(os.getuid()),'-p','Linger']);linger=r.stdout.strip()==b'Linger=yes'
    enabled=c.systemctl('is-enabled','ai-proxy.service').returncode==0
    add('退出登录/重启恢复条件','通过' if linger and enabled else '未验证',{'Linger':linger,'unit_enabled':enabled,'required_if_no_linger':'管理员执行 loginctl enable-linger '+c.HOME.name})
    add('实际断开 SSH 和机器重启后恢复','未验证','本轮不主动重启共享服务器；当前检查不代替真实重启测试')
    ac=app_check();add('目标应用接入与环境冲突','未验证',ac)
    if network:
        urls=[
            ('GitHub raw','https://raw.githubusercontent.com/MetaCubeX/mihomo/Meta/README.md'),
            ('GitHub Release','https://github.com/MetaCubeX/mihomo/releases/download/v1.19.32/mihomo-linux-amd64-compatible-v1.19.32.gz'),
            ('HF model/CDN redirect','https://huggingface.co/bert-base-uncased/resolve/main/model.safetensors'),
            ('HF second model/CDN redirect','https://huggingface.co/sshleifer/tiny-gpt2/resolve/main/pytorch_model.bin')]
        for name,url in urls:
            rr=c.probe(url)
            observed=rr.get('observed',[])
            direct=bool(observed) and all('DIRECT' in x.get('chains',[]) for x in observed)
            # Every requested redirect host must have observable DIRECT evidence.
            hosts={h['host'] for h in rr['history']};seen={x['host'] for x in observed if 'DIRECT' in x.get('chains',[])}
            state='通过' if rr['ok'] and hosts<=seen and direct else '未验证'
            if any(x.get('chains') and 'DIRECT' not in x['chains'] for x in observed):state='失败'
            add(name+' 下载和逐跳 DIRECT',state,rr)
        for name,url in [('OpenAI','https://api.openai.com/v1/models'),('Claude','https://api.anthropic.com/v1/models')]:
            rr=c.probe(url);obs=rr.get('observed',[]);sock=rr.get('socket_evidence',{})
            chain=any('EXIT_B' in x.get('chains',[]) for x in obs) and sock.get('entry_socket_seen') and not sock.get('direct_B_socket_seen')
            add(name+' 代表性网络路径','通过' if chain else '未验证',rr)
        exit_result=chain_test('chain',True);add('出口 B 强制链路查询',exit_result.get('result','未验证'),exit_result)
        negatives=negative_test();negative_state='通过' if isinstance(negatives,list) and all(x['result']=='通过' for x in negatives) else '未验证'
        add('A/B 故障无回退测试',negative_state,negatives)
    else:
        for name in ['下载重定向实际 DIRECT','OpenAI/Claude 实际两跳路径','出口 B','真实 A/B 故障无回退']:add(name,'未验证','本轮未执行网络实测；可在菜单选择网络诊断，或运行 doctor --network。')
    for name in ['真实最小 AI 请求','目标应用代理不可用负向验证','重复安装/失败重载/失败升级恢复']:
        evidence=c.read(c.S/'application-tests.json',{}) if '应用' in name or 'AI' in name else c.read(c.S/'acceptance.json',{})
        if name=='真实最小 AI 请求':state='通过' if any(v.get('result')=='通过' and v.get('signature')==c.evidence_signature() and not v.get('negative') for v in evidence.values() if isinstance(v,dict)) else '未验证'
        elif name=='目标应用代理不可用负向验证':state='通过' if any(v.get('result')=='通过' and v.get('signature')==c.evidence_signature() and v.get('negative') for v in evidence.values() if isinstance(v,dict)) else '未验证'
        else:state='通过' if evidence and all(v=='通过' for v in evidence.values()) else '未验证'
        if state=='未验证' and evidence:evidence={'reason':'节点或规则已变化，或该项尚未实测；不能沿用旧的通过结论。','previous_results':evidence}
        add(name,state,evidence or '需独立验收，不能从静态配置推断')
    c.save(c.S/'doctor.json',{'time':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'checks':results})
    from .main import out
    out(results);return results

def application_test(name,negative=False):
    if negative:return app_negative_test(name)
    if name not in ['codex','claude']:raise c.Error('app-test codex|claude [--negative]')
    exe=shutil.which(name)
    if not exe:return {'result':'未验证','reason':'目标应用未安装'}
    if not c.generate()['proxies']:return {'result':'未验证','reason':'缺少真实 A/B，不读取或复制应用登录文件'}
    # Client performs a minimal real request using its own existing login; output stays in memory.
    token='AI_PROXY_OK_'+c.secrets.token_hex(4)
    args=[exe,'exec','--skip-git-repo-check','--json','只回复 '+token] if name=='codex' else [exe,'-p','只回复 '+token,'--max-turns','1']
    p,ap=c.free_port(),c.free_port();cfg=c.generate(port=p,api_port=ap)
    env=os.environ.copy();env.update(c.env_proxy())
    # Replace only local port; credentials remain in environment, never argv.
    for k in c.PROXY_KEYS:env[k]=env[k].rsplit(':',1)[0]+':'+str(p)
    observed=[];timed_out=False
    with c.isolated(cfg):
        socket_evidence,sample_sockets=c.socket_observer(p)
        with c.tempfile.TemporaryDirectory(dir=c.S) as wd:
            proc=subprocess.Popen(args,env=env,cwd=wd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(proc.communicate)
                end=time.monotonic()+75
                while not future.done() and time.monotonic()<end:
                    sample_sockets()
                    try:
                        for con in (c.api('/connections',port=ap).get('connections') or []):
                            v={'host':con.get('metadata',{}).get('host'),'chains':con.get('chains',[])}
                            if v not in observed:observed.append(v)
                    except c.Error:pass
                    time.sleep(.04)
                if not future.done():proc.kill();timed_out=True
                stdout,stderr=future.result(timeout=10)
    # Do not print model content, raw stderr, authentication data or conversation logs.
    reply=False
    if name=='codex':
        for line in stdout.decode(errors='replace').splitlines():
            try:
                event=json.loads(line);item=event.get('item',{})
                if item.get('type')=='agent_message' and token in item.get('text',''):reply=True
            except Exception:pass
    else:reply=token in stdout.decode(errors='replace')
    chain=any('EXIT_B' in v['chains'] for v in observed) and socket_evidence.get('entry_socket_seen') and not socket_evidence.get('direct_B_socket_seen')
    result={'signature':c.evidence_signature(),'application':name,'negative':negative,'exit_code':proc.returncode,'timed_out':timed_out,'expected_reply_received':reply,'observed':observed,'socket_evidence':socket_evidence,'result':'通过' if not negative and proc.returncode==0 and reply and chain else '未验证'}
    tests=c.read(c.S/'application-tests.json',{});tests[name+('-negative' if negative else '')]=result;c.save(c.S/'application-tests.json',tests)
    return result

def app_negative_test(name):
    """A controlled authenticated but unavailable HTTP proxy; never stop the live service."""
    import socketserver, ipaddress
    if name not in ['codex','claude']:raise c.Error('app-test codex|claude --negative')
    exe=shutil.which(name)
    if not exe:return {'result':'未验证','reason':'目标应用未安装'}
    previous=c.read(c.S/'application-tests.json',{}).get(name,{})
    if previous.get('result')!='通过' or previous.get('signature')!=c.evidence_signature():return {'result':'未验证','reason':'先通过同一应用的最小真实请求，才能作因果对照'}
    attempts=[];cred=c.read(c.C/'credentials.json')
    expected='Basic '+base64.b64encode((cred['username']+':'+cred['password']).encode()).decode()
    class Reject(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(3)
            try:
                line=self.rfile.readline(4096).decode(errors='replace');headers={}
                for _ in range(40):
                    row=self.rfile.readline(8192)
                    if row in [b'',b'\r\n']:break
                    k,_,v=row.decode(errors='replace').partition(':');headers[k.lower()]=v.strip()
                valid=headers.get('proxy-authorization')==expected
                # Discard all original headers; only a boolean and verb are retained.
                if valid:attempts.append({'authenticated':True,'method':'CONNECT' if line.startswith('CONNECT ') else 'HTTP'})
                response=b'HTTP/1.1 502 Test proxy unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n' if valid else b'HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
                self.wfile.write(response)
            except (OSError,ValueError):pass
    class Server(socketserver.ThreadingTCPServer):daemon_threads=True
    token='AI_PROXY_NEG_'+c.secrets.token_hex(4)
    args=[exe,'exec','--skip-git-repo-check','--json','只回复 '+token] if name=='codex' else [exe,'-p','只回复 '+token,'--max-turns','1']
    direct_seen=False;proc_observed=False;timed_out=False
    def process_sockets(pid):
        nonlocal direct_seen,proc_observed
        try:
            pids={pid};todo=[pid]
            while todo:
                parent=todo.pop()
                try:children=(pathlib.Path('/proc')/str(parent)/'task'/str(parent)/'children').read_text().split()
                except OSError:continue
                for child in children:
                    if int(child) not in pids:pids.add(int(child));todo.append(int(child))
            inodes=set()
            for child in pids:
                try:files=list((pathlib.Path('/proc')/str(child)/'fd').iterdir())
                except OSError:continue
                proc_observed=True
                for f in files:
                    try:v=os.readlink(f)
                    except OSError:continue
                    if v.startswith('socket:['):inodes.add(v[8:-1])
            for fn in ['/proc/net/tcp','/proc/net/tcp6']:
                for row in pathlib.Path(fn).read_text().splitlines()[1:]:
                    f=row.split()
                    if f[9] not in inodes:continue
                    addr,port=f[2].split(':')
                    if int(port,16)==0:continue
                    raw=bytes.fromhex(addr)
                    ip=socket.inet_ntop(socket.AF_INET,raw[::-1]) if len(raw)==4 else socket.inet_ntop(socket.AF_INET6,b''.join(raw[i:i+4][::-1] for i in range(0,16,4)))
                    if not ipaddress.ip_address(ip).is_loopback:direct_seen=True
        except (OSError,ValueError,IndexError):pass
    with Server(('127.0.0.1',0),Reject) as srv:
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        env=os.environ.copy();env.update(c.env_proxy())
        for key in c.PROXY_KEYS:env[key]=env[key].rsplit(':',1)[0]+':'+str(srv.server_address[1])
        with c.tempfile.TemporaryDirectory(dir=c.S) as wd:
            proc=subprocess.Popen(args,env=env,cwd=wd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(proc.communicate);end=time.monotonic()+60
                while not future.done() and time.monotonic()<end:process_sockets(proc.pid);time.sleep(.02)
                if not future.done():proc.kill();timed_out=True
                stdout,stderr=future.result(timeout=10)
        srv.shutdown();thread.join(timeout=5)
    replied=token.encode() in stdout
    # An echoed input event is not a model reply. Codex only checks completed agent_message items.
    if name=='codex':
        replied=False
        for line in stdout.decode(errors='replace').splitlines():
            try:
                item=json.loads(line).get('item',{})
                if item.get('type')=='agent_message' and token in item.get('text',''):replied=True
            except Exception:pass
    state='通过' if attempts and proc.returncode!=0 and not timed_out and not replied and proc_observed and not direct_seen else '未验证'
    if replied or direct_seen:state='失败'
    result={'signature':c.evidence_signature(),'application':name,'negative':True,'result':state,'exit_code':proc.returncode,'timed_out':timed_out,'authenticated_proxy_attempts':len(attempts),'expected_reply_received':replied,'external_tcp_socket_observed':direct_seen,'process_tree_observed':proc_observed,'scope':'本次最小请求的对照测试；20ms 采样，不是网络层全进程防绕过控制。生产服务未停止。'}
    tests=c.read(c.S/'application-tests.json',{});tests[name+'-negative']=result;c.save(c.S/'application-tests.json',tests)
    return result
