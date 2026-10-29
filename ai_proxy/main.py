from __future__ import annotations
import argparse, contextlib, getpass, io, json, os, pathlib, re, shutil, subprocess, sys, tarfile, time
from . import core as c

JSON_OUTPUT=False
DETAILED_OUTPUT=False
def out(x):
    from .presentation import emit
    emit(x,json_mode=JSON_OUTPUT,details=DETAILED_OUTPUT)
def yes(b):return '通过' if b else '失败'
def safe_name(s):
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}',s):raise c.Error('名称仅允许字母、数字、点、下划线和短横线，最长 80 字符')
    return s

def private_file(path):
    p=c.P(path).expanduser()
    if p.is_symlink() or not p.is_file() or p.stat().st_uid!=os.getuid() or p.stat().st_mode&0o077:raise c.Error('导入文件必须属于当前用户、不是符号链接且权限为 600')
    if p.stat().st_size>8*1024*1024:raise c.Error('输入文件超过 8MB')
    return p.read_bytes()

def parse_file(path):return parse_bytes(private_file(path))

def parse_bytes(data):
    try:
        import yaml
        d=yaml.safe_load(data)
    except ImportError:
        try:d=json.loads(data)
        except Exception:raise c.Error('JSON 解析失败；YAML 导入需要 python3-yaml') from None
    except Exception:raise c.Error('节点 YAML/JSON 解析失败；内容已隐藏') from None
    return d

def node_import(data,prefix=''):
    if not isinstance(data,dict):raise c.Error('应提供包含 proxies、nodes 或单个 node 的映射')
    if 'proxies' in data:
        items={safe_name(prefix+str(i+1)):n for i,n in enumerate(data['proxies'])}
    elif 'nodes' in data:items={safe_name(prefix+k):v for k,v in data['nodes'].items()}
    elif 'type' in data:items={safe_name(prefix or 'node'):data}
    else:raise c.Error('未找到 proxies/nodes/type；不接受规则作为节点')
    result={}
    for k,v in items.items():result[k]=c.clean_node(v)
    if not result:raise c.Error('没有有效节点')
    return result

def configure_node(name):
    safe_name(name)
    old=c.read(c.C/'nodes.json',{}).get(name,{})
    def ask(label,key,default=''):
        val=input(f'{label} [{old.get(key,default)}]: ').strip()
        return val or old.get(key,default)
    typ=ask('协议 http/socks5/ss/vmess/trojan/vless','type','socks5');n={'type':typ,'server':ask('服务器地址','server'),'port':int(ask('端口','port','1080'))}
    if typ in ['http','socks5']:
        user=input('用户名（空=不变；输入 - 清除）: ').strip()
        if user!='-':
            if user or old.get('username'):n['username']=user or old['username']
    if typ in ['http','socks5','ss','trojan']:
        pw=getpass.getpass('密码（隐藏；空=不变；输入 - 清除）: ')
        if pw!='-' and (pw or old.get('password')):n['password']=pw or old['password']
    if typ=='ss':n['cipher']=ask('cipher','cipher','aes-128-gcm')
    if typ in ['vmess','vless']:n['uuid']=getpass.getpass('UUID（隐藏；空=不变）: ') or old.get('uuid','')
    if typ in ['http','socks5','vmess','vless'] and input('启用 TLS? [y/N]: ').lower()=='y':
        n['tls']=True
        sni=input('TLS SNI（可空）: ').strip()
        if sni:n['sni']=sni
    # New manual nodes default to strict; retain an explicit old exception only after showing it.
    if typ=='trojan' or n.get('tls'):
        if input('该代理跳过 TLS 证书验证?（存在中间人风险）[y/N]: ').lower()=='y':n['skip-cert-verify']=True
    save_node(name,n)

def save_node(name,node):
    safe_name(name)
    n=c.clean_node(node)
    def change():
        nodes=c.read(c.C/'nodes.json',{});nodes[name]=n;c.save(c.C/'nodes.json',nodes)
    c.transaction(change);out('节点已保存；若被选中，运行配置已安全更新')

