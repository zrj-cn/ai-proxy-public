"""Readable terminal output; structured data stays available with --json."""
import contextlib
import contextvars
import json
import os
import sys
import unicodedata

_CAPTURE=contextvars.ContextVar('ai_proxy_output_capture',default=None)
ACTIONS={'CHAIN':'始终代理 · A → B，失败即停止','DIRECT':'始终直连','FALLBACK':'代理优先 · 链路不可用后直连'}
TYPES={'DOMAIN':'精确域名','DOMAIN-SUFFIX':'域名及子域','IP-CIDR':'IPv4 网段','IP-CIDR6':'IPv6 网段','MATCH':'其余目标'}
LABELS={
 'previous_results':'上次验收记录','current_outbound':'当前可回退组出站','service':'服务','http_proxy':'HTTP 入口','control_api':'控制入口','entry_A':'入口 A','entry_id':'入口标识','entry':'入口 A','exit_B':'落地 B','exit':'落地 B','chain':'完整链路','path':'路径','ready':'已配置完整链','entry_tls_identity_verified':'入口证书身份已验证',
 'applications_configured':'已配置应用','applications_verified':'应用验收','last_doctor':'最近诊断','time':'检查时间','counts':'结果汇总','credentials':'凭证',
 'check':'检查项目','result':'结果','detail':'详情','reason':'原因','error':'错误','note':'说明','scope':'验证范围','evidence':'证据','application_layer':'应用层',
 'ok':'请求成功','history':'请求过程','observed':'实际路由观测','host':'目标域名','status':'HTTP 状态','route':'路由','rule':'规则类型','rule_payload':'命中内容','chains':'实际出站','socket_evidence':'核心连接观测','entry_socket_seen':'观察到连接 A','direct_B_socket_seen':'观察到直接连接 B','proc_observation_available':'进程观测可用',
 'mode':'检测对象','forced_rule':'强制检测路径','exit_ip':'最终出口 IP','B_independent_exit_ip':'B 独立出口 IP','same_exit_as_B':'与 B 出口一致','disabled':'模拟故障跳',
 'application':'应用','negative':'代理不可用对照','exit_code':'退出码','timed_out':'是否超时','expected_reply_received':'收到预期 AI 回复','authenticated_proxy_attempts':'已认证代理请求次数','external_tcp_socket_observed':'观察到外部 TCP','process_tree_observed':'已观测应用进程树',
 'priority':'优先级','type':'匹配类型','value':'匹配内容','action':'路由策略','source':'来源','custom_id':'自定义编号','winner':'先命中优先级','shadowed':'后命中优先级','first':'先命中规则','later':'被覆盖规则',
 'id':'标识','label':'名称','protocol':'协议','role':'当前用途','address':'地址','tls_cert_verified':'验证代理证书','url':'订阅地址','nodes':'节点数','updated':'最近更新','ids':'节点标识','imported_ids':'导入节点',
 'current_process_conflicting_env_keys':'当前进程冲突变量','installed':'已安装','version':'版本','claude_settings':'Claude 设置','all_match':'代理设置一致','private_permissions':'权限受限','merged_proxy_keys':'已合并变量','running_app_processes':'已有应用进程','pid':'进程号','name':'名称','inherited_proxy_matches':'继承代理一致','conflicting_keys':'冲突变量','http_status':'HTTP 状态','port':'端口','family':'地址族','loopback':'仅回环',
 'Linger':'退出登录后持续运行','unit_enabled':'已启用启动恢复','required_if_no_linger':'缺少持续运行时所需操作','config':'配置检查','chain_ready':'链路已配置','conflicts':'规则冲突','detected':'检测版本','launcher':'启动命令','state':'接入状态','backup':'备份文件','contains_secrets':'包含秘密','subscription_insecure_tls_count':'跳过代理证书验证的节点数','warning':'注意'
}
SOURCES={'OpenAI':'OpenAI 核心服务','OpenAI assets':'OpenAI 静态资源','OpenAI attachments':'OpenAI 附件','Claude official network docs':'Claude 官方网络文档','Claude Desktop widgets':'Claude Desktop 内容组件','Claude official optional telemetry':'Claude 官方列出的可选遥测','Claude official optional error reporting':'Claude 官方列出的可选错误上报','custom':'自定义','local':'本地地址','loopback':'回环地址','default external; DNS IP rules use no-resolve':'其余外部目标，默认走完整链路'}

