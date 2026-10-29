"""Arrow-key SSH interface. Standard-library curses; actions reuse the CLI handlers."""
from __future__ import annotations
import contextlib
import copy
import curses
import io
import json
import locale
import os
import re
import sys
import unicodedata
from . import core as c
from . import presentation as present


def clean(text):
    return ''.join(ch for ch in str(text) if not unicodedata.category(ch).startswith('C'))


def width(text):
    return sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in text)


def clip(text, columns):
    result=[];used=0;limit=max(0,columns)
    for ch in clean(text):
        size=0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in 'WF' else 1
        if used+size>limit:break
        result.append(ch);used+=size
    return ''.join(result)


def wrapped(text,columns):
    rows=[]
    for line in str(text).splitlines() or ['']:
        part=''
        for ch in clean(line):
            if width(part+ch)>max(2,columns):
                rows.append(part);part='  '
            part+=ch
        rows.append(part)
    return rows

def node_options(role=None):
    st=c.settings();nodes=c.read(c.C/'nodes.json',{});labels={}
    for sub in c.read(c.C/'subscriptions.json',{}).values():labels.update(sub.get('labels',{}))
    result=[]
    for key,node in nodes.items():
        if role=='exit' and node['type'] not in ['http','socks5','ss','vmess']:continue
        marks=[]
        if st.get('entry')==key:marks.append('当前 A')
        if st.get('exit')==key:marks.append('当前 B')
        if node.get('skip-cert-verify'):marks.append('跳过入口证书验证')
        label=clean(c.redact(labels.get(key,key)))+'  ['+node['type']+']'
        if marks:label+='  '+ ' · '.join(marks)
        result.append((label,key))
    return result