def node_cmd(args):
    action=args[0] if args else 'list';nodes=c.read(c.C/'nodes.json',{})
    if action=='list':
        search=args[1].lower() if len(args)>1 else ''
        st=c.settings();labels={}
        for sub in c.read(c.C/'subscriptions.json',{}).values():labels.update(sub.get('labels',{}))
        out([{'label':c.redact(re.sub(r'[\x00-\x1f\x7f]','',labels.get(k,k))), 'id':k,'protocol':v['type'],'role':','.join(r for r in ['entry','exit'] if st.get(r)==k),'address':'[隐藏]','tls_cert_verified':not v.get('skip-cert-verify',False)} for k,v in nodes.items() if search in (k+' '+v.get('type','')+' '+labels.get(k,'')).lower()]);return
    if action in ['add','edit']:configure_node(args[1] if len(args)>1 else input('节点名称: ').strip());return
    if action=='import':
        p=args[1] if len(args)>1 else input('600 权限的节点文件路径: ').strip();prefix=args[2] if len(args)>2 else ''
        items=node_import(parse_file(p),prefix)
        def change():
            nodes=c.read(c.C/'nodes.json',{});nodes.update(items);c.save(c.C/'nodes.json',nodes)
        c.transaction(change);out({'imported_ids':list(items)});return
    if action=='select':
        role=args[1];name=args[2]
        if role not in ['entry','exit'] or name not in nodes:raise c.Error('格式：node select entry|exit 已存在节点ID')
        def change():
            st=c.settings();st[role]=name;c.save(c.C/'settings.json',st)
        c.transaction(change);out('节点选择已保存；不会自动轮换');return
    if action=='delete':
        name=args[1]
        if name in [c.settings().get('entry'),c.settings().get('exit')]:raise c.Error('不能删除正在使用的节点，请先切换')
        def change():
            n=c.read(c.C/'nodes.json',{});n.pop(name,None);c.save(c.C/'nodes.json',n)
        c.transaction(change);out('已删除');return
    raise c.Error('node list [搜索] | add ID | edit ID | import FILE [前缀] | select entry|exit ID | delete ID')

def subscription_cmd(args):
    action=args[0] if args else 'list';subs=c.read(c.C/'subscriptions.json',{})
    if action=='list':out([{'id':k,'url':'[隐藏]','nodes':len(v.get('ids',[])),'updated':v.get('updated')} for k,v in subs.items()]);return
    name=safe_name(args[1] if len(args)>1 else input('订阅名称: ').strip())
    if action in ['add','edit','import']:
        if action=='add' and name in subs:raise c.Error('订阅已存在，请用 subscription edit NAME 保留缓存与选择')
        if action=='edit' and name not in subs:raise c.Error('订阅不存在')
        if action=='import':
            url=private_file(args[2]).decode().strip()
            if not isinstance(url,str):raise c.Error('订阅 URL 文件应只包含一行 HTTPS URL')
            url=url.strip()
            if '\n' in url:raise c.Error('订阅 URL 文件应只有一行')
        else:url=getpass.getpass('HTTPS 订阅 URL（隐藏输入）: ')
        store_subscription(name,url,action);return
    if name not in subs:raise c.Error('订阅不存在')
    if action=='update':
        raw=c.direct_fetch(subs[name]['url'])
        from .subscription import decode
        d=decode(raw)
        if not isinstance(d,dict) or not isinstance(d.get('proxies'),list):raise c.Error('订阅必须为 mihomo YAML/JSON proxies 列表；不执行第三方转换器')
        # Stable id from original node name; subscription reordering must not switch the chosen entry.
        items={};labels={};import hashlib
        for n in d['proxies']:
            label=n.get('name') if isinstance(n,dict) else None
            if not isinstance(label,str) or not label:raise c.Error('订阅每个节点必须有唯一 name')
            key=name+'-'+hashlib.sha256(label.encode()).hexdigest()[:12]
            if key in items:raise c.Error('订阅节点名称重复')
            items[key]=c.clean_node(n);labels[key]=label
        st=c.settings();nodes=c.read(c.C/'nodes.json',{});selected={st.get('entry'),st.get('exit')}
        for key in subs[name].get('ids',[]):
            if key in selected and (key not in items or nodes.get(key)!=items[key]):raise c.Error('订阅删除或改变了已选节点；为保持出口稳定，拒绝更新。请先切换至其他已确认节点')
        def change():
            ns=c.read(c.C/'nodes.json',{})
            for key in subs[name].get('ids',[]):ns.pop(key,None)
            ns.update(items);c.save(c.C/'nodes.json',ns)
            ss=c.read(c.C/'subscriptions.json',{});ss[name].update({'ids':list(items),'labels':labels,'updated':time.strftime('%Y-%m-%dT%H:%M:%S%z')});c.save(c.C/'subscriptions.json',ss)
        c.transaction(change);out({'updated':name,'ids':list(items),'subscription_insecure_tls_count':d.get('_insecure_tls_count',0),'warning':'按提供的节点设置保留 skip-cert-verify；该跳 TLS 不验证身份，目标 HTTPS 验证不变'});return
    if action=='delete':
        if any(k in [c.settings().get('entry'),c.settings().get('exit')] for k in subs[name].get('ids',[])):raise c.Error('订阅仍有已选节点，先切换')
        def change():
            ss=c.read(c.C/'subscriptions.json',{});ids=ss.pop(name)['ids'];c.save(c.C/'subscriptions.json',ss)
            ns=c.read(c.C/'nodes.json',{})
            for k in ids:ns.pop(k,None)
            c.save(c.C/'nodes.json',ns)
        c.transaction(change);out('订阅及其缓存节点已删除');return
    raise c.Error('subscription list | add NAME（隐藏 URL）| edit NAME | import NAME FILE | update NAME | delete NAME')

