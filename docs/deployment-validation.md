# 新机器验收清单

每台机器都需要使用自己的节点验收，不能沿用其他部署的地区、连通性或应用成功结论。先完成 [新手部署](quickstart.md) 和 [节点配置](node-configuration.md)。

| 检查 | 方法与通过条件 |
|---|---|
| 环境 | `./install.sh --check`；确认依赖、用户总线、空闲端口，检查提示中的未满足条件 |
| 节点与监听 | `ai-proxy status`；A、B 为不同节点，HTTP/API 仅本机监听，均有认证 |
| 完整链路 | `ai-proxy test chain`；核实 A→B 和 B 出口对照，不单凭地区或一个出口 IP 判定 |
| 规则 | `ai-proxy rule explain claude.ai`、`ai-proxy rule explain api.openai.com` 为 CHAIN；`ai-proxy rule explain pypi.org` 为 DIRECT |
| 网络诊断 | `ai-proxy doctor --network`；逐项处理失败/未验证，不把未验证当作通过 |
| 断路边界 | `ai-proxy negative-test` 使用隔离实例验证任意一跳失败时无回退；不改变生产实例 |
| 实际应用 | 在自己的应用中登录并发出最小实际请求；`app-test` 可能产生少量费用，按应用需要选择 |
| 实际通道 | `ai-proxy traffic` 观察最终域名与通道；短连接可能漏采，不能只看连接数/字节判断应用成功 |
| 常驻 | 检查用户服务和 `Linger=yes`；在自己的维护窗口验证退出 SSH 后运行，重启共享机器需另行安排 |

`test B` 会明确直接连接 B，只用于隔离诊断；生产 AI 仍走完整 A→B。401/403、CONNECT 200、地区为美国均不证明 AI 应用可用。检测失败时见 [排障](troubleshooting.md)，不要将强制代理改为直连来“通过”检查。

## 修改源码后的检查

```bash
python3 -m unittest discover -s tests -v
python3 scripts/audit_staged.py
```

隐私脚本检查 Git 索引中的文件，提交前需先 `git add` 自己审查过的源码/文档。它能识别当前本地配置中的已知秘密及部分凭证格式，不能替代人工检查，也不扫描历史提交。

`tests/integration.py` 和 `tests/traffic_integration.py` 使用已下载的官方 mihomo、独立实例与本地模拟目标，适合验证程序机制，不能替代真实节点验收。`tests/acceptance_live.py --live` 会操作实际服务，**不要在承载连接的实例上随意运行**。

记录验收结果时仅分享必要的脱敏结论；不要把节点地址、出口 IP、服务器信息、订阅、密码或应用登录放进仓库。
