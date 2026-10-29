"""Live curses dashboard. Keyboard actions never mutate routes or terminate connections."""
from __future__ import annotations
import copy
import curses
import time
from . import core as c
from .traffic import CHANNELS,FILTERS,Sampler,TrafficModel,human,spark
from .tui import clip,width,wrapped


def pad(text,size):return clip(text,size)+' '*max(0,size-width(clip(text,size)))

def details(row):
    return '\n'.join(['目标：'+row['target'],'实际通道：'+CHANNELS[row['channel']],'连接：'+str(row['active'])+' 个活跃 · 本页观察到 '+str(row['seen'])+' 个连接',
        '本页观测上传：'+human(row['up'])+'    下载：'+human(row['down']),
        '协议：'+(' / '.join(sorted(row['networks'])) or '待识别'),'命中规则类型：'+(' / '.join(sorted(row['rules'])) or '待识别'),
        '', '最终目标域名 / IP（最多 100 项）：',*('  '+host for host in sorted(row['hosts'])),'',
        '实际通道来自核心连接记录；完整代理表示出站为 B（按配置经 A）。',
        '有连接/有流量不代表 HTTP 成功、登录成功或 AI 已回复。',
        '已结束仅表示连接不再出现，不能据此区分正常结束与失败。'])


def paint(ui,model,rows,index,filter_index,paused,sort,active_only,query,now,detail=None,detail_offset=0,view='overview'):
    h,w=ui.screen.getmaxyx()
    if h>=24 and w>=100:
        from .dashboard import render
        return render(ui,model,rows,index,filter_index,paused,sort,active_only,query,now,detail,detail_offset,view,details(detail) if detail else '')
    ui.frame('实时流量  ·  最终目标 → 实际通道','↑↓ 选择  ←→ 通道  回车详情  空格暂停  Esc 返回')
    h,w=ui.screen.getmaxyx()
    if h<16 or w<60:
        ui.screen.erase();ui.put(0,'实时流量需要至少 60 列 × 16 行',x=0);ui.put(2,'Esc 返回；Ctrl+C 退出，后台服务继续。',x=0)
        ui.screen.refresh();return 1
    from .dashboard import Theme
    if not hasattr(ui,'dashboard_theme'):ui.dashboard_theme=Theme()
    color=lambda name:ui.dashboard_theme({'proxy':'mint','direct':'gold','warning':'pink'}.get(name,name))
    age=max(0,int(now-model.last_time)) if model.last_time is not None else None
    state='暂停画面 · 后台仍采样' if paused else (model.error+' · 下方为旧数据' if model.error else '') or ('等待首次采样…' if age is None else '数据读取正常 · 不代表链路健康')
    ui.put(3,state+(f'  | 上次采样 {age}s 前' if age is not None and (age>=3 or model.error) else ''),color('warning') if paused or model.error or age is None else color('title'))
    top='↑ '+human(model.rate[0],True)+'   ↓ '+human(model.rate[1],True)
    if model.core_totals:top+='   核心累计 ↑ '+human(model.core_totals[0])+' ↓ '+human(model.core_totals[1])
    ui.put(4,top,curses.A_BOLD)
    chain=model.route_summary('CHAIN');direct=model.route_summary('DIRECT');fallback=model.route_summary('FALLBACK_DIRECT')
    rate=lambda value:human(None if model.error else value,True)
    ui.put(5,'A → B 业务  ↑ '+rate(chain['up_rate'])+' ↓ '+rate(chain['down_rate'])+'  | 本页 ↑ '+human(chain['up'])+' ↓ '+human(chain['down']),color('proxy'))
    ui.put(6,'直连业务   ↑ '+rate(direct['up_rate'])+' ↓ '+rate(direct['down_rate'])+'  | 回退直连 ↓ '+rate(fallback['down_rate']),color('direct'))
    full=h>=24 and w>=100
    if full:
        ui.put(7,'入口 A 与落地 B 承载同一份链路业务量；不重复相加，不含封装开销。',curses.A_DIM)
        ui.put(8,'下载 '+spark([v[1] for v in model.history],24)+'   上传 '+spark([v[0] for v in model.history],24),color('title'))
    tabs_y=9 if full else 7
    tabs='  '.join(('['+label+']' if i==filter_index else label) for i,(label,_) in enumerate(FILTERS))
    ui.put(tabs_y,tabs,color('title')|curses.A_BOLD)
    mode='实时连接' if active_only else '活跃 + 近期结束30s'
    ui.put(tabs_y+1,mode+' · 排序：'+{'speed':'速率','total':'本页流量','target':'目标'}[sort]+(' · 搜索：'+query if query else '')+(' · '+model.notice if model.notice else ''),curses.A_DIM)
    header_y=tabs_y+2;start=header_y+1;page=max(1,h-start-3)
    if detail is not None:
        ui.put(header_y,'连接详情  ·  ↑↓滚动  回车/Esc 返回列表',color('title')|curses.A_BOLD)
        lines=wrapped(details(detail),w-5);detail_offset=min(detail_offset,max(0,len(lines)-page))
        for i,line in enumerate(lines[detail_offset:detail_offset+page]):ui.put(start+i,line)
        ui.put(h-3,'仅展示目标与路由元数据；不读取请求内容、Cookie 或账号凭证。',curses.A_DIM)
    else:
        wide=w>=110
        name_size=max(12,min(32,w-(80 if wide else 39)))
        header='  '+pad('最终目标',name_size)+' '+pad('实际通道',12)
        if wide:header+=' '+pad('连接',5)+' '+pad('↓ 下载/s',12)+' '+pad('↑ 上传/s',12)+' '+pad('本页合计',12)+' 状态'
        else:header+=' ↓ 下载/s'
        ui.put(header_y,header,curses.A_BOLD)
        if not rows:ui.put(start,'暂无符合条件的连接。等待应用请求，或切回“全部”。',color('warning'))
        begin=(index//page)*page
        for i,row in enumerate(rows[begin:begin+page],begin):
            route=row['channel'];tone={'CHAIN':'proxy','A':'proxy','DIRECT':'direct','FALLBACK_DIRECT':'warning','REJECT':'error','UNKNOWN':'warning'}[route]
            target=row['target']+(f" · {len(row['hosts'])} 域名" if len(row['hosts'])>1 else '')
            line=('› ' if i==index else '  ')+pad(target,name_size)+' '+pad(CHANNELS[route],12)
            if wide:
                state=('上次活跃' if row['active'] else '上次结束') if model.error else '活跃' if row['active'] else '近期结束'
                line+=' '+pad(str(row['active']),5)+' '+pad(rate(row['down_rate']),12)+' '+pad(rate(row['up_rate']),12)+' '+pad(human(row['up']+row['down']),12)+' '+state
            else:line+=' '+rate(row['down_rate'])
            style=color(tone)
            if i==index:style=curses.A_BOLD|color('selected') or curses.A_REVERSE
            ui.put(start+i-begin,line,style)
        suffix=f'  {index+1 if rows else 0}/{len(rows)} 项'
        if model.evicted:suffix+=' · 目标较多，部分已省略'
        ui.put(h-3,'仅本工具承载流量；短连接/失败请求可能漏采。'+suffix,curses.A_DIM)
    ui.put(h-2,'↑↓选择  ←→通道  Enter详情  空格暂停  /搜索  F活跃  S排序  ?帮助',curses.A_DIM)
    ui.put(h-1,'Esc返回 · 薄荷绿代理 金色直连 粉色回退；本页字节为采样量。',curses.A_DIM)
    ui.screen.refresh();return page


def help_text():
    return '\n'.join(['↑↓：选择最终目标；列表自动翻页，无需 PgUp/PgDn。','←→ / 1–5：切换全部、完整代理、直连、回退直连、其他。','Tab / F1–F3：切换总览、目标、趋势；无需功能键也能操作。','Enter / D：查看最终域名、通道、流量与命中规则；不显示中转节点地址。','空格：暂停/继续画面；暂停时后台继续采样，网络不受影响。','F：只看活跃连接 / 同时显示最近30秒结束的连接。','S：按速率、本页流量、目标名称轮换排序。','/：搜索目标或域名；清空搜索框回车恢复全部。','Esc / Q：返回；Ctrl+C退出界面，恢复终端，服务继续。','',
        '顶部速率与核心累计来自全部连接计数；含已结束的短连接。','列表与 A/B 汇总来自每秒采样；可能遗漏极短连接或关闭前的最后字节。','入口 A 与落地 B 的完整链路业务量相同，不重复累计，不是网卡或计费统计。','通道取实际连接的出站结果；完整代理按当前配置经 A 到 B。','失败请求可能尚未进入连接列表；无连接不代表网络正常或没有请求。','访问同一服务但走不同通道时分行显示，便于发现异常直连。','仅观察本工具承载的连接；未接入代理的程序不会出现在这里。','数据仅保留在内存，退出即清除；不保存访问历史，不读取请求内容。','服务停止或 API 不可达时保留旧数据并标明过期，自动尝试重连。','面板不会更改节点、规则、服务状态，也不会主动探测目标网站。'])


def monitor(ui,sampler=None,model=None):
    if model is None:
        nodes=c.read(c.C/'nodes.json',{});model=TrafficModel([n.get('server') for n in nodes.values()])
    sampler=sampler or Sampler();sampler.start()
    index=0;selected=None;filter_index=0;sort='speed';active_only=False;query='';paused=False;frozen=None;detail_key=None;detail_offset=0;view='overview';stamp=None;page=1
    try:
        while True:
            event=sampler.latest()
            if event:
                when,snapshot,error=event
                if error:model.fail(error)
                else:model.update(snapshot,when)
            shown=frozen if paused else model
            rows=shown.view(filter_index,sort,active_only,query)
            if selected is not None:index=next((i for i,row in enumerate(rows) if row['key']==selected),min(index,max(0,len(rows)-1)))
            index=max(0,min(index,len(rows)-1))
            selected=rows[index]['key'] if rows else None
            detail=shown.rows.get(detail_key) if detail_key is not None else None
            if detail_key is not None and detail is None:detail_key=None
            now=time.monotonic()
            changed=(shown.last_time,shown.error,index,filter_index,paused,sort,active_only,query,detail_key,detail_offset,view,ui.screen.getmaxyx(),int(now))
            if changed!=stamp:
                page=paint(ui,shown,rows,index,filter_index,paused,sort,active_only,query,now,detail,detail_offset,view)
                stamp=changed
            ui.screen.timeout(100)
            key=ui.key()
            if key in ['\x1b','q','Q']:
                if detail_key is not None:detail_key=None;detail_offset=0;continue
                return
            if key in ['\n','\r',curses.KEY_ENTER,'d','D']:
                detail_key=None if detail_key is not None else selected;detail_offset=0
            elif key==' ':
                paused=not paused;frozen=copy.deepcopy(model) if paused else None
            elif key in [curses.KEY_UP,'k']:
                if detail_key is not None:detail_offset=max(0,detail_offset-1)
                else:index=max(0,index-1);selected=rows[index]['key'] if rows else None
            elif key in [curses.KEY_DOWN,'j']:
                if detail_key is not None:detail_offset+=1
                else:index=min(max(0,len(rows)-1),index+1);selected=rows[index]['key'] if rows else None
            elif key in ['\t',curses.KEY_F1,curses.KEY_F2,curses.KEY_F3]:
                views=['overview','targets','timeline']
                view=views[(views.index(view)+1)%3] if key=='\t' else views[[curses.KEY_F1,curses.KEY_F2,curses.KEY_F3].index(key)]
                detail_key=None;detail_offset=0
            elif isinstance(key,str) and key in ['1','2','3','4','5']:
                filter_index=int(key)-1;index=0;selected=None;detail_key=None
            elif key in [curses.KEY_LEFT,curses.KEY_RIGHT]:
                filter_index=(filter_index+(-1 if key==curses.KEY_LEFT else 1))%len(FILTERS);index=0;selected=None;detail_key=None
            elif key in [curses.KEY_NPAGE,curses.KEY_PPAGE]:
                move=page if key==curses.KEY_NPAGE else -page
                if detail_key is not None:detail_offset=max(0,detail_offset+move)
                else:index=max(0,min(len(rows)-1,index+move));selected=rows[index]['key'] if rows else None
            elif key in ['f','F']:active_only=not active_only;index=0;selected=None
            elif key in ['s','S']:sort={'speed':'total','total':'target','target':'speed'}[sort];selected=None
            elif key=='/':
                ui.screen.timeout(-1)
                answer=ui.text('筛选最终目标或域名（清空回车恢复全部）',query)
                if answer is not None:query=answer
                index=0;selected=None;stamp=None
            elif key=='?':
                ui.message('实时流量 · 操作与统计口径',help_text());stamp=None
    finally:
        ui.screen.timeout(-1);sampler.close()
