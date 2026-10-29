"""Curses observatory: bounded panels and block digits, no network or configuration writes."""
from __future__ import annotations
import curses
import os
from .traffic import CHANNELS,FILTERS,human
from .tui import clip,width,wrapped

VIEWS=[('overview','总览'),('targets','目标'),('timeline','趋势')]
ROUTES=[('CHAIN','完整代理 · A → B','mint'),('DIRECT','直连下载','gold'),('FALLBACK_DIRECT','回退直连','pink')]
DIGITS={
 '0':['111','101','101','101','111'],'1':['010','110','010','010','111'],
 '2':['111','001','111','100','111'],'3':['111','001','111','001','111'],
 '4':['101','101','111','001','001'],'5':['111','100','111','001','111'],
 '6':['111','100','111','101','111'],'7':['111','001','010','010','010'],
 '8':['111','101','111','101','111'],'9':['111','101','111','001','111'],
 '.':['0','0','0','0','1'],'—':['000','000','111','000','000']}


def digits(text):
    return [' '.join(''.join('█' if bit=='1' else ' ' for bit in DIGITS.get(ch,DIGITS['—'])[y]) for ch in text) for y in range(5)]


def compact_rate(value):
    if value is None:return '—','等待采样'
    number,unit=human(value,True).split(' ',1)
    return number,unit


class Theme:
    """Use existing xterm colors; never alter the user's terminal palette."""
    def __init__(self):
        self.styles={};self.base=0
        if os.environ.get('NO_COLOR'):return
        try:
            if not curses.has_colors():return
            curses.start_color()
            if getattr(curses,'COLORS',0)>=256 and getattr(curses,'COLOR_PAIRS',0)>48:
                colors={'base':(252,233),'panel':(252,234),'muted':(245,234),'border':(60,234),
                        'mint':(121,234),'gold':(222,234),'pink':(211,234),'title':(147,233),
                        'selected':(255,60),'tab':(233,147),'error':(203,234)}
            else:
                colors={'base':(curses.COLOR_WHITE,curses.COLOR_BLACK),'panel':(curses.COLOR_WHITE,curses.COLOR_BLACK),
                        'muted':(curses.COLOR_WHITE,curses.COLOR_BLACK),'border':(curses.COLOR_BLUE,curses.COLOR_BLACK),
                        'mint':(curses.COLOR_CYAN,curses.COLOR_BLACK),'gold':(curses.COLOR_YELLOW,curses.COLOR_BLACK),
                        'pink':(curses.COLOR_MAGENTA,curses.COLOR_BLACK),'title':(curses.COLOR_CYAN,curses.COLOR_BLACK),
                        'selected':(curses.COLOR_WHITE,curses.COLOR_BLUE),'tab':(curses.COLOR_BLACK,curses.COLOR_CYAN),
                        'error':(curses.COLOR_RED,curses.COLOR_BLACK)}
            for index,(name,(fg,bg)) in enumerate(colors.items(),32):
                curses.init_pair(index,fg,bg);self.styles[name]=curses.color_pair(index)
            self.base=self.styles.get('base',0)
        except curses.error:self.styles={};self.base=0

    def __call__(self,name,bold=False):return self.styles.get(name,0)|(curses.A_BOLD if bold else 0)


class Canvas:
    def __init__(self,ui):
        self.ui=ui;self.h,self.w=ui.screen.getmaxyx()
        if not hasattr(ui,'dashboard_theme'):ui.dashboard_theme=Theme()
        self.theme=ui.dashboard_theme
    def text(self,y,x,text,tone='panel',bold=False,limit=None):
        self.ui.put(y,clip(text,limit) if limit is not None else text,self.theme(tone,bold),x=x)
    def blank(self):
        self.ui.screen.erase()
        for y in range(self.h):self.text(y,0,' '*(self.w-1),'base')
    def panel(self,y,x,h,w,title,tone='border'):
        if h<3 or w<8:return
        for row in range(y,y+h):self.text(row,x,' '*w)
        self.text(y,x,'╭'+'─'*(w-2)+'╮',tone)
        self.text(y+h-1,x,'╰'+'─'*(w-2)+'╯',tone)
        for row in range(y+1,y+h-1):self.text(row,x,'│',tone);self.text(row,x+w-1,'│',tone)
        self.text(y,x+2,' '+title+' ',tone,True,limit=w-5)
    def chart(self,y,x,h,w,values,tone='mint',peak=None):
        values=list(values)[-w:]
        if not values:self.text(y+h-1,x,'等待采样…','muted');return
        scale=max((v for v in values if v is not None),default=0) if peak is None else peak
        for col in range(w):
            # Left-pad the graph: before the first sample is unknown, not measured zero.
            offset=col-(w-len(values))
            if offset<0:continue
            value=values[offset]
            if value is None:continue
            blocks=0 if not scale or value<=0 else max(1,int(round(value/scale*h*8)))
            for row in range(h):
                fill=max(0,min(8,blocks-(h-row-1)*8))
                if fill:self.text(y+row,x+col,'▁▂▃▄▅▆▇█'[fill-1],tone)
                elif row==h-1:self.text(y+row,x+col,'·','muted')


