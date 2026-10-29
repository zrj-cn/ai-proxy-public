# 三类分流与 Claude 域名

规则页只列三类，选择域名后可看来源、优先级、失败行为；自定义规则可直接编辑或删除。

| 类别 | 请求路径 | 链路失败时 |
|---|---|---|
| 始终代理（紫色） | 本机 → A → B → 目标 | 失败即停止，不直连、不少一跳 |
| 始终直连（绿色） | 服务器直接出站 | 沿用服务器网络；更高优先级的 AI 规则仍优先 |
| 代理优先，可回退（黄色） | 优先完整 A → B | 健康检查判定链路不可用后，新连接可 DIRECT |

AI 与其余外部目标默认属于第一类。第三类只允许你明确指定的非 AI 域名（精确/后缀），不接受 IP 网段，初始为空，不自动迁移已有规则。每台机器独立选择自己的入口 A 和落地 B。禁止把覆盖已知 AI 的域名/后缀加入第三类；直接编辑文件或导入迁移包也会再次校验。

```bash
ai-proxy rule add DOMAIN ordinary.example.org FALLBACK
ai-proxy rule explain ordinary.example.org
ai-proxy rule custom
# 用实际自定义编号替换 1
ai-proxy rule edit 1 DOMAIN ordinary.example.org CHAIN
ai-proxy rule delete 1
```

回退由 mihomo fallback 组的健康状态驱动，顺序只有 EXIT_B、DIRECT，EXIT_B 自身仍通过 A。探测地址为 `https://www.gstatic.com/generate_204`，期望204，间隔120秒、超时4秒、惰性检查。只有配置了第三类规则才生成此组；并非每个失败请求都会立即重放。HTTP 401/403/429等业务响应不自动触发针对该目标的回退，不把AI服务错误当作“改直连”的理由。探测地址的可达性可能与具体目标不同，说明页和域名查询会展示当前组的出站。停止整个 mihomo 服务后代理入口不存在，第三类也不能替客户端执行回退。

优先级：内置 AI → 自定义始终代理 → 本地地址 → 自定义始终直连 → 自定义可回退 → 内置下载直连 → 可选开发下载直连 → 其余外部始终代理。列表中的大范围直连可能有更具体的强制代理例外，选择规则可见提示；查询具体域名得到实际命中原因。IP规则保持 no-resolve，不接管系统DNS或UDP。

## Python、PyTorch 与 CUDA 下载直连

以下属于默认“始终直连”，无需打开可选开发规则：

| 下载 | 域名 |
|---|---|
| pip/PyPI 索引、wheel/源码包 | `pypi.org`、`pythonhosted.org` 及其子域；旧索引 `pypi.python.org` |
| pip 引导安装脚本 | `bootstrap.pypa.io` |
| PyTorch CPU/CUDA wheel、torchvision/torchaudio、模型文件 | `download.pytorch.org`、`download-r2.pytorch.org` |
| CUDA/cuDNN/驱动安装包、APT/RPM/redist | `download.nvidia.com` 及其子域，包括 `developer.download.nvidia.com` |
| NVIDIA Python 包索引 | `pypi.nvidia.com`、旧索引 `pypi.ngc.nvidia.com` |

PyPI上的 `nvidia-*-cu12/cu13` 等依赖同样经其文件下载域名直连。实时面板分别归为“PyPI / pip”“PyTorch”“NVIDIA / CUDA”，回车可看实际最终域名与通道。规则按域名生效；自定义镜像若使用其他域名，需按实际域名添加规则。AI始终代理优先级保持不变，也没有把整个NVIDIA、CloudFront或AWS共享域名设为直连。可选开发规则现在仅保留npm/Docker。

依据：[PyPI pip索引](https://pypi.org/simple/pip/)、[PyTorch官方CUDA wheel索引](https://download.pytorch.org/whl/cu128/torch/)（文件链接指向download-r2.pytorch.org）、[CUDA Linux安装指南](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/)、[NVIDIA Python索引](https://pypi.nvidia.com/)。

## Claude 核对

已读取 [Net.Coffee 域名线索](https://ip.net.coffee/claude/site.html)，并对照 [Claude 官方网络要求](https://code.claude.com/docs/en/network-config)。后缀规则本来就包含对应子域，例如 `anthropic.com` 已覆盖 `api.anthropic.com`、`mcp-proxy.anthropic.com`。不在直连名单里的外部域名默认也走完整代理链，未单列不代表漏走代理。

| 域名 | 处理与证据 |
|---|---|
| anthropic.com、claude.ai、claude.com、claudeusercontent.com | 已有强制代理，覆盖API、认证、内容及辅助子域；官方网络文档 |
| claudemcpcontent.com | 已有强制代理；官方 Desktop 内容组件 |
| clau.de | 新增专用后缀；专用短链后缀，覆盖短链及跳转目标；请在自己的机器上验证实际访问结果 |
| claudemcpclient.com | 新增强制代理；来自线索页；需按自己的实际应用核实解析与使用情况 |
| anthropic.auth0.com | 新增精确强制代理；历史认证线索，不代表当前 Claude 仍使用它 |
| anthropic.com.cdn.cloudflare.net、servd-anthropic-website.b-cdn.net | 新增精确强制代理；专用 CDN 线索，需按实际会话验证用途 |
| anthropic-com.ghost.io | 新增精确强制代理；内容线索，不保证当前仍提供业务内容 |
| http-intake.logs.us5.datadoghq.com、browser-intake-us5-datadoghq.com | 已有精确强制代理；官方列出的可选遥测主机 |
| sentry.io、statsigapi.net、intercom.io/intercomcdn.com等共享服务 | 不整站接管为AI强制规则；接入程序访问时，未列为直连的目标仍由默认完整代理处理 |
| datadog/sift宽泛关键词、共享IP网段/ASN、NTP | 不导入；不因此改变整机网络/时间/IPv6配置 |

域名线索不是应用成功验收，也不表示每个域名仍在当前业务中使用。后续可在菜单“查询域名怎么走”查看具体路由，或“诊断→指定目标验证”观测真实请求。网络到达不等于应用可用，也不保证账号风控结果。