class Terminal:
    def __init__(self,screen):
        self.screen=screen
        self.positions={}
        screen.keypad(True)
        curses.noecho()
        curses.cbreak()
        try:curses.set_escdelay(35)
        except AttributeError:pass
        self.colors={}
        if not os.environ.get('NO_COLOR'):
            try:
                if curses.has_colors():
                    curses.start_color()
                    try:curses.use_default_colors();background=-1
                    except curses.error:background=curses.COLOR_BLACK
                    pairs=[('title',curses.COLOR_CYAN,background),('direct',curses.COLOR_GREEN,background),('proxy',curses.COLOR_MAGENTA,background),('warning',curses.COLOR_YELLOW,background),('error',curses.COLOR_RED,background),('selected',curses.COLOR_WHITE,curses.COLOR_BLUE)]
                    for index,(name,fg,bg) in enumerate(pairs,1):
                        curses.init_pair(index,fg,bg);self.colors[name]=curses.color_pair(index)
            except curses.error:self.colors={}
        self.cursor(False)

    def tone(self,text):
        text=str(text).lstrip(' ›')
        if text.startswith('失败') or text.startswith('操作失败'):key='error'
        elif text.startswith('通过') or '始终直连' in text or text=='服务：运行中':key='direct'
        elif '始终代理' in text or '完整 A → B' in text or text.startswith('当前链路'):key='proxy'
        elif any(t in text for t in ['未验证','未设置','跳过','可回退','代理优先','注意','HTTP 状态非成功']):key='warning'
        else:return 0
        return self.colors.get(key,0)

    def cursor(self,visible):
        try:curses.curs_set(1 if visible else 0)
        except curses.error:pass

    def put(self,y,text,style=0,x=2):
        h,w=self.screen.getmaxyx()
        if 0<=y<h and w>x+1:
            try:self.screen.addstr(y,x,clip(text,w-x-1),style or self.tone(text))
            except curses.error:pass

    def frame(self,title,hint):
        self.screen.erase()
        h,w=self.screen.getmaxyx()
        if h<10 or w<42:
            self.put(0,'终端过小，请放大到至少 42 列 × 10 行',x=0)
            self.put(max(1,h-1),'Esc / Ctrl+C 退出，服务继续运行',x=0)
            self.screen.refresh()
            return False
        self.put(0,'AI 代理管理  /  '+title,curses.A_BOLD|self.colors.get('title',0))
        st=c.settings();labels={}
        for sub in c.read(c.C/'subscriptions.json',{}).values():labels.update(sub.get('labels',{}))
        a=labels.get(st.get('entry'),st.get('entry')) or '未配置 A'
        self.put(1,'当前链路：'+clean(c.redact(a))+' → '+str(st.get('exit') or '未配置 B'))
        self.put(2,'─'*(w-4),curses.A_DIM)
        self.put(h-2,hint,curses.A_DIM)
        self.put(h-1,'绿：通过/直连  紫：代理  黄：回退/待核实  红：失败',curses.A_DIM)
        return True

    def key(self):
        try:k=self.screen.get_wch()
        except curses.error:return None
        if k=='\x1b':
            # Accept both normal CSI arrows and application-mode SS3 arrows.
            sequence=''
            self.screen.timeout(35)
            try:
                for _ in range(6):
                    try:part=self.screen.get_wch()
                    except curses.error:break
                    if not isinstance(part,str):break
                    sequence+=part
                    if len(sequence)>1 and (part.isalpha() or part=='~'):break
            finally:self.screen.timeout(-1)
            k={'OP':curses.KEY_F1,'OQ':curses.KEY_F2,'OR':curses.KEY_F3,'[11~':curses.KEY_F1,'[12~':curses.KEY_F2,'[13~':curses.KEY_F3,'[A':curses.KEY_UP,'OA':curses.KEY_UP,'[B':curses.KEY_DOWN,'OB':curses.KEY_DOWN,'[C':curses.KEY_RIGHT,'OC':curses.KEY_RIGHT,'[D':curses.KEY_LEFT,'OD':curses.KEY_LEFT,'[5~':curses.KEY_PPAGE,'[6~':curses.KEY_NPAGE,'[H':curses.KEY_HOME,'OH':curses.KEY_HOME,'[F':curses.KEY_END,'OF':curses.KEY_END,'[3~':curses.KEY_DC}.get(sequence,'\x1b')
        if k=='\x03':raise KeyboardInterrupt
        if k=='\x04':raise EOFError
        return k

    def choose(self,title,options,default=None,hint=None):
        """Return an option value, or None for back. Lists keep their cursor position."""
        if not options:
            self.message(title,'暂无可选项。请先添加节点、订阅或规则。');return None
        index=self.positions.get(title,0) if default is None else default
        index=max(0,min(index,len(options)-1))
        while True:
            sized=self.frame(title,hint or '↑↓ 选择/自动翻页  →/回车确认  ←/Esc返回')
            h,w=self.screen.getmaxyx();page=max(1,h-7)
            if sized:
                start=(index//page)*page
                for n in range(start,min(len(options),start+page)):
                    row_style=0
                    value=options[n][1]
                    if isinstance(value,dict) and value.get('action') in present.ACTIONS:
                        row_style=self.colors.get({'CHAIN':'proxy','DIRECT':'direct','FALLBACK':'warning'}[value['action']],0)
                    if n==index:row_style=curses.A_BOLD|self.colors.get('selected',curses.A_REVERSE)
                    self.put(4+n-start,('› ' if n==index else '  ')+options[n][0],row_style)
                self.put(3,f'{index+1}/{len(options)}',curses.A_DIM)
            self.screen.refresh();k=self.key()
            if k in ['\x1b','q',curses.KEY_LEFT]:return None
            if not sized:continue
            if k in [curses.KEY_UP,'k']:index=(index-1)%len(options)
            elif k in [curses.KEY_DOWN,'j']:index=(index+1)%len(options)
            elif k==curses.KEY_PPAGE:index=max(0,index-page)
            elif k==curses.KEY_NPAGE:index=min(len(options)-1,index+page)
            elif k==curses.KEY_HOME:index=0
            elif k==curses.KEY_END:index=len(options)-1
            elif k in ['\n','\r',curses.KEY_ENTER,curses.KEY_RIGHT]:
                self.positions[title]=index
                return options[index][1]

    def text(self,title,default='',secret=False):
        value=list(str(default));position=len(value)
        try:
            self.cursor(True)
            while True:
                sized=self.frame(title,'输入必要的新内容；←→ 移动  Ctrl+U 清空  Enter 保存  Esc 取消')
                h,w=self.screen.getmaxyx()
                if sized:
                    self.put(4,'隐藏输入，不会写入命令参数或日志。' if secret else '已有内容可直接回车保留；无需输入命令。')
                    start=position
                    while start>0 and width(''.join(value[start-1:position]) if not secret else '*'*(position-start+1))<w-7:start-=1
                    visible='*'*(len(value)-start) if secret else ''.join(value[start:])
                    self.put(6,'> '+visible)
                    try:self.screen.move(6,min(w-2,4+width('*'*(position-start) if secret else ''.join(value[start:position]))))
                    except curses.error:pass
                self.screen.refresh();k=self.key()
                if k=='\x1b':return None
                if not sized:continue
                if k in ['\n','\r',curses.KEY_ENTER]:return ''.join(value)
                if k in [curses.KEY_BACKSPACE,'\x7f','\b']:
                    if position:value.pop(position-1);position-=1
                elif k==curses.KEY_DC:
                    if position<len(value):value.pop(position)
                elif k==curses.KEY_LEFT:position=max(0,position-1)
                elif k==curses.KEY_RIGHT:position=min(len(value),position+1)
                elif k in [curses.KEY_HOME,'\x01']:position=0
                elif k in [curses.KEY_END,'\x05']:position=len(value)
                elif k=='\x15':value=[];position=0
                elif isinstance(k,str) and k.isprintable() and len(value)<8192:value.insert(position,k);position+=1
        finally:self.cursor(False)

    def message(self,title,text,details=None):
        summary=c.redact(str(text));expanded=False;offset=0
        while True:
            hint='↑↓ 滚动  ←/Esc/回车返回'
            if details:hint+='  D 收起详情' if expanded else '  D 查看详情'
            sized=self.frame(title,hint)
            h,w=self.screen.getmaxyx();page=max(1,h-6)
            lines=wrapped(c.redact(str(details)) if expanded else summary,w-5)
            offset=min(offset,max(0,len(lines)-page))
            if sized:
                for i,line in enumerate(lines[offset:offset+page]):self.put(4+i,line)
            self.screen.refresh();k=self.key()
            if k in ['\n','\r','\x1b','q',curses.KEY_LEFT,curses.KEY_ENTER]:return
            if k in ['d','D'] and details:expanded=not expanded;offset=0
            elif k==curses.KEY_DOWN:offset=min(max(0,len(lines)-page),offset+1)
            elif k==curses.KEY_UP:offset=max(0,offset-1)
            elif k==curses.KEY_NPAGE:offset=min(max(0,len(lines)-page),offset+page)
            elif k==curses.KEY_PPAGE:offset=max(0,offset-page)
            elif k==curses.KEY_HOME:offset=0
            elif k==curses.KEY_END:offset=max(0,len(lines)-page)

    def confirm(self,title,detail):
        return self.choose(title,[(detail+'：取消',False),('确认执行',True)],default=0) is True

    def file(self,title):
        current=c.HOME
        while True:
            try:
                entries=sorted(current.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower()))
                options=[('返回，不选择文件',None)]
                if current.parent!=current:options.append(('📁 ..  上级目录',current.parent))
                for path in entries:
                    if path.is_symlink():continue
                    if path.is_dir() or path.is_file():options.append((('📁 ' if path.is_dir() else '   ')+clean(path.name),path))
            except OSError:
                self.message('无法打开目录','无读取权限，未修改任何文件。');current=current.parent;continue
            chosen=self.choose(title+'  '+str(current),options)
            if chosen is None:return None
            if chosen.is_dir():current=chosen;continue
            return str(chosen)

    def perform(self,title,argv=None,action=None):
        from .main import dispatch
        self.frame(title,'正在执行；Ctrl+C 退出界面，已有后台服务仍运行。')
        self.put(4,'处理中…');self.screen.refresh()
        output=io.StringIO()
        try:
            with present.capture() as structured,contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                result=action() if action else dispatch(argv)
                if result is not None:present.emit(result)
            details='\n\n'.join(present.render(value,details=True) for value in structured)
            self.message(title,output.getvalue() or '操作完成。',details=details or None)
            return True
        except (c.Error,ValueError,IndexError) as exc:
            self.message('操作失败',str(exc) if isinstance(exc,c.Error) else '输入格式不正确；没有应用无效配置。')
            return False
        except Exception as exc:
            self.message('操作失败',type(exc).__name__+'：详情可能含秘密，已隐藏；可运行诊断查看状态。')
            return False

    def select_node(self,role):
        options=node_options(role)
        current=c.settings().get(role)
        default=next((i for i,item in enumerate(options) if item[1]==current),0)
        chosen=self.choose('选择入口 A' if role=='entry' else '选择落地 B',options,default=default)
        if chosen is None or chosen==current:return
        self.perform('切换节点',['node','select',role,chosen])

    def node_form(self,name=None):
        from .main import save_node
        nodes=c.read(c.C/'nodes.json',{})
        if name is None:
            i=1
            while 'manual-'+str(i) in nodes:i+=1
            draft={'type':'socks5','server':'','port':1080};name='manual-'+str(i)
        else:draft=copy.deepcopy(nodes[name])
        original=name if name in nodes else None
        while True:
            typ=draft['type']
            if typ=='ss':draft.setdefault('cipher','aes-128-gcm')
            sni_key='servername' if typ=='vmess' else 'sni'
            options=[('名称：'+name,'name'),('协议：'+typ,'type'),('地址：'+('已设置' if draft.get('server') else '未设置'),'server'),('端口：'+str(draft['port']),'port')]
            if typ in ['http','socks5']:options.append(('用户名：'+('已设置（隐藏）' if draft.get('username') else '无'),'username'))
            if typ in ['http','socks5','ss','trojan']:options.append(('密码：'+('已设置（隐藏）' if draft.get('password') else '未设置'),'password'))
            if typ in ['vmess','vless']:options.append(('UUID：'+('已设置（隐藏）' if draft.get('uuid') else '未设置'),'uuid'))
            if typ=='ss':options.append(('加密方式：'+draft.get('cipher','aes-128-gcm'),'cipher'))
            if typ in ['http','socks5','vmess','vless']:options.append(('TLS：'+('开启' if draft.get('tls') else '关闭'),'tls'))
            if typ=='trojan' or draft.get('tls'):
                options.extend([('SNI：'+('已设置' if draft.get(sni_key) else '默认'),sni_key),('验证代理证书：'+('跳过（风险）' if draft.get('skip-cert-verify') else '验证'),'skip-cert-verify')])
            options += [('保存并应用','save'),('取消编辑','cancel')]
            field=self.choose('编辑节点' if original else '添加节点',options)
            if field in [None,'cancel']:return
            if field=='save':
                if original and name!=original:
                    self.message('名称未修改','已有节点名称不可改，请保留原名或新增节点。');continue
                if not original and name in nodes:
                    self.message('名称已存在','请使用其他名称，或返回节点管理选择编辑已有节点。');continue
                if self.perform('保存节点',action=lambda:save_node(name,draft)):return
                continue
            if field=='type':
                protocols=['http','socks5','ss','vmess','trojan','vless']
                selected=self.choose('选择节点协议',[(t,t) for t in protocols],default=protocols.index(typ))
                if selected and selected!=typ:
                    draft={k:v for k,v in draft.items() if k in ['server','port']};draft['type']=selected
            elif field in ['tls','skip-cert-verify']:
                choices=[('验证证书（推荐）',False),('跳过此代理证书验证（存在中间人风险）',True)] if field=='skip-cert-verify' else [('关闭',False),('开启',True)]
                value=self.choose('证书验证' if field=='skip-cert-verify' else 'TLS',choices,default=int(bool(draft.get(field))))
                if value is not None:draft[field]=value
            elif field=='cipher':
                value=self.choose('选择 SS 加密方式',[(v,v) for v in ['aes-128-gcm','aes-256-gcm','chacha20-ietf-poly1305','2022-blake3-aes-128-gcm','2022-blake3-aes-256-gcm']])
                if value:draft['cipher']=value
            else:
                value=self.text({'name':'节点名称','server':'服务器地址','port':'端口','username':'用户名','password':'密码','uuid':'UUID'}.get(field,'TLS SNI'),name if field=='name' else draft.get(field,''),secret=field in ['username','password','uuid'])
                if value is None:continue
                if field=='name':name=value.strip()
                elif field=='port':
                    try:draft[field]=int(value)
                    except ValueError:self.message('端口无效','请输入 1 到 65535 的整数。')
                else:draft[field]=value

    def nodes(self):
        while True:
            choice=self.choose('节点与链路',[
                ('切换入口 A（从现有节点选择）','entry'),('切换落地 B（从现有节点选择）','exit'),
                ('查看全部节点','list'),('添加节点','add'),('编辑现有节点','edit'),('从本地文件导入节点','import'),('删除未使用节点','delete'),('返回上级',None)])
            if choice is None:return
            if choice in ['entry','exit']:self.select_node(choice)
            elif choice=='add':self.node_form()
            elif choice in ['edit','delete']:
                options=node_options()
                if choice=='delete':options=[o for o in options if o[1] not in [c.settings().get('entry'),c.settings().get('exit')]]
                node=self.choose('选择要编辑的节点' if choice=='edit' else '选择要删除的节点',options)
                if node:
                    if choice=='edit':self.node_form(node)
                    elif self.confirm('删除节点','删除所选未使用节点'):self.perform('删除节点',['node','delete',node])
            elif choice=='import':
                path=self.file('选择 600 权限的节点文件')
                if path:self.perform('导入节点',['node','import',path])
            else:self.perform('节点列表',['node','list'])

    def subscriptions(self):
        from .main import store_subscription
        while True:
            choice=self.choose('订阅管理',[('更新订阅','update'),('查看订阅','list'),('添加订阅','add'),('修改订阅 URL','edit'),('从本地文件导入 URL','import'),('删除订阅','delete'),('返回上级',None)])
            if choice is None:return
            if choice=='list':self.perform('订阅列表',['subscription','list']);continue
            if choice in ['add','import']:
                subs=c.read(c.C/'subscriptions.json',{});i=1
                while 'source-'+str(i) in subs:i+=1
                name=self.text('订阅名称（可直接使用默认名称）','source-'+str(i))
                if not name:continue
                if choice=='import':
                    path=self.file('选择只包含订阅 URL 的 600 文件')
                    if path:self.perform('导入订阅',['subscription','import',name,path])
                else:
                    url=self.text('订阅 HTTPS URL（隐藏输入）',secret=True)
                    if url:self.perform('添加订阅',action=lambda:store_subscription(name,url,'add'))
                continue
            subs=c.read(c.C/'subscriptions.json',{})
            name=self.choose('选择订阅',[(clean(n)+'  '+str(len(v.get('ids',[])))+' 个节点',n) for n,v in subs.items()])
            if not name:continue
            if choice=='edit':
                url=self.text('新订阅 HTTPS URL（隐藏；直接回车保留）',subs[name]['url'],secret=True)
                if url:self.perform('修改订阅',action=lambda:store_subscription(name,url,'edit'))
            elif choice!='delete' or self.confirm('删除订阅','删除订阅及其未使用节点'):self.perform('订阅操作',['subscription',choice,name])

    def rule_form(self,index=None,action=None):
        custom=c.read(c.C/'custom-rules.json',[])
        current=copy.deepcopy(custom[index]) if index is not None else {'type':'DOMAIN','value':'','action':action or 'DIRECT'}
        while True:
            field=self.choose('编辑自定义规则' if index is not None else '新增规则',[
                ('匹配类型：'+present.TYPES[current['type']],'type'),('域名 / 网段：'+current['value'],'value'),('出站动作：'+present.ACTIONS[current['action']],'action'),('保存并应用','save'),('取消',None)])
            if field is None:return
            if field=='save':
                args=['rule','edit',str(index+1)] if index is not None else ['rule','add']
                if self.perform('保存规则',args+[current['type'],current['value'],current['action']]):return
                continue
            if field=='type':
                choices=[('精确域名','DOMAIN'),('域名及其子域','DOMAIN-SUFFIX')]
                if current['action']!='FALLBACK':choices += [('IPv4 网段','IP-CIDR'),('IPv6 网段','IP-CIDR6')]
                value=self.choose('匹配类型',choices)
            elif field=='action':value=self.choose('出站动作',[('始终代理：完整 A → B，失败即停止','CHAIN'),('始终直连','DIRECT'),('代理优先：非 AI 目标，链路不可用后直连','FALLBACK')],default=['CHAIN','DIRECT','FALLBACK'].index(current['action']))
            else:value=self.text('域名或 IP 网段',current['value'])
            if field=='action' and value=='FALLBACK' and current['type'] not in ['DOMAIN','DOMAIN-SUFFIX']:
                self.message('请选择域名规则','可回退只支持明确的非 AI 域名；请先把匹配类型改为域名。');continue
            if value is not None:current[field]=value

    def rule_browser(self,action):
        title={'CHAIN':'始终代理 · 失败即停止','DIRECT':'始终直连 · AI 优先','FALLBACK':'代理优先 · 可回退直连'}[action]
        while True:
            rs=[{'priority':i,**r} for i,r in enumerate(c.rules(),1) if r['action']==action]
            if action=='CHAIN':rs.append({'priority':len(c.rules())+1,'type':'MATCH','value':'其余外部目标','action':'CHAIN','source':'默认策略（失败即停止）'})
            options=[(r['value']+'  ·  '+present.TYPES[r['type']],r) for r in rs]
            options += [('＋ 新增此类规则','add'),('返回上级',None)]
            chosen=self.choose(title,options)
            if chosen is None:return
            if chosen=='add':self.rule_form(action=action);continue
            custom=c.read(c.C/'custom-rules.json',[])
            index=next((i for i,r in enumerate(custom) if c.normalize_rule(r)=={k:v for k,v in chosen.items() if k!='priority'}),None)
            while True:
                if action=='FALLBACK':behavior='健康检查认定完整链不可用后，新连接直连；不重放失败请求。'
                elif action=='CHAIN':behavior='A 或 B 任一跳不可用即失败，不回退。'
                else:behavior='直接从服务器出站；命中更高优先级 AI 规则时仍走完整链。'
                detail=present.render(chosen)+'\n失败处理：'+behavior
                if any(x['later']['value']==chosen['value'] for x in c.conflicts()):detail+='\n注意：部分范围有更高优先级例外，请用域名查询确认。'
                if index is None:
                    self.message('规则说明',detail);break
                options=[('查看说明与来源','details'),('编辑这条规则','edit'),('删除这条规则','delete')]
                options.append(('返回列表',None))
                option=self.choose(chosen['value'],options)
                if option is None:break
                if option=='details':self.message('规则说明',detail)
                elif option=='edit':self.rule_form(index);break
                elif self.confirm('删除规则','删除此自定义规则'):self.perform('删除规则',['rule','delete',str(index+1)]);break

    def rules_advanced(self):
        while True:
            choice=self.choose('更多规则操作',[('查看全部规则及优先级','list'),('搜索规则','search'),('查看冲突与例外','conflicts'),('开发下载直连包','dev'),('校验并应用规则','refresh'),('返回上级',None)])
            if choice is None:return
            if choice=='search':
                value=self.text('搜索关键词')
                if value:self.perform('搜索规则',['rule','list',value])
            elif choice=='dev':
                value=self.choose('开发下载直连包',[('开启','on'),('关闭','off')],default=0 if c.settings().get('dev_rules') else 1)
                if value:self.perform('开发下载规则',['rule','dev',value])
            else:self.perform('规则检查',['rule',choice])

    def rules(self):
        while True:
            rs=c.rules();count=lambda action:sum(r['action']==action for r in rs)
            choice=self.choose('分流规则',[
                ('始终代理  ·  '+str(count('CHAIN'))+' 条 + 其余外部  ·  失败即停止','CHAIN'),
                ('始终直连  ·  '+str(count('DIRECT'))+' 条  ·  下载 / 本地地址','DIRECT'),
                ('代理优先  ·  '+str(count('FALLBACK'))+' 条  ·  可回退直连','FALLBACK'),
                ('查询一个域名怎么走','explain'),('更多规则操作','advanced'),('返回上级',None)])
            if choice is None:return
            if choice in ['CHAIN','DIRECT','FALLBACK']:self.rule_browser(choice)
            elif choice=='advanced':self.rules_advanced()
            else:
                value=self.choose('查询域名',[(v,v) for v in ['api.openai.com','claude.ai','clau.de','claudemcpclient.com','github.com','huggingface.co']]+[('输入其他域名','other')])
                if value=='other':value=self.text('要查询的域名')
                if value:self.perform('域名路由',['rule','explain',value])

    def actions(self,title,items):
        while True:
            argv=self.choose(title,[(label,args) for label,args in items]+[('返回上级',None)])
            if argv is None:return
            if argv[:2]==['service','stop'] and not self.confirm('停止代理服务','已接入应用暂时无法联网；保留代理设置'):continue
            if argv[0]=='app-test' and not self.confirm('最小实际 AI 请求','使用目标应用既有登录；可能有少量 API 费用'):continue
            self.perform(title,argv)

    def diagnostics(self):
        while True:
            choice=self.choose('诊断与报告',[('本地状态与安全检查','local'),('低流量网络与分流诊断','network'),('生成脱敏诊断报告','report'),('验证指定目标的实际路由','probe'),('返回上级',None)])
            if choice is None:return
            if choice!='probe':
                self.perform('诊断与报告',{'local':['doctor'],'network':['doctor','--network'],'report':['report']}[choice]);continue
            url=self.choose('选择请求验证目标',[
                ('GitHub raw 小文件','https://raw.githubusercontent.com/MetaCubeX/mihomo/Meta/README.md'),
                ('Hugging Face 模型下载重定向（限量）','https://huggingface.co/bert-base-uncased/resolve/main/model.safetensors'),
                ('OpenAI API 网络路径','https://api.openai.com/v1/models'),
                ('Claude API 网络路径','https://api.anthropic.com/v1/models'),('输入其他 HTTPS URL','other')])
            if url=='other':url=self.text('要验证的 HTTPS URL')
            if url:self.perform('实际请求与路由观测',['probe',url])

    def maintenance(self):
        while True:
            choice=self.choose('维护与迁移',[('校验配置','validate'),('安全重载','reload'),('恢复上一份配置','config'),('恢复上一核心版本','version'),('更新 mihomo 核心','update'),('导出不含秘密的迁移包','export'),('从本地迁移包导入','import'),('卸载用户服务及命令入口','uninstall'),('返回上级',None)])
            if choice is None:return
            if choice in ['validate','reload']:self.perform('配置维护',[choice])
            elif choice in ['config','version']:
                if self.confirm('恢复旧状态','恢复上一份'+('配置' if choice=='config' else '核心版本')):self.perform('恢复旧状态',['rollback',choice])
            elif choice=='export':self.perform('导出无秘密迁移包',['backup','export'])
            elif choice=='import':
                path=self.file('选择无秘密迁移包')
                if path:self.perform('导入迁移包',['backup','import',path])
            elif choice=='update':
                pins=c.read(c.ROOT/'versions.json',{});versions=[v for v in pins if v.startswith('v')]
                version=self.choose('选择核心版本',[(v+'（固定校验信息）',v) for v in versions]+[('输入其他明确版本','other')])
                if version=='other':version=self.text('版本号，例如 v1.19.32')
                if version and self.confirm('更新核心',version):self.perform('更新核心',['update',version])
            elif self.confirm('卸载','停止并移除本项目服务/入口；保留秘密和应用设置'):
                self.perform('卸载',['uninstall','--yes']);return

    def overview(self):
        st=c.settings();options=node_options();names={key:label for label,key in options}
        last=c.read(c.S/'doctor.json',{});counts={}
        for row in last.get('checks',[]):counts[row['result']]=counts.get(row['result'],0)+1
        text='\n'.join(['服务：'+('运行中' if c.active() else '已停止'),f"HTTP 入口：127.0.0.1:{st['port']}（强制认证）",'入口 A：'+names.get(st.get('entry'),'未配置'),'落地 B：'+names.get(st.get('exit'),'未配置'),'已配置应用：'+('、'.join(st.get('applications',[])) or '暂无'),'最近诊断：'+('、'.join(k+' '+str(v)+' 项' for k,v in counts.items()) or '尚无诊断记录'),'','停止服务不会自动改成直连；普通未接入程序沿用原网络。'])
        self.message('状态总览',text)

    def run(self):
        while True:
            choice=self.choose('主菜单',[('状态总览','status'),('切换入口 A','entry'),('切换落地 B','exit'),('节点管理','nodes'),('订阅管理','subscriptions'),('检测链路与出口','chain'),('分流规则','rules'),('实时流量 · 最终目标与通道','traffic'),('应用接入','apps'),('服务管理','service'),('诊断与报告','doctor'),('维护与迁移','maintenance'),('帮助与键盘操作','help'),('退出界面（后台继续运行）',None)])
            if choice is None:return
            if choice=='status':self.overview()
            elif choice=='traffic':
                from .traffic_ui import monitor
                monitor(self)
            elif choice in ['entry','exit']:self.select_node(choice)
            elif choice in ['nodes','subscriptions','rules','maintenance']:getattr(self,choice)()
            elif choice=='chain':self.actions('检测链路与出口',[('查看当前完整链路',['chain']),('单独检测入口 A',['test','A']),('单独检测落地 B',['test','B']),('检测完整 A → B',['test','chain']),('查看完整链路出口 IP',['exit-ip']),('隔离测试任一跳故障无回退',['negative-test'])])
            elif choice=='service':self.actions('服务管理',[('查看服务状态',['service','status']),('开启代理服务',['service','start']),('停止代理服务',['service','stop']),('重启代理服务',['service','restart']),('查看脱敏日志',['service','logs'])])
            elif choice=='apps':self.actions('应用接入',[('检查应用与环境冲突',['app','check']),('配置 Claude Code',['app','configure','claude']),('配置 Claude Desktop SSH',['app','configure','claude-desktop']),('配置 Codex 专用入口',['app','configure','codex']),('Codex 最小实际请求',['app-test','codex']),('Claude 最小实际请求',['app-test','claude']),('Codex 代理不可用对照',['app-test','codex','--negative']),('Claude 代理不可用对照',['app-test','claude','--negative'])])
            elif choice=='doctor':self.diagnostics()
            elif choice=='help':self.message('帮助与键盘操作','↑↓：选择项目\n→ / Enter：进入或确认\n← / Esc：返回或取消\nPgUp / PgDn：长列表与结果翻页\nHome / End：列表首尾\nCtrl+C：退出界面，恢复终端；服务保持原状态\n\n切换已有节点、服务管理、订阅更新、诊断等均无需打字。\n仅新增地址/域名/密码等内容时输入文字；密码显示为星号。\n表单输入支持←→、退格、Delete、Ctrl+U清空，Esc丢弃编辑。\nCLI 仍可用：ai-proxy help')


def run(traffic=False):
    if not sys.stdin.isatty() or not sys.stdout.isatty():raise c.Error('方向键菜单需要交互终端，请直接在 SSH 终端运行 ai-proxy；自动化请使用 ai-proxy help 中的 CLI。')
    try:
        locale.setlocale(locale.LC_ALL,'')
        os.environ.setdefault('ESCDELAY','35')
        def launch(screen):
            ui=Terminal(screen)
            if traffic:
                from .traffic_ui import monitor
                monitor(ui)
            else:ui.run()
        curses.wrapper(launch)
    except curses.error:raise c.Error('终端不支持此界面；请确认 TERM 为 xterm-256color，并直接在 SSH 终端运行。') from None
