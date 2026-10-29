# 新手部署步骤

适合课题组同学在自己的 Linux 账号下安装。工具负责安装 mihomo、管理 A→B 链式代理和分流，并提供方向键菜单及实时流量面板。**你需要准备自己的代理节点；仓库不提供可用节点、订阅或应用账号。**

## 1. 先准备什么

| 项目 | 要求 |
|---|---|
| 服务器 | Linux x86_64 / arm64；可通过 SSH 打开交互终端 |
| 软件 | Python ≥3.8（含 curses）、systemd 用户服务、TLS 根证书；克隆需要 Git |
| 入口 A | 自己的代理节点，或能导入的 mihomo 订阅 |
| 落地 B | 自己的代理服务：连接地址、端口、协议、认证信息；需要固定美国出口时使用对应供应商的服务 |
| 网络 | 首次能下载 GitHub 上的官方 mihomo；订阅需能从服务器直接通过 HTTPS 下载 |

YAML 订阅另需 `python3-yaml`；JSON 不需该可选包。缺少系统软件时请管理员安装；安装器不自动 sudo。Windows 原生不支持，Windows 同学可以 SSH 到 Linux 服务器操作。

共享服务器上每位同学应使用自己的 Linux 账号和节点配置。同机端口仍是共享资源：每个实例的 HTTP 和 API 端口都要独立，不能使用别人已占用的端口。

## 2. 下载源码，检查环境

```bash
git clone https://github.com/zrj-cn/ai-proxy-public.git
cd ai-proxy-public
./install.sh --check
```

HTTPS 克隆无需 GitHub 登录。`--check` 只检查环境、不安装；输出中的用户总线、端口、依赖问题仍需按提示处理，出现输出不代表全部条件通过。

## 3. 首次安装

在**没有本项目旧实例的新账号/新机器**上运行：

```bash
./install.sh
```

默认监听本机 HTTP `17890`、API `19090`。两者都需要认证，API 使用独立随机密钥；不要把它们开放到公网。若端口被占用，在首次安装时改为自己的空闲端口，例如：

```bash
./install.sh --port 17891 --api-port 19091
```

以上两种安装方式选一种即可。安装器会打开中文菜单；之后可随时运行 `~/.local/bin/ai-proxy`。退出菜单不会停止后台服务。A/B 未配齐前，AI 和其余外部流量会拒绝连接，需继续完成下一步。

**升级已有实例时请先读 [迁移与升级](migration.md)。重新安装、切换节点或应用配置可能关闭已有代理连接，不能当作零中断操作。**

## 4. 用菜单配置入口 A 和落地 B

1. 有订阅：进入“订阅管理 → 添加订阅”，填写自己的订阅名称及 HTTPS URL，再选“更新订阅”。订阅 URL 隐藏输入。也可以在“节点管理”手动添加 A。
2. 在“节点管理 → 添加节点”填写自己的 B。美国静态/家宽通常按供应商提供的 SOCKS5 或 HTTP 协议填写连接地址、端口、用户名和密码。
3. 回到主菜单，“切换入口 A”选择第一跳，“切换落地 B”选择最终出口。A、B 必须是不同节点。

上下键选择，回车确认，左键或 Esc 返回；长列表按上下键自动滚动，不需要 PgUp/PgDn。只有新增地址、密码等内容需要输入文字。

**具体填哪里、每个字段是什么意思、如何使用 JSON 模板，见 [代理配置填写位置说明](node-configuration.md)。** 示例域名不能连接；不需要修改 Python 源码或手工写链式代理规则。工具支持的协议范围见 [README](../README.md#网络路径与范围)；不支持的订阅协议会报错，请向供应商获取兼容节点。

## 5. 检测完整链路

```bash
~/.local/bin/ai-proxy test chain
~/.local/bin/ai-proxy doctor --network
```

也可从菜单“检测链路与出口”进入。完整路径应为本机 → A → B → 最终目标；检测 B 出口对照时会在隔离实例里直接连接 B，不改变生产 AI 规则。不要将 401、403、CONNECT 200 或“有流量”当作模型请求成功；还要在应用里完成自己的登录并发出实际请求。若失败，请按 [排障](troubleshooting.md) 处理，不要通过允许 AI 直连来绕过问题。

## 6. 让程序使用代理

安装代理不代表所有程序都已接入。先安装目标应用，并使用自己的账号登录，再选择需要的方式：

| 使用方式 | 操作 |
|---|---|
| Claude Code | 菜单“应用接入 → 配置 Claude Code”；重新启动应用后验证 |
| Claude Desktop SSH | 菜单“应用接入 → 配置 Claude Desktop SSH”；重连服务器会话后验证 |
| Codex | 菜单“应用接入 → 配置 Codex 专用入口”；以后用 `~/.local/bin/codex-ai` 启动新的 CLI 进程 |
| 临时给一个命令接入 | `~/.local/bin/ai-proxy run -- COMMAND [ARGS...]` |

例如只给一次 curl 请求接入：

```bash
~/.local/bin/ai-proxy run -- curl --max-time 20 https://huggingface.co/robots.txt
```

`run` 只改变新子进程的环境。配置 Claude 不会安装 Claude 或替你登录；配置 Codex 不会改变已运行的 Desktop 会话。不要复制别人的应用登录文件。

## 7. 看流量、开关服务

```bash
~/.local/bin/ai-proxy traffic  # 实时最终目标与实际通道
~/.local/bin/ai-proxy status  # 当前状态
~/.local/bin/ai-proxy on      # 启动后台服务
~/.local/bin/ai-proxy off     # 停止后台服务
```

流量面板中 Tab 切换视图，左右键筛选通道，上下键选择目标，回车查看域名详情，Q/Esc 退出。中转 A/B 的连接地址不会充当最终访问目标。统计来自采样，极短连接可能漏采；有字节不证明应用成功。

默认分流：

| 目标 | 路径 |
|---|---|
| OpenAI / ChatGPT / Codex、Anthropic / Claude | 完整 A→B；失败即失败 |
| 没有匹配规则的外部目标 | 完整 A→B；失败即失败 |
| 已列出的 GitHub、Hugging Face、pip/PyPI、PyTorch、NVIDIA CUDA 下载域名 | DIRECT 直连 |
| 明确添加到“代理优先，可回退”的非 AI 域名 | 完整 A→B 优先；健康检查失败后新连接可直连 |

规则就在仓库 [rules/](../rules/)，包括 GPT 与 Claude 域名；完整优先级和边界见 [分流规则](routing-policy.md)。停止服务会使已经接入它的程序暂时不可用，包含其 DIRECT 下载；未接入的普通程序维持原网络。

## 8. 退出 SSH 后继续运行

```bash
loginctl show-user "$USER" -p Linger
```

需要 `Linger=yes` 才具备退出登录/开机运行的必要条件。没有开启时请管理员按 [迁移文档](migration.md) 为你的账号设置；不要重启共享服务器来测试。完整验收清单见 [新机器验收](deployment-validation.md)。

真实节点和订阅保存在你自己的 `~/.config/ai-proxy/`，不会通过克隆源码获得。提交 Issue 或给同学发文件前，先看 [隐私与分享](privacy.md)。