def scalar(value):
    if value is True:return '是'
    if value is False:return '否'
    if value is None:return '未设置'
    if isinstance(value,str):return ACTIONS.get(value,TYPES.get(value,SOURCES.get(value,{'ENTRY_A':'入口 A','EXIT_B':'完整链路出口 B','CHAIN_OR_DIRECT':'可回退代理组','ENTRY_A 不可用':'入口 A 不可用'}.get(value,value))))
    return str(value)


def generic(value,level=0):
    prefix='  '*level;lines=[]
    if isinstance(value,dict):
        for key,item in value.items():
            if key=='signature':continue
            label=LABELS.get(key,str(key).replace('_',' '))
            if isinstance(item,(dict,list)):
                if not item:lines.append(prefix+label+'：无');continue
                if isinstance(item,list) and all(not isinstance(v,(dict,list)) for v in item):lines.append(prefix+label+'：'+'、'.join(scalar(v) for v in item))
                else:lines.append(prefix+label+'：');lines+=generic(item,level+1)
            else:lines.append(prefix+label+'：'+scalar(item))
    elif isinstance(value,list):
        for i,item in enumerate(value,1):
            if i>1:lines.append('')
            if isinstance(item,(dict,list)):lines+=generic(item,level)
            else:lines.append(prefix+scalar(item))
    else:lines.append(prefix+scalar(value))
    return lines


def request_lines(value):
    lines=[]
    for step in value.get('history',[]):
        lines.append('  '+str(step.get('host','目标'))+'  →  HTTP '+str(step.get('status','?'))+'  ·  '+scalar(step.get('route','')))
    for step in value.get('observed',[]):
        host=step.get('host')
        if not host:continue
        route=' → '.join(scalar(v) for v in step.get('chains',[]))
        lines.append('  实测 '+host+'  →  '+route)
    for key in ['exit_ip','B_independent_exit_ip','same_exit_as_B','error','reason']:
        if key in value:lines.append(LABELS[key]+'：'+scalar(value[key]))
    return lines


