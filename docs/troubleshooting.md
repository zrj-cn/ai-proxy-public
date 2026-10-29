# 排障和恢复

- `ai-proxy doctor` 显示配置/服务/认证/监听/权限/Linger；`doctor --network` 增加每跳限量的实际下载与链路观察。`service logs` 仅输出脱敏生命周期，mihomo 原始日志禁用，不把节点、密码、签名下载 URL 或应用输出写入普通日志。
- 显示 `未配置真实 A/B`：不是部署成功，AI 默认 REJECT。`node add A`、`node add B` 后 `node select entry A`、`node select exit B`，再用 `test A` / `test B` / `test chain` / `exit-ip`。如果 `test B` 正常而链路异常，检查 A 能否拨号 B、B 协议兼容及上游认证，不能简单移除 dialer-proxy 使其单跳运行。
- 订阅更新拒绝改变已选节点：为保持出口稳定保留原配置。先保存新节点为不同 ID，测试后显式切换；选中节点删除/凭证改变不会自动生效。订阅只支持列出的简单 TCP 节点，支持 base64 简单 TCP URI 集，不支持未知复杂字段。
- `Linger=no`：最后登录退出后用户管理器可能停止、重启前未登录可能不启动。管理员最小操作 `loginctl enable-linger 用户名`；工具不自动提升权限。即使 yes 也不是断开 SSH/重启的真实测试。本方案服务器独立运行，不依赖电脑隧道。
- 用户总线不可用：确认真实服务器登录会话有 `/run/user/UID/bus`，在 SSH 用户会话中检查 `systemctl --user status`，不要用 root 运行安装器。无 systemd 的平台，本实现明确不完成常驻。若已有普通用户 runit/supervisord，可让它监管 `~/.local/share/ai-proxy/mihomo -d ~/.local/state/ai-proxy -f ~/.local/state/ai-proxy/runtime.json`（参数均为路径，不含秘密），且由管理员保证 supervisor 在退出登录和重启时工作；CLI 的 systemd 服务操作不能用于此兼容方案，需改用该 supervisor 命令。没有常驻管理器时仅能前台调试，tmux/nohup 不能保证重启恢复。
- 认证 407：不要关闭认证或加入 skip-auth-prefixes。`app check` 检查持久设置。`app configure claude` 正确合并；`run -- COMMAND` 正确设置新进程环境，无需把密码粘入 shell。只有回环监听仍是整机共享端口，必须保留认证。
- Claude Desktop SSH 卡住：已有 helper 环境可覆盖 settings。`app check` 仅显示本账号进程和冲突变量名；请在没有活动任务时重连会话，必要时自行结束旧 helper。工具不终止现有应用进程；未完成实际会话验证前，不应将 Desktop 标记为已通过。共享服务/MCP 的非 HTTP 客户端需要单独验证，不承诺全覆盖。
- 已有 shell 代理：本工具不改全局环境。使用 `ai-proxy run`/`codex-ai` 对新进程覆盖大/小写代理及 NO_PROXY；它不能修改父 shell。Claude 用户设置会被进程环境或更高优先级 managed/project 设置覆盖，需核实真实会话。不要打印完整 env/应用设置/登录文件。
- 负向测试：默认全部使用隔离临时实例，不停止生产实例。A/B 不可用时 CONNECT/TLS 失败可以证明此链路没有该请求的自动回退；真实应用仍需独立测试，不把任意 403 当做成功。
- 下载重定向有新域名：`probe` 对每次真实 GET 显示脱敏主机与状态及能采集到的核心路由。先核实具体主机确属下载，再新增精确 DOMAIN。快速短连接可能采不到路由，显示未验证。不得直接扩大为整个共享云服务 DIRECT。
- 失败重载：事务保留旧输入/运行配置，验证失败不调用 API；API 失败恢复旧文件并尝试重载，必要时重启用户服务。`rollback config` 将上一输入重新生成验证；备份在私有状态目录。若核心根本不能启动，先 `rollback version` 或用已校验的旧核心启动，再校验配置。任何恢复失败都需 doctor 处理，不能宣称成功。
- 版本更新：官方发布 digest 不存在、校验不符、核心自检或重启失败，保留/恢复当前版本。`update vX.Y.Z` 不自动追踪 latest。完整 core 接口的版本差异仍需重新验收。源码更新与核心更新是两件事。

## 恢复与卸载

```bash
ai-proxy rollback config
ai-proxy rollback version
ai-proxy uninstall --yes
```

卸载停止服务并移除 unit/命令入口；保留 `~/.config/ai-proxy`、`~/.local/share/ai-proxy`、`~/.local/state/ai-proxy` 作为恢复资料。应用代理设置保留以免 AI 意外直连。若想恢复到代理接入前的 Claude，先安全备份当前设置，再用 `~/.local/state/ai-proxy/backups/claude-settings.original` 对照合并代理键，**不要整份覆盖后来新加的设置**。不存在原文件时只删除本工具添加的 env 代理键；这是有意允许应用重新使用原网络的操作，应明确决定后再做。Codex 直接运行原 `codex` 即回到其既有配置，是否代理仍取决于原环境。

确认不再需要后，手动只删除本项目的这三个目录；不要误删 `~/.claude`、`~/.codex`、`~/.config/systemd/user` 或其他用户文件。若曾为本项目专门打开 lingering，关闭前确认本账号其他用户服务是否也需要它。

## 方向键界面

直接在交互 SSH 终端运行 `ai-proxy`；不要把无参数命令放进管道。终端至少42列×10行，`TERM` 应匹配实际终端，常见为 xterm-256color。↑↓选择、→/Enter确认、←/Esc返回，长列表PgUp/PgDn翻页。小终端可放大后继续，Ctrl+C退出会恢复终端，不停止后台服务。Python缺少curses时需使用带curses的系统Python，CLI照常可用；不自动安装复杂UI依赖。