def route_tone(route):
    return {'CHAIN':'mint','A':'mint','DIRECT':'gold','FALLBACK_DIRECT':'pink','REJECT':'error','UNKNOWN':'pink'}.get(route,'muted')


def card(canvas,model,route,label,tone,y,x,h,w):
    canvas.panel(y,x,h,w,label,tone)
    summary=model.route_summary(route)
    known=model.last_time is not None and model.rate[0] is not None and not model.error
    rate=summary['down_rate'] if known else None
    number,unit=compact_rate(rate)
    if h>=10:
        for i,line in enumerate(digits(number)):canvas.text(y+1+i,x+2,line,tone,True,limit=w-4)
        canvas.text(y+6,x+2,unit+'  下载',tone)
        canvas.text(y+7,x+2,'↑ '+human(summary['up_rate'] if known else None,True)+'  · '+str(summary['active'])+' 连接','muted',limit=w-4)
    else:
        canvas.text(y+1,x+2,number+' '+unit+' ↓',tone,True,limit=w-4)
        canvas.text(y+2,x+2,'↑ '+human(summary['up_rate'] if known else None,True)+' · '+str(summary['active'])+' 连接','muted',limit=w-4)
    history=getattr(model,'route_history',{}).get(route,[])
    chart_h=max(1,h-11) if h>=10 else 1
    chart_y=y+h-1-chart_h
    if h>=12:canvas.text(y+8,x+2,'本页 ↓ '+human(summary['down'])+'  ↑ '+human(summary['up']),'muted',limit=w-4)
    canvas.chart(chart_y,x+2,chart_h,w-4,[sample[1] for sample in history],tone)


