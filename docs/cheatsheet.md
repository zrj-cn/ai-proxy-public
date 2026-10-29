# 一页命令速查

`ai-proxy` 打开方向键中文菜单：↑↓选择，→/回车确认，←/Esc返回，PgUp/PgDn翻页，Ctrl+C退出且服务继续。切换入口/落地、更新订阅、服务管理与诊断均无需输入命令或节点ID。只有新增地址/密码等必要内容才需填写。结果默认中文摘要，D展开详情；规则按始终代理/始终直连/可回退分组。

`ai-proxy help` 显示参数。若 PATH 尚无 `~/.local/bin`，使用 `~/.local/bin/ai-proxy`。

| 操作 | 可复制命令 |
|---|---|
| 快速开启/关闭/切换 | `ai-proxy on` / `ai-proxy off` / `ai-proxy toggle` |
| 实时最终目标与通道 | `ai-proxy traffic`（Tab切换观测视图、←→筛选、↑↓选择、回车详情、空格暂停） |
| 中文摘要/技术详情/JSON | `ai-proxy doctor` / `ai-proxy --details doctor` / `ai-proxy --json doctor` |
| 指定非AI域名允许回退 | `ai-proxy rule add DOMAIN ordinary.example.org FALLBACK` |
| 总览/完整链路 | `ai-proxy status` / `ai-proxy chain` |
| 启动/停止/重启 | `ai-proxy service start` / `ai-proxy service stop` / `ai-proxy service restart` |
| 日志 | `ai-proxy service logs` |
| 安全添加/修改节点 | `ai-proxy node add my-A` / `ai-proxy node edit my-B` |
| 导入本地 600 节点文件 | `ai-proxy node import /安全路径/nodes.json` |
| 列出/搜索节点 | `ai-proxy node list` / `ai-proxy node list socks5` |
| 切换 A/B | `ai-proxy node select entry my-A` / `ai-proxy node select exit my-B` |
| 删除未选中节点 | `ai-proxy node delete old-A` |
| 订阅 URL 隐藏输入 | `ai-proxy subscription add source1` |
| 隐藏编辑/导入订阅URL | `ai-proxy subscription edit source1` / `ai-proxy subscription import source1 /安全路径/url.txt` |
| 更新/查看/删除订阅 | `ai-proxy subscription update source1` / `ai-proxy subscription list` / `ai-proxy subscription delete source1` |
| 分别检测 A/B/两跳 | `ai-proxy test A` / `ai-proxy test B` / `ai-proxy test chain` |
| 两跳出口 IP/断路测试 | `ai-proxy exit-ip` / `ai-proxy negative-test` |
| 查看/搜索规则 | `ai-proxy rule list` / `ai-proxy rule list hf.co` |
| 精确直连 | `ai-proxy rule add DOMAIN downloads.example.org DIRECT` |
| 后缀代理 | `ai-proxy rule add DOMAIN-SUFFIX new-ai.example CHAIN` |
| IP 规则 | `ai-proxy rule add IP-CIDR 192.0.2.0/24 CHAIN` |
| 自定义编号/编辑/删除 | `ai-proxy rule custom` / `ai-proxy rule edit 1 DOMAIN downloads.example.net DIRECT` / `ai-proxy rule delete 1` |
| 优先级/冲突/路由解释 | `ai-proxy rule list` / `ai-proxy rule conflicts` / `ai-proxy rule explain api.anthropic.com` |
| 可选开发下载规则 | `ai-proxy rule dev on` / `ai-proxy rule dev off` |
| 实际请求/重定向/命中 | `ai-proxy probe https://huggingface.co/bert-base-uncased/resolve/main/model.safetensors` |
| 校验/重载 | `ai-proxy validate` / `ai-proxy reload` |
| 应用配置/环境检查 | `ai-proxy app configure claude` / `ai-proxy app configure claude-desktop` / `ai-proxy app check` |
| Codex 新启动入口 | `ai-proxy app configure codex`，之后运行 `codex-ai` |
| 实际 AI 请求 | `ai-proxy app-test codex` / `ai-proxy app-test claude` |
| 隔离应用断路测试 | `ai-proxy app-test codex --negative` |
| 单个命令临时代理 | `ai-proxy run -- curl --max-time 20 https://api.openai.com/v1/models` |
| 安装检查/首次自定义端口 | `./install.sh --check` / `./install.sh --port 17890 --api-port 19090` |
| 尚无应用持久配置时改端口 | `ai-proxy ports 17892 19092` |
| 自动诊断/脱敏报告 | `ai-proxy doctor --network` / `ai-proxy report` |
| 明确版本升级/恢复 | `ai-proxy update v1.19.32` / `ai-proxy rollback version` |
| 恢复上一份输入与配置 | `ai-proxy rollback config` |
| 无秘密迁移包 | `ai-proxy backup export /安全路径/public.tar` / `ai-proxy backup import /安全路径/public.tar` |
| 卸载 | `ai-proxy uninstall --yes` |

停止服务保留应用代理配置，已接入应用暂时不可用；退出菜单保留服务。`test B` 显式直连 B，仅用于单独检测。任意 HTTP 响应都不能单独证明应用可用。
