"""Read-only connection snapshots. Keep only destination metadata, never requests or credentials."""
from __future__ import annotations
import collections
import ipaddress
import queue
import threading
import time
import unicodedata
import urllib.parse
from . import core as c

CHANNELS={'CHAIN':'完整代理','DIRECT':'直连','FALLBACK_DIRECT':'回退直连','A':'仅 A','REJECT':'拒绝','UNKNOWN':'通道待识别'}
FILTERS=[('全部',None),('完整代理','CHAIN'),('直连','DIRECT'),('回退直连','FALLBACK_DIRECT'),('其他','OTHER')]
SERVICES=[('Claude',['anthropic.com','claude.ai','claude.com','clau.de','claudeusercontent.com','claudemcpcontent.com','claudemcpclient.com']),('OpenAI',['openai.com','chatgpt.com','oaistatic.com','oaiusercontent.com']),('GitHub',['github.com','githubusercontent.com','githubassets.com','github.io']),('Hugging Face',['huggingface.co','hf.co']),('PyPI / pip',['pypi.org','pythonhosted.org','pypi.python.org','bootstrap.pypa.io']),('PyTorch',['download.pytorch.org','download-r2.pytorch.org']),('NVIDIA / CUDA',['download.nvidia.com','pypi.nvidia.com','pypi.ngc.nvidia.com'])]


def safe_host(value):
    value=''.join(ch for ch in str(value or '') if not unicodedata.category(ch).startswith('C')).strip()
    if not value:return ''
    # Metadata is untrusted: discard userinfo, query strings, paths and ports.
    if '://' in value:
        try:value=urllib.parse.urlsplit(value).hostname or ''
        except ValueError:return ''
    else:value=value.rsplit('@',1)[-1].split('/',1)[0].split('?',1)[0].split('#',1)[0]
    try:return str(ipaddress.ip_address(value.strip('[]')))
    except ValueError:pass
    value=value.lower().rstrip('.')
    try:value=value.encode('idna').decode('ascii')
    except UnicodeError:return ''
    if len(value)>253 or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789-.' for ch in value):return ''
    return value


def amount(value):
    try:return max(0,int(value or 0))
    except (ValueError,TypeError,OverflowError):return 0


def human(value,rate=False):
    if value is None:return '—'
    value=max(0,float(value));units=['B','KiB','MiB','GiB','TiB']
    for unit in units:
        if value<1024 or unit==units[-1]:break
        value/=1024
    return (f'{value:.1f}' if value<100 and unit!='B' else f'{value:.0f}')+' '+unit+('/s' if rate else '')


def spark(values,columns=22):
    values=list(values)[-columns:]
    if not values:return '·'
    peak=max((v for v in values if v is not None),default=0) or 1;bars='▁▂▃▄▅▆▇█'
    return ''.join(' ' if v is None else bars[min(7,int(max(0,v)/peak*7))] for v in values)


def channel(chains):
    # Prefer the actual final outbound over configured policy or group name.
    if 'REJECT' in chains or 'REJECT-DROP' in chains:return 'REJECT'
    if 'DIRECT' in chains:return 'FALLBACK_DIRECT' if 'CHAIN_OR_DIRECT' in chains else 'DIRECT'
    if 'EXIT_B' in chains:return 'CHAIN'
    if 'ENTRY_A' in chains:return 'A'
    return 'UNKNOWN'


def service(host):
    for label,suffixes in SERVICES:
        if any(host==s or host.endswith('.'+s) for s in suffixes):return label
    return host