def store_subscription(name,url,action='add'):
    safe_name(name)
    if not isinstance(url,str) or not url.startswith('https://') or '\n' in url:raise c.Error('订阅只接受单行 HTTPS URL')
    def change():
        x=c.read(c.C/'subscriptions.json',{})
        if action=='add' and name in x:raise c.Error('订阅已存在，请使用修改订阅')
        if action=='edit' and name not in x:raise c.Error('订阅不存在')
        x.setdefault(name,{'ids':[]});x[name]['url']=url;c.save(c.C/'subscriptions.json',x)
    c.transaction(change);out('订阅已安全保存；选择“更新订阅”即可获取节点。')

def rule_cmd(args):
    action=args[0] if args else 'list'
    if action=='list':
        q=args[1].lower() if len(args)>1 else '';out([{'priority':i,**r} for i,r in enumerate(c.rules(),1) if q in json.dumps(r,ensure_ascii=False).lower()]);return
    if action=='conflicts':out(c.conflicts());return
    if action=='explain':
        result=c.explain(args[1])
        if result['action']=='FALLBACK':
            try:result['current_outbound']=c.api('/proxies/CHAIN_OR_DIRECT').get('now','未知')
            except c.Error:result['current_outbound']='服务不可用或尚未应用；代理入口不可用时不能执行回退'
            result['note']='仅指定非 AI 目标；健康检查切换新连接，不自动重放失败请求。'
        out(result);return
    if action=='dev':
        if args[1] not in ['on','off']:raise c.Error('rule dev on|off')
        def change():st=c.settings();st['dev_rules']=args[1]=='on';c.save(c.C/'settings.json',st)
        c.transaction(change);out('可选开发规则已更新');return
    custom=c.read(c.C/'custom-rules.json',[])
    if action in ['add','edit']:
        offset=2 if action=='edit' else 1
        r=c.normalize_rule({'type':args[offset],'value':args[offset+1],'action':args[offset+2].upper(),'source':'custom'})
        # An edited rule replaces its old value; do not report a conflict against itself.
        edited=int(args[1])-1 if action=='edit' else None
        protected=c.read(c.ROOT/'rules/ai.json',[])+[x for i,x in enumerate(custom) if x['action']=='CHAIN' and i!=edited]
        if r['action'] in ['DIRECT','FALLBACK'] and any(c.overlaps(x,r) for x in protected):raise c.Error('该规则与强制代理范围冲突，不能设为直连或可回退')
        if action=='edit':
            idx=int(args[1])-1
            if idx<0 or idx>=len(custom):raise c.Error('自定义编号不存在')
            custom[idx]=r
        elif r not in custom:custom.append(r)
    elif action=='delete':
        idx=int(args[1])-1
        if idx<0 or idx>=len(custom):raise c.Error('自定义编号不存在')
        custom.pop(idx)
    elif action=='custom':out([{'custom_id':i,**r} for i,r in enumerate(custom,1)]);return
    elif action=='refresh':
        c.apply();out('已从当前安装包重新生成规则；自定义规则保留');return
    else:raise c.Error('rule list [搜索] | custom | add TYPE VALUE CHAIN|DIRECT|FALLBACK | edit 自定义编号 TYPE VALUE ACTION | delete 自定义编号 | explain HOST | conflicts | dev on|off | refresh')
    c.transaction(lambda:c.save(c.C/'custom-rules.json',custom));out('规则已验证并应用')

