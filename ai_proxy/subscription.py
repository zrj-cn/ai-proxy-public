"""Offline URI decoder. No third-party converters, downloads, or executable config."""
import base64, json, urllib.parse
from . import core as c

def b64(s):
    try:return base64.urlsafe_b64decode(s+'='*(-len(s)%4)).decode()
    except Exception:raise c.Error('订阅 base64 解析失败；原内容已隐藏') from None

def decode(data):
    from .main import parse_bytes
    text_input=data.decode().strip() if isinstance(data,bytes) else data.strip()
    if '://' in text_input and not text_input.startswith(('{','proxies:')):
        d=text_input
    elif text_input and all(ch.isalnum() or ch in '+/=\r\n-_' for ch in text_input):
        d=text_input
    else:
        d=parse_bytes(data)
    if isinstance(d,dict) and isinstance(d.get('proxies'),list):return d
    if not isinstance(d,str):raise c.Error('订阅应为 mihomo proxies 或 base64 URI 列表')
    text=d.strip()
    if '://' not in text:text=b64(''.join(text.split()))
    items=[];strict=0
    for i,line in enumerate(text.splitlines(),1):
        if not line.strip():continue
        u=urllib.parse.urlsplit(line.strip());q=urllib.parse.parse_qs(u.query)
        label=urllib.parse.unquote(u.fragment) or ('node-'+str(i))
        if u.scheme not in ['trojan','ss','socks5','http','https','vmess','vless']:raise c.Error('订阅包含未支持 URI 协议；未覆盖旧配置')
        if u.scheme=='vmess':
            try:v=json.loads(b64(line.strip()[8:]))
            except Exception:raise c.Error('VMess URI 格式错误') from None
            if v.get('net','tcp')!='tcp' or v.get('type','none') not in ['none','']:raise c.Error('VMess 仅支持简单 TCP')
            n={'name':v.get('ps') or label,'type':'vmess','server':v['add'],'port':int(v['port']),'uuid':v['id'],'alterId':int(v.get('aid',0)),'cipher':v.get('scy','auto')}
            if v.get('tls')=='tls':n.update({'tls':True,'servername':v.get('sni') or v.get('host') or v['add']})
        else:
            if set(q)-{'allowInsecure','peer','sni','security','type','encryption','fp','remarks'}:raise c.Error('节点 URI 含未支持参数；不忽略复杂传输或插件')
            if q.get('security',['tls' if u.scheme=='trojan' else 'none'])[0] not in ['none','tls']:raise c.Error('仅支持普通 TLS，拒绝 Reality 等传输')
            if q.get('type',['tcp'])[0]!='tcp':raise c.Error('URI 节点仅支持 TCP')
            insecure=q.get('allowInsecure',['0'])[0].lower() in ['1','true']
            strict+=insecure
            if not u.hostname or not u.port:raise c.Error('URI 缺少主机或端口')
            n={'name':label,'type':'http' if u.scheme=='https' else u.scheme,'server':u.hostname,'port':u.port}
            if insecure:n['skip-cert-verify']=True
            if u.scheme=='trojan':n['password']=urllib.parse.unquote(u.username or '')
            elif u.scheme=='vless':n['uuid']=urllib.parse.unquote(u.username or '')
            elif u.scheme=='ss':
                # SIP002 base64(method:password)@host:port; plain percent-encoded userinfo also accepted.
                pair=urllib.parse.unquote(u.username or '')+(':'+urllib.parse.unquote(u.password) if u.password is not None else '')
                if ':' not in pair:pair=b64(pair)
                method,sep,password=pair.partition(':')
                if not sep:raise c.Error('SS URI 缺少 cipher/password')
                n.update(cipher=method,password=password)
            else:
                if u.username is not None:n['username']=urllib.parse.unquote(u.username)
                if u.password is not None:n['password']=urllib.parse.unquote(u.password)
            if u.scheme=='https' or q.get('security',['none'])[0]=='tls':n['tls']=True
            sni=q.get('sni',q.get('peer',['']))[0]
            if sni:n['sni']=sni
            if q.get('fp'):n['client-fingerprint']=q['fp'][0]
        c.clean_node(n);items.append(n)
    if not items:raise c.Error('订阅没有有效节点')
    return {'proxies':items,'_insecure_tls_count':strict}