class TrafficModel:
    def __init__(self,hidden_hosts=(),retention=30,limit=1000):
        self.hidden={safe_host(h) for h in hidden_hosts if h}
        self.retention=retention;self.limit=limit;self.rows={};self.previous={};self.last_time=None
        self.core_totals=None;self.rate=(None,None);self.history=collections.deque(maxlen=60)
        self.sample_totals=collections.defaultdict(lambda:[0,0]);self.error='';self.notice='';self.active=0
        self.sampling_started=False;self.evicted=False
        self.route_history={route:collections.deque(maxlen=60) for route in CHANNELS}

    def update(self,snapshot,now=None):
        now=time.monotonic() if now is None else now
        if not isinstance(snapshot,dict) or not isinstance(snapshot.get('connections'),(list,type(None))):
            self.fail('连接数据格式异常，等待下一次刷新');return
        totals=(amount(snapshot.get('uploadTotal')),amount(snapshot.get('downloadTotal')))
        reset=self.core_totals is not None and any(v<old for v,old in zip(totals,self.core_totals))
        if reset:
            self.rows.clear();self.previous.clear();self.history.clear();self.sample_totals.clear();self.last_time=None
            self.notice='核心计数已重置，已重新开始统计';self.sampling_started=False
            for history in self.route_history.values():history.clear()
        dt=now-self.last_time if self.last_time is not None else 0
        self.rate=tuple(max(0,v-old)/dt for v,old in zip(totals,self.core_totals)) if dt>0 and self.core_totals else (None,None)
        if dt>0:self.history.append(self.rate)
        for row in self.rows.values():row.update(active=0,up_rate=0.,down_rate=0.)
        previous={};self.active=0
        for item in snapshot.get('connections') or []:
            if not isinstance(item,dict):continue
            meta=item.get('metadata') or {}
            if not isinstance(meta,dict):continue
            # Mihomo exposes dialer-proxy transports as Inner trackers alongside final requests.
            if str(meta.get('type','')).lower()=='inner':continue
            host=safe_host(meta.get('host') or meta.get('destinationIP'))
            if not host or host in self.hidden:continue
            # Transit destinations are suppressed even when a metadata hostname aliases a configured endpoint.
            if safe_host(meta.get('destinationIP')) in self.hidden:continue
            chain_data=item.get('chains') or []
            chains=[v for v in chain_data if isinstance(v,str)] if isinstance(chain_data,list) else []
            route=channel(chains);group=service(host);key=(group,route)
            cid=str(item.get('id') or '')
            if not cid:continue
            counters=(amount(item.get('upload')),amount(item.get('download')))
            old=self.previous.get(cid)
            delta=tuple(max(0,v-o) for v,o in zip(counters,old)) if old else counters if self.sampling_started else (0,0)
            previous[cid]=counters
            row=self.rows.setdefault(key,{'key':key,'target':group,'channel':route,'hosts':set(),'rules':set(),'networks':set(),'active':0,'seen':0,'last_seen':now,'up':0,'down':0,'up_rate':0.,'down_rate':0.})
            row['hosts'].add(host)
            if len(row['hosts'])>100:row['hosts']=set(sorted(row['hosts'])[:100])
            rule=str(item.get('rule') or '')
            if rule:row['rules'].add(rule[:60])
            network=str(meta.get('network') or '')
            if network:row['networks'].add(network[:12])
            row['active']+=1;self.active+=1;row['last_seen']=now
            if not old:row['seen']+=1
            row['up']+=delta[0];row['down']+=delta[1]
            if dt>0:row['up_rate']+=delta[0]/dt;row['down_rate']+=delta[1]/dt
            for n in [0,1]:self.sample_totals[route][n]+=delta[n]
        self.rows={k:r for k,r in self.rows.items() if r['active'] or now-r['last_seen']<=self.retention}
        if len(self.rows)>self.limit:
            self.evicted=True
            self.rows=dict(sorted(self.rows.items(),key=lambda kv:(kv[1]['active']>0,kv[1]['last_seen']),reverse=True)[:self.limit])
        if dt>0:
            for route,history in self.route_history.items():
                summary=self.route_summary(route);history.append((summary['up_rate'],summary['down_rate']))
        self.previous=previous;self.core_totals=totals;self.last_time=now;self.error='';self.sampling_started=True

    def fail(self,message='控制 API 暂不可达；可能服务停止或连接失败，正在自动重连'):
        self.error=message;self.rate=(None,None)
        self.history.append((None,None))
        for history in self.route_history.values():history.append((None,None))
        # Keep last rows explicitly stale; never present a failed poll as zero traffic.

    def view(self,filter_index=0,sort='speed',active_only=False,query=''):
        route=FILTERS[filter_index][1];rows=[]
        for row in self.rows.values():
            if active_only and not row['active']:continue
            if route=='OTHER' and row['channel'] in ['CHAIN','DIRECT','FALLBACK_DIRECT']:continue
            if route and route!='OTHER' and row['channel']!=route:continue
            if query and query.lower() not in (row['target']+' '+' '.join(row['hosts'])).lower():continue
            rows.append(row)
        if sort=='target':return sorted(rows,key=lambda r:(r['target'].lower(),r['channel']))
        if sort=='total':return sorted(rows,key=lambda r:(r['up']+r['down'],r['target']),reverse=True)
        return sorted(rows,key=lambda r:(r['up_rate']+r['down_rate'],r['active'],r['last_seen'],r['target']),reverse=True)

    def route_summary(self,route):
        rows=[r for r in self.rows.values() if r['channel']==route]
        return {'up_rate':sum(r['up_rate'] for r in rows),'down_rate':sum(r['down_rate'] for r in rows),'up':self.sample_totals[route][0],'down':self.sample_totals[route][1],'active':sum(r['active'] for r in rows)}


class Sampler:
    """Only GET /connections, in a worker so API timeouts never block keyboard input."""
    def __init__(self,fetch=None,interval=1.):
        self.fetch=fetch or (lambda:c.api('/connections'));self.interval=interval
        self.stop_event=threading.Event();self.queue=queue.Queue(maxsize=1)
        self.thread=threading.Thread(target=self._run,daemon=True)

    def start(self):self.thread.start();return self
    def _run(self):
        while not self.stop_event.is_set():
            try:event=(time.monotonic(),self.fetch(),None)
            except Exception:event=(time.monotonic(),None,'控制 API 暂不可达；可能服务停止或连接失败，正在自动重连')
            if self.stop_event.is_set():return
            try:self.queue.get_nowait()
            except queue.Empty:pass
            self.queue.put_nowait(event)
            self.stop_event.wait(self.interval)

    def latest(self):
        try:return self.queue.get_nowait()
        except queue.Empty:return None

    def close(self):
        self.stop_event.set();self.thread.join(timeout=.15)