def install(args):
    p=argparse.ArgumentParser(prog='install.sh');p.add_argument('--check',action='store_true');p.add_argument('--port',type=int,default=17890);p.add_argument('--api-port',type=int,default=19090);p.add_argument('--non-interactive',action='store_true');p.add_argument('--nodes-file');p.add_argument('--entry');p.add_argument('--exit');p.add_argument('--configure-claude',action='store_true');a=p.parse_args(args)
    if platform_check(a):return
    with c.lock():
        if not (c.C/'settings.json').exists():
            for port in [a.port,a.api_port]:
                if not 1024<=port<=65535:raise c.Error('普通用户监听端口须为 1024..65535')
                c.port_free(port)
            if a.port==a.api_port:raise c.Error('入口和 API 端口不能相同')
        c.init(a.port,a.api_port)
        app=c.D/'app'
        if c.ROOT.resolve()!=app.resolve():
            if app.exists():
                backup=c.D/'app.previous'
                if backup.exists():shutil.rmtree(backup)
                shutil.copytree(app,backup,ignore=shutil.ignore_patterns('__pycache__','.git'))
            staging=c.D/'app.new'
            if staging.exists():shutil.rmtree(staging)
            staging.mkdir(mode=0o700)
            for name in ['ai-proxy','ai_proxy','rules','templates','versions.json','docs','README.md','LICENSE','install.sh']:
                src=c.ROOT/name
                if src.is_dir():shutil.copytree(src,staging/name,ignore=shutil.ignore_patterns('__pycache__'))
                elif src.exists():shutil.copy2(src,staging/name)
            if app.exists():
                displaced=c.D/'app.displaced'
                if displaced.exists():shutil.rmtree(displaced)
                os.replace(app,displaced)
                try:os.replace(staging,app)
                except BaseException:os.replace(displaced,app);raise
                shutil.rmtree(displaced)
            else:os.replace(staging,app)
        target=c.download_version(c.read(c.ROOT/'versions.json')['default'])
        if not c.BIN.exists():c.switch_binary(target)
        c.apply()
        unit=(c.ROOT/'templates/ai-proxy.service').read_text()
        # systemd quoting; paths are generated locally, never interpreted by a shell.
        def systemd_arg(path):return '"'+str(path).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
        for key,val in [('BINARY',c.BIN),('STATE',c.S),('CONFIG',c.S/'runtime.json')]:unit=unit.replace('@'+key+'@',systemd_arg(val))
        c.UNIT.parent.mkdir(parents=True,exist_ok=True)
        # Keep the shared systemd user unit directory's existing permissions unchanged.
        fd=os.open(c.UNIT,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:f.write(unit)
        bindir=c.HOME/'.local/bin';bindir.mkdir(parents=True,exist_ok=True)
        link=bindir/'ai-proxy'
        if link.exists() or link.is_symlink():
            if not link.is_symlink() or link.resolve()!=(app/'ai-proxy').resolve():raise c.Error('~/.local/bin/ai-proxy 已存在且不属于本项目；未覆盖')
        else:link.symlink_to(app/'ai-proxy')
        if c.systemctl('daemon-reload').returncode:raise c.Error('systemd 用户总线不可用；文件已安装，未宣称完成常驻。请查看 docs/troubleshooting.md')
        if c.systemctl('enable','--now','ai-proxy.service').returncode:raise c.Error('用户服务启用失败，使用 status 排障')
        c.ready_api()
    if a.nodes_file:node_cmd(['import',a.nodes_file])
    if a.entry:node_cmd(['select','entry',a.entry])
    if a.exit:node_cmd(['select','exit',a.exit])
    if not a.non_interactive and sys.stdin.isatty():
        menu()
    if a.configure_claude:app_cmd(['configure','claude'])
    status();out('退出菜单不会停止服务。Linger 条件请见下方 doctor；命令：~/.local/bin/ai-proxy')
    from .diagnostics import doctor
    doctor(network=False)

def platform_check(a):
    import platform
    if sys.version_info < (3,8):raise c.Error('需要 Python 3.8 或更新版本')
    if platform.system()!='Linux' or platform.machine() not in ['x86_64','aarch64','arm64']:raise c.Error('支持 Linux amd64/arm64')
    if not shutil.which('systemctl'):raise c.Error('本版本可靠常驻需要 systemd --user；替代方案需现有用户 supervisor，见排障文档')
    if a.check:
        out({'system':platform.platform(),'uid':os.getuid(),'python':sys.version.split()[0],'systemd_user':c.systemctl('is-system-running').stdout.decode().strip(),'port':c.read(c.C/'settings.json',{}).get('port',a.port),'core_installed':c.BIN.exists(),'proxy_environment_present':[k for k in c.PROXY_KEYS if os.environ.get(k)]});return True
    return False

def status():
    st=c.settings();cfg=c.generate();live=c.active()
    last=c.read(c.S/'doctor.json',{});counts={}
    for row in last.get('checks',[]):counts[row['result']]=counts.get(row['result'],0)+1
    labels={}
    for sub in c.read(c.C/'subscriptions.json',{}).values():labels.update(sub.get('labels',{}))
    out({'service':'运行' if live else '停止','http_proxy':f"http://127.0.0.1:{st['port']}（需认证；凭证不显示）",'control_api':f"127.0.0.1:{st['api_port']}（独立密钥）",'entry_A':c.redact(labels.get(st.get('entry'),st.get('entry')) or '未设置'),'entry_id':st.get('entry'),'exit_B':st.get('exit'),'chain':'本机 → A → B → 目标' if cfg['proxies'] else '未配置真实 A/B；AI 和其余外部流量 REJECT','entry_tls_identity_verified':not c.read(c.C/'nodes.json',{}).get(st.get('entry'),{}).get('skip-cert-verify',False),'applications_configured':st.get('applications',[]),'applications_verified':c.read(c.S/'application-tests.json',{}),'last_doctor':{'time':last.get('time'),'counts':counts},'credentials':'[隐藏]'})

def service(args):
    action=args[0] if args else 'status'
    if action=='status':status();return
    if action=='logs':
        out(c.read(c.S/'events.json',{}));out('mihomo 原始日志默认关闭，避免域名/节点/认证泄露；以下仅为脱敏服务生命周期日志。')
        r=c.run(['journalctl','--user','-u','ai-proxy.service','-n','40','--no-pager']);out(c.redact(r.stdout.decode(errors='replace')));return
    if action not in ['start','stop','restart']:raise c.Error('service start|stop|restart|status|logs')
    if action in ['start','restart']:c.validate(c.generate())
    if c.systemctl(action,'ai-proxy.service').returncode:raise c.Error('服务操作失败；请运行 doctor')
    if action in ['start','restart']:c.ready_api()
    out('服务已停止；已接入应用包括 DIRECT 目标均可能连接失败；普通未接入程序不受影响。' if action=='stop' else '服务已启动并通过 API 健康检查')

def app_cmd(args):
    action=args[0] if args else 'check';name=args[1] if len(args)>1 else 'all'
    if action=='check':
        from .diagnostics import app_check
        out(app_check());return
    if action=='configure' and name in ['claude','claude-desktop']:
        c.validate(c.generate());c.ready_api()
        p=c.HOME/'.claude/settings.json'
        if p.exists():
            old=p.read_bytes()
            try:d=json.loads(old)
            except Exception:raise c.Error('现有 Claude settings.json 非法；未修改') from None
        else:old=None;d={}
        if not isinstance(d,dict) or not isinstance(d.get('env',{}),dict):raise c.Error('现有 Claude env 不是对象；未修改')
        if old and not (c.S/'backups/claude-settings.original').exists():c.write(c.S/'backups/claude-settings.original',old)
        d.setdefault('env',{}).update(c.env_proxy());c.write(p,json.dumps(d,ensure_ascii=False,indent=2)+'\n')
        def change():
            st=c.settings();st['applications']=sorted(set(st.get('applications',[])+['claude-settings']));c.save(c.C/'settings.json',st)
        c.transaction(change)
        out('已合并服务器 ~/.claude/settings.json（600）。现有 SSH/helper 进程环境可能优先；check 会报告冲突。未验证实际应用。');return
    if action=='configure' and name=='codex':
        if not shutil.which('codex'):raise c.Error('未检测到 codex；先安装后再接入')
        version=c.run(['codex','--version']).stdout.decode().strip()
        # Explicit launcher; never edits auth, model/provider or the currently running app-server.
        target=c.HOME/'.local/bin/codex-ai'
        if target.exists() and 'ai-proxy run' not in target.read_text():raise c.Error('codex-ai 已存在且不属于本项目')
        launcher='#!/bin/sh\nexec "$HOME/.local/bin/ai-proxy" run codex "$@"\n';c.write(target,launcher,0o700)
        def change():st=c.settings();st['applications']=sorted(set(st.get('applications',[])+['codex-ai-launcher']));c.save(c.C/'settings.json',st)
        c.transaction(change);out({'detected':version,'launcher':str(target),'state':'仅新启动的 codex-ai 继承代理；未改变当前 Codex 会话。实际网络/应用层尚待验证'});return
    raise c.Error('app check | configure claude|claude-desktop|codex；真实验证：app-test claude|codex')

def run_command(args):
    if args and args[0]=='--':args=args[1:]
    if not args:raise c.Error('run -- COMMAND [ARGS...]')
    c.ready_api() # fail before spawning when local service unavailable
    if not c.generate()['proxies']:raise c.Error('缺少真实 A/B；拒绝启动目标命令')
    env=os.environ.copy();env.update(c.env_proxy())
    os.execvpe(args[0],args,env)

def backup_cmd(args):
    action=args[0] if args else 'export'
    if action=='export':
        dest=c.P(args[1]).expanduser() if len(args)>1 else c.S/'backups'/('public-'+str(int(time.time()))+'.tar')
        # Node names/hosts and machine paths deliberately excluded; only portable rule intent.
        d={'schema':1,'dev_rules':c.settings().get('dev_rules',False),'custom_rules':c.read(c.C/'custom-rules.json',[])}
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w') as tf:
            raw=json.dumps(d,ensure_ascii=False,indent=2).encode();ti=tarfile.TarInfo('public-config.json');ti.size=len(raw);ti.mode=0o600;tf.addfile(ti,io.BytesIO(raw))
        c.write(dest,buf.getvalue());out({'backup':str(dest),'contains_secrets':False});return
    if action=='import':
        try:
            with tarfile.open(args[1]) as tf:
                ms=tf.getmembers()
                if len(ms)!=1 or ms[0].name!='public-config.json' or not ms[0].isfile() or ms[0].size>1024*1024:raise c.Error('迁移包格式不合法')
                d=json.load(tf.extractfile(ms[0]))
        except c.Error:raise
        except Exception:raise c.Error('读取迁移包失败') from None
        if d.get('schema')!=1:raise c.Error('迁移包版本不支持')
        rs=[c.normalize_rule(x) for x in d['custom_rules']]
        if any(r['action'] in ['DIRECT','FALLBACK'] and any(a['action']=='CHAIN' and c.overlaps(a,r) for a in c.read(c.ROOT/'rules/ai.json')) for r in rs):raise c.Error('迁移规则与 AI 强制规则冲突')
        def change():
            st=c.settings();st['dev_rules']=bool(d.get('dev_rules'));c.save(c.C/'settings.json',st);c.save(c.C/'custom-rules.json',rs)
        c.transaction(change);out('非敏感规则已导入；机器端口、节点与秘密未覆盖');return
    raise c.Error('backup export [FILE.tar] | import FILE.tar')

def rollback(args):
    what=args[0] if args else 'config'
    if what=='config':
        previous=c.read(c.S/'previous-inputs.json')
        if not previous:raise c.Error('没有上一份输入快照')
        c.transaction(lambda:c.restore(previous));out('输入与配置已恢复并重新验证');return
    if what=='version':
        previous=c.read(c.S/'previous-version.json')
        if not previous:raise c.Error('没有上一核心版本')
        p=c.P(previous['binary'])
        if c.D/'versions' not in p.parents:raise c.Error('版本备份路径无效')
        out(c.upgrade(p.parent.name));return
    raise c.Error('rollback config|version')

def ports_cmd(args):
    port,apiport=map(int,args)
    if port==apiport or any(not 1024<=v<=65535 for v in [port,apiport]):raise c.Error('端口须不同且在 1024..65535')
    if c.settings().get('applications'):raise c.Error('已有应用持久配置；更改端口会使已有应用失联。请备份后在停机维护窗口操作，当前拒绝自动修改')
    old=c.settings();running=c.active()
    for key,v in [('port',port),('api_port',apiport)]:
        if v!=old[key]:c.port_free(v)
    # API listener changes require restart; avoid sending a reload to a newly configured API port.
    with c.lock():
        oldcfg=c.read(c.S/'runtime.json')
        try:
            st=dict(old,port=port,api_port=apiport);cfg=c.generate(st);c.validate(cfg)
            c.save(c.C/'settings.json',st);c.save(c.S/'runtime.json',cfg)
            if running:
                if c.systemctl('restart','ai-proxy.service').returncode:raise c.Error('重启失败')
                c.ready_api()
        except BaseException:
            c.save(c.C/'settings.json',old);c.save(c.S/'runtime.json',oldcfg)
            if running:c.systemctl('restart','ai-proxy.service');c.ready_api()
            raise
    out('端口已更新')

def uninstall(args):
    if '--yes' not in args:raise c.Error('卸载使用 uninstall --yes；停止并移除本项目服务/程序，保留秘密、备份与应用代理设置以避免意外直连')
    if c.systemctl('disable','--now','ai-proxy.service').returncode:raise c.Error('未能停止服务；未删除程序')
    c.UNIT.unlink(missing_ok=True);c.systemctl('daemon-reload')
    for p in [c.HOME/'.local/bin/ai-proxy',c.HOME/'.local/bin/codex-ai']:
        if p.is_symlink() and p.resolve()==(c.D/'app/ai-proxy').resolve():p.unlink()
        elif p.name=='codex-ai' and p.exists() and 'ai-proxy run' in p.read_text():p.unlink()
    out('服务与命令入口已卸载。配置/秘密/核心/备份保留；应用设置仍指向停止的代理，避免意外直连。明确删除方法见文档。')

HELP='''ai-proxy：无参数进入方向键中文菜单；所有 URL/密码均通过隐藏输入或 600 本地文件导入。
on | off | toggle | restart | status | service start|stop|restart|status|logs
node list [搜索] | add ID | edit ID | import FILE [PREFIX] | select entry|exit ID | delete ID
subscription list|add NAME|edit NAME|import NAME FILE|update NAME|delete NAME
traffic（实时终端流量面板）
chain | test A|B|chain | exit-ip | negative-test
rule list [搜索] | custom | add TYPE VALUE CHAIN|DIRECT|FALLBACK | edit ID TYPE VALUE ACTION | delete ID
rule explain HOST | conflicts | dev on|off | refresh
probe HTTPS_URL | validate | reload | ports HTTP_PORT API_PORT
app check | configure claude|claude-desktop|codex | app-test claude|codex [--negative]
run -- COMMAND [ARGS...]（只设置子进程环境，不改变父 shell）
doctor [--network] | report [FILE] | backup export [FILE.tar] | backup import FILE.tar
update vX.Y.Z | rollback config|version | uninstall --yes | help
输出：默认中文；--details 查看技术细节；--json 用于脚本。
install.sh --check | --non-interactive | --nodes-file FILE --entry ID --exit ID --configure-claude'''

def dispatch(argv):
    if not argv:menu();return
    cmd,*args=argv
    if cmd in ['help','--help','-h']:out(HELP);return
    if cmd=='install':install(args);return
    c.settings()
    if cmd in ['on','off','restart','toggle']:
        action={'on':'start','off':'stop','restart':'restart'}.get(cmd)
        if cmd=='toggle':action='stop' if c.active() else 'start'
        service([action])
    elif cmd=='traffic':
        from .tui import run
        run(traffic=True)
    elif cmd=='status':status()
    elif cmd=='service':service(args)
    elif cmd=='node':node_cmd(args)
    elif cmd=='subscription':subscription_cmd(args)
    elif cmd=='rule':rule_cmd(args)
    elif cmd=='app':app_cmd(args)
    elif cmd=='run':run_command(args)
    elif cmd=='backup':backup_cmd(args)
    elif cmd=='rollback':rollback(args)
    elif cmd=='ports':ports_cmd(args)
    elif cmd=='uninstall':uninstall(args)
    elif cmd=='update':out(c.upgrade(args[0]))
    elif cmd=='validate':c.validate(c.generate());out({'config':'通过','chain_ready':bool(c.generate()['proxies']),'conflicts':c.conflicts()})
    elif cmd=='reload':
        with c.lock():c.apply()
        out('已校验并安全重载；已有代理连接已关闭，应用需要重连')
    elif cmd=='probe':out(c.probe(args[0]))
    elif cmd=='chain':
        st=c.settings();out({'entry':st.get('entry'),'exit':st.get('exit'),'path':'本机 → ENTRY_A → EXIT_B → 目标','dialer-proxy':'位于 EXIT_B 节点；值 ENTRY_A','ready':bool(c.generate()['proxies'])})
    elif cmd in ['doctor','report','test','exit-ip','negative-test','app-test']:
        from . import diagnostics as d
        if cmd=='doctor':d.doctor('--network' in args)
        elif cmd=='report':
            dest=c.P(args[0]).expanduser() if args else c.S/'report.json';results=d.doctor(False);c.save(dest,{'checks':results,'scope':'仅本账号；无秘密、节点地址或应用登录文件'});out('脱敏报告：'+str(dest))
        elif cmd=='test':out(d.chain_test(args[0] if args else 'chain'))
        elif cmd=='exit-ip':out(d.chain_test('chain',ip=True))
        elif cmd=='negative-test':out(d.negative_test())
        else:out(d.application_test(args[0],negative='--negative' in args))
    else:raise c.Error('未知命令；运行 ai-proxy help')

def menu():
    try:from .tui import run
    except ImportError:raise c.Error('当前 Python 缺少标准库 curses，无法打开方向键界面；请安装含 curses 的系统 Python，CLI 仍可使用。') from None
    run()

def main():
    os.umask(0o077)
    global JSON_OUTPUT,DETAILED_OUTPUT
    argv=sys.argv[1:]
    while argv and argv[0] in ['--json','--details']:
        flag=argv.pop(0)
        if flag=='--json':JSON_OUTPUT=True
        else:DETAILED_OUTPUT=True
    if argv and argv[0]!='run':
        if '--json' in argv:JSON_OUTPUT=True;argv.remove('--json')
        if '--details' in argv:DETAILED_OUTPUT=True;argv.remove('--details')
    try:dispatch(argv)
    except (KeyboardInterrupt,EOFError):print('\n操作已取消；后台服务不受影响。');sys.exit(130)
    except c.Error as e:print('失败：'+str(e),file=sys.stderr);sys.exit(1)
    except (ValueError,IndexError,KeyError):print('失败：参数或本地配置格式不正确；请运行 ai-proxy help。',file=sys.stderr);sys.exit(2)
    except Exception as e:print('失败：'+type(e).__name__+'（原始详情可能含秘密，已隐藏）；请运行 doctor。',file=sys.stderr);sys.exit(1)