def draw_targets(canvas,model,rows,index,y,x,h,w,sort,active_only,query):
    mode='活跃' if active_only else '活跃 + 近期30s'
    sort_label={'speed':'速率','total':'本页流量','target':'名称'}[sort]
    canvas.panel(y,x,h,w,'最终目标 → 实际通道   '+mode+'   排序 '+sort_label,'border')
    if h<5:return 1
    inner=w-4;wide=inner>=104
    name_w=max(14,min(34,inner-(78 if wide else 45)))
    # Field widths count terminal cells, not Unicode codepoints.
    def pad(text,n):return clip(text,n)+' '*max(0,n-width(clip(text,n)))
    header='  '+pad('最终目标',name_w)+' '+pad('实际通道',12)+' '+pad('↓ 下载/s',12)
    if wide:header+=' '+pad('↑ 上传/s',12)+' '+pad('本页字节',12)+' 连接 / 状态'
    else:header+=' 连接'
    canvas.text(y+1,x+2,header,'muted',True,limit=inner)
    page=max(1,h-4);start=(index//page)*page
    if not rows:canvas.text(y+2,x+2,'暂无匹配连接 · 等待应用访问，或切回 [全部]','muted',limit=inner)
    for offset,row in enumerate(rows[start:start+page]):
        selected=start+offset==index;tone='selected' if selected else route_tone(row['channel'])
        target=row['target']+(f" ·{len(row['hosts'])}域名" if len(row['hosts'])>1 else '')
        rate=lambda key:human(None if model.error else row[key],True)
        line=('› ' if selected else '  ')+pad(target,name_w)+' '+pad(CHANNELS[row['channel']],12)+' '+pad(rate('down_rate'),12)
        if wide:line+=' '+pad(rate('up_rate'),12)+' '+pad(human(row['up']+row['down']),12)+' '+str(row['active'])+(' / 旧数据' if model.error else ' / 活跃' if row['active'] else ' / 已结束')
        else:line+=' '+str(row['active'])
        canvas.text(y+2+offset,x+2,pad(line,inner),tone,selected,limit=inner)
    footer=f'{index+1 if rows else 0}/{len(rows)} 项'
    if query:footer+='  筛选 '+query
    if model.evicted:footer+='  部分目标已省略'
    canvas.text(y+h-2,x+2,footer,'muted',limit=inner)
    return page


def draw_activity(canvas,model,y,x,h,w):
    canvas.panel(y,x,h,w,'ACTIVITY / 最近60次采样 · 同一比例','border')
    routes=ROUTES;inner=w-17
    peak=max((v[1] for route,_,_ in routes for v in getattr(model,'route_history',{}).get(route,[]) if v[1] is not None),default=0)
    band=max(1,(h-3)//3)
    for i,(route,label,tone) in enumerate(routes):
        row_y=y+1+i*band
        canvas.text(row_y+band-1,x+2,{'CHAIN':'完整代理','DIRECT':'直连','FALLBACK_DIRECT':'回退直连'}[route],tone,limit=10)
        canvas.chart(row_y,x+13,band,inner,[v[1] for v in getattr(model,'route_history',{}).get(route,[])],tone,peak)


def draw_rank(canvas,model,rows,y,x,h,w):
    canvas.panel(y,x,h,w,'TARGET VELOCITY / 下载速率','border')
    candidates=sorted(rows,key=lambda r:r['down_rate'],reverse=True)[:max(1,(h-2)//3)]
    peak=max((r['down_rate'] for r in candidates),default=0)
    for i,row in enumerate(candidates):
        row_y=y+1+i*3
        tone=route_tone(row['channel']);rate=human(None if model.error else row['down_rate'],True)
        canvas.text(row_y,x+2,row['target'],tone,limit=max(8,w-20))
        canvas.text(row_y,x+w-2-width(rate),rate,tone)
        if not model.error and peak and row['down_rate']:
            size=max(1,round(row['down_rate']/peak*(w-4)))
            canvas.text(row_y+1,x+2,'━'*size,tone,limit=w-4)
        else:canvas.text(row_y+1,x+2,'·'*(w-4),'muted')
    if not candidates:canvas.text(y+2,x+2,'等待最终目标连接…','muted',limit=w-4)


def render(ui,model,rows,index,filter_index,paused,sort,active_only,query,now,detail=None,detail_offset=0,view='overview',detail_text=''):
    canvas=Canvas(ui);canvas.blank();h,w=canvas.h,canvas.w
    canvas.text(0,2,'◈ AI PROXY  /  实时流量观测台','title',True)
    badge='Ⅱ PAUSED' if paused else '● API OFFLINE' if model.error else '● LIVE' if model.last_time is not None else '○ WAITING'
    canvas.text(0,w-width(badge)-3,badge,'pink' if paused or model.error else 'mint',True)
    canvas.text(1,2,'最终目标 → 实际通道  ·  上传/下载业务字节  ·  不读取请求内容','muted')
    tab_x=2
    for i,(key,label) in enumerate(VIEWS):
        text=f' F{i+1} {label} '
        canvas.text(3,tab_x,text,'tab' if key==view else 'muted',key==view);tab_x+=width(text)+2
    tabs='  '.join('['+label+']' if i==filter_index else label for i,(label,_) in enumerate(FILTERS))
    canvas.text(5,2,'通道  '+tabs,'title',True,limit=w-5)
    age=max(0,int(now-model.last_time)) if model.last_time is not None else None
    status='暂停画面 · 后台仍采样' if paused else model.error+' · 下方为旧数据' if model.error else '数据读取正常 · 不代表链路健康' if age is not None else '等待首次采样…'
    if age is not None and age>=3:status+=f'  | 上次采样 {age}s前'
    canvas.text(6,2,status,'pink' if paused or model.error else 'muted',limit=w-4)
    start=8;end=h-3;page=1
    if detail is not None:
        canvas.panel(start,1,end-start,w-2,'连接详情 · '+detail['target'],'title')
        lines=wrapped(detail_text,w-8);page=max(1,end-start-3)
        offset=min(detail_offset,max(0,len(lines)-page))
        for i,line in enumerate(lines[offset:offset+page]):canvas.text(start+1+i,3,line,limit=w-7)
    elif view=='targets':
        page=draw_targets(canvas,model,rows,index,start,1,end-start,w-2,sort,active_only,query)
    elif view=='timeline':
        chart_h=max(7,(end-start)*2//3)
        left_w=max(55,(w-4)*2//3)
        draw_activity(canvas,model,start,1,chart_h,left_w)
        draw_rank(canvas,model,rows,start,left_w+2,chart_h,w-left_w-3)
        page=draw_targets(canvas,model,rows,index,start+chart_h+1,1,end-start-chart_h-1,w-2,sort,active_only,query)
    else:
        available=end-start
        card_h=13 if available>=32 else 11 if available>=22 else 10 if available>=18 else 8 if available>=15 else 6
        gap=2;total_w=w-4;card_w=(total_w-2*gap)//3
        for i,(route,label,tone) in enumerate(ROUTES):
            box_w=card_w if i<2 else total_w-2*(card_w+gap)
            card(canvas,model,route,label,tone,start,2+i*(card_w+gap),card_h,box_w)
        below=start+card_h+1
        if end-below>=17:
            chart_h=max(7,min(10,(end-below)//2-1));left_w=(w-4)*2//3
            draw_activity(canvas,model,below,1,chart_h,left_w)
            draw_rank(canvas,model,rows,below,left_w+2,chart_h,w-left_w-3)
            below+=chart_h+1
        page=draw_targets(canvas,model,rows,index,below,1,end-below,w-2,sort,active_only,query)
    totals='核心 ↑ '+human(model.rate[0],True)+'  ↓ '+human(model.rate[1],True)
    if model.core_totals:totals+='  · 累计 ↓ '+human(model.core_totals[1])
    canvas.text(h-3,2,totals+'  · A/B业务量不重复相加','muted',limit=w-4)
    canvas.text(h-2,2,'Tab视图  1–5/←→通道  ↑↓选择  Enter详情  空格暂停  /搜索  S排序  ?帮助  Esc返回','title',limit=w-4)
    canvas.text(h-1,2,model.notice or '薄荷绿完整代理 / 金色直连 / 粉色回退 · 入口 A 与落地 B 业务量不重复计数；短连接可能漏采。','muted',limit=w-4)
    ui.screen.refresh();return page