def render(value,details=False):
    if details:return '\n'.join(generic(value))
    if isinstance(value,dict) and 'service' in value and 'http_proxy' in value:
        lines=['服务：'+str(value['service']),'入口：'+str(value['http_proxy']),'','入口 A：'+str(value.get('entry_A','未配置')),'落地 B：'+str(value.get('exit_B','未配置')),'路径：'+str(value.get('chain','未验证')),'']
        if value.get('entry_tls_identity_verified') is False:lines.append('注意：入口 A 按原节点设置跳过证书验证。')
        lines.append('已接入设置：'+'、'.join({'claude-settings':'Claude Code / Desktop SSH','codex-ai-launcher':'Codex 专用入口'}.get(v,v) for v in value.get('applications_configured',[])))
        counts=value.get('last_doctor',{}).get('counts',{})
        if counts:lines.append('最近检查：'+' / '.join(k+' '+str(v) for k,v in counts.items()))
        lines.append('技术详情：CLI 加 --details；菜单按 D。')
        return '\n'.join(lines)
    if isinstance(value,dict) and 'current_process_conflicting_env_keys' in value:
        lines=[]
        for name in ['claude','codex']:
            item=value.get(name,{})
            lines.append(name+'：'+(str(item.get('version','已安装')) if item.get('installed') else '未安装'))
        env=value.get('current_process_conflicting_env_keys',[])
        lines.append('当前进程环境：'+('存在旧代理变量 '+ '、'.join(env) if env else '未发现冲突变量'))
        settings=value.get('claude_settings',{})
        if settings:lines.append('Claude 设置：'+('与本入口一致' if settings.get('all_match') else '需检查或重新配置'))
        lines.append('已有应用进程：'+str(len(value.get('running_app_processes',[])))+' 个，环境不会自动更新。')
        lines.append('实际应用可用性：仍需最小请求验证。')
        return '\n'.join(lines)
    if isinstance(value,list) and value and all(isinstance(r,dict) and 'check' in r for r in value):
        counts={k:sum(r.get('result')==k for r in value) for k in ['通过','失败','未验证']}
        lines=['检查完成  ·  '+'  /  '.join(k+' '+str(v)+' 项' for k,v in counts.items()),'']
        for row in value:
            lines.append(row.get('result','未验证')+'  '+row['check'])
            detail=row.get('detail')
            if isinstance(detail,str) and detail:lines.append('  '+detail)
            elif isinstance(detail,dict):
                if detail.get('reason') or detail.get('error'):lines.append('  '+str(detail.get('reason') or detail.get('error')))
                if 'current_process_conflicting_env_keys' in detail:
                    for name in ['claude','codex']:
                        app=detail.get(name,{})
                        lines.append('  '+name+'：'+(str(app.get('version','已安装')) if app.get('installed') else '未安装'))
                    if detail.get('current_process_conflicting_env_keys'):lines.append('  当前会话有旧代理环境变量，启动新应用时需检查。')
                if detail.get('exit_ip'):lines.append('  出口：'+str(detail['exit_ip']))
                if detail.get('history'):
                    lines.append('  '+' → '.join(str(s.get('host',''))+' ('+str(s.get('status','?'))+')' for s in detail['history']))
        lines+=['','详情：菜单按 D 展开；CLI 加 --details。未验证不等于通过。']
        return '\n'.join(lines)
    if isinstance(value,list) and value and all(isinstance(r,dict) and 'action' in r and 'value' in r for r in value):
        return '\n'.join(str(r.get('priority',r.get('custom_id','·'))).rjust(2)+'  '+str(r['value'])+'  ·  '+TYPES.get(r.get('type'),str(r.get('type','')))+'  →  '+ACTIONS.get(r['action'],r['action']) for r in value)
    if isinstance(value,list) and value and all(isinstance(r,dict) and 'label' in r for r in value):
        return '\n'.join(str(r['label'])+'  ['+str(r.get('protocol',''))+']'+('  ·  '+str(r['role']) if r.get('role') else '') for r in value)
    if isinstance(value,dict) and ('history' in value or 'expected_reply_received' in value or 'mode' in value):
        responded=bool(value.get('history')) and not value.get('error')
        state=value.get('result') or ('通过' if value.get('ok') else '已收到目标响应，HTTP 状态非成功' if responded else '失败')
        lines=[state+'  '+({'A':'入口 A','B':'落地 B','chain':'完整 A → B 链路'}.get(value.get('mode'),value.get('application','请求验证'))),'']
        lines+=request_lines(value)
        if responded and not value.get('ok'):lines.append('说明：收到响应不等于 AI 应用可用；请检查目标认证、权限或服务状态。')
        for key in ['expected_reply_received','exit_code','timed_out','authenticated_proxy_attempts','external_tcp_socket_observed','scope','application_layer']:
            if key in value:lines.append(LABELS[key]+'：'+scalar(value[key]))
        socket=value.get('socket_evidence',{})
        if socket.get('proc_observation_available'):
            lines.append('连接核实：'+('观察到 A' if socket.get('entry_socket_seen') else '未观察到 A')+'；'+('观察到直接拨号 B' if socket.get('direct_B_socket_seen') else '未观察到直接拨号 B'))
        return '\n'.join(lines)
    return '\n'.join(generic(value)) or '暂无记录。'


@contextlib.contextmanager
def capture():
    values=[];token=_CAPTURE.set(values)
    try:yield values
    finally:_CAPTURE.reset(token)


def emit(value,json_mode=False,details=False):
    values=_CAPTURE.get()
    if values is not None and isinstance(value,(dict,list)):values.append(value)
    if json_mode and values is None and isinstance(value,(dict,list)):print(json.dumps(value,ensure_ascii=False,indent=2))
    else:
        text=render(value,details=details)
        text=''.join(ch for ch in text if ch in '\n\t' or not unicodedata.category(ch).startswith('C'))
        if sys.stdout.isatty() and not os.environ.get('NO_COLOR'):
            rows=[]
            for line in text.splitlines():
                key=line.lstrip()
                color='31' if key.startswith('失败') else '32' if key.startswith('通过') or '始终直连' in key else '35' if '始终代理' in key else '33' if any(t in key for t in ['未验证','注意','可回退']) else None
                rows.append(('\x1b['+color+'m'+line+'\x1b[0m') if color else line)
            text='\n'.join(rows)
        print(text)
