# 代理配置填写位置说明

[返回新手部署步骤](quickstart.md) · [查看节点模板](../templates/nodes.example.json)

## 推荐：用菜单填写

第一次安装后运行 `~/.local/bin/ai-proxy`。

1. 入口A：在“订阅管理”添加你自己的订阅并更新，或者在“节点管理”新增入口节点；在“切换入口A”中选中它。
2. 美国静态/家宽落地B：在“节点管理”新增节点，协议选择供应商提供的SOCKS5或HTTP，填写供应商给出的连接地址、端口、用户名、密码；在“切换落地B”中选中它。
3. 用“检测链路与出口”核实完整A→B与B独立出口，再做目标应用的实际请求。

## 也可以填写JSON文件

模板为 [`templates/nodes.example.json`](../templates/nodes.example.json)。它只有无效示例地址和占位文字，必须替换成自己的信息。在源码目录下执行，将副本放到仓库外；如果这个目标文件已存在，请换一个新文件名，避免覆盖：

```bash
install -m 600 templates/nodes.example.json ~/ai-proxy-nodes.json
```

用自己熟悉的编辑器修改 `~/ai-proxy-nodes.json`；只改副本，JSON 不能带注释。模板示例如下：

```json
{
  "nodes": {
    "entry-A": {
      "type": "trojan",
      "server": "entry.example.invalid",
      "port": 443,
      "password": "YOUR_ENTRY_PASSWORD",
      "sni": "entry.example.invalid",
      "skip-cert-verify": false
    },
    "exit-B": {
      "type": "socks5",
      "server": "exit.example.invalid",
      "port": 1080,
      "username": "YOUR_EXIT_USERNAME",
      "password": "YOUR_EXIT_PASSWORD"
    }
  }
}
```

字段对应关系：

| 字段 | 填写内容 |
|---|---|
| nodes.entry-A.type | 第一跳协议，模板以trojan为例；有订阅时也可直接在菜单导入并选择入口 |
| nodes.entry-A.server | 你自己的入口代理主机名或IP |
| nodes.entry-A.port | 你自己的入口代理端口 |
| nodes.entry-A.password | 你自己的入口代理密码 |
| nodes.entry-A.sni | 入口供应商指定的TLS SNI；不能照抄别人的SNI |
| nodes.entry-A.skip-cert-verify | 默认false，验证证书；保留证书校验；不要照搬他人的跳过校验设置 |
| nodes.exit-B.type | 美国静态/家宽代理协议，模板以socks5为例；供应商提供HTTP时改为http |
| nodes.exit-B.server | 供应商提供的B代理连接地址，不是仅用于展示的最终出口IP |
| nodes.exit-B.port | B代理连接端口 |
| nodes.exit-B.username | B代理认证用户名；如果服务明确无需该字段则删除它 |
| nodes.exit-B.password | B代理认证密码；如果服务明确无需该字段则删除它 |

“美国家宽”不是mihomo协议类型：它是你购买的B代理服务的线路/出口属性。B仍按SOCKS5或HTTP等实际协议填写。供应商的连接主机名可能与目标网站看到的最终出口IP不同。如果只有一个美国IP，没有可用的代理服务、端口及认证方式，不能直接把这个IP填进去就实现链式代理。

填写完成后，**在新机器首次安装时**可以运行：

```bash
./install.sh --check
./install.sh --non-interactive --nodes-file ~/ai-proxy-nodes.json --entry entry-A --exit exit-B
~/.local/bin/ai-proxy test chain
~/.local/bin/ai-proxy traffic
```

也可以通过菜单“节点管理 → 从本地文件导入节点”导入这个600文件，再分别选择入口A和落地B。不同协议需要的字段不同，请使用对应协议模板/供应商配置；不要把Trojan字段原样用于其他协议。

工具会把节点安全保存到当前账号的 `~/.config/ai-proxy/nodes.json`，订阅保存在 `~/.config/ai-proxy/subscriptions.json`，选择保存在 `~/.config/ai-proxy/settings.json`。无需修改Python源码；无需手工编辑生成的 `~/.local/state/ai-proxy/runtime.json`。代理/API 随机认证另存于 `~/.config/ai-proxy/credentials.json`，每台机器独立生成。上述真实文件、运行状态和备份都不要提交到 GitHub 或打包转发。

规则位于项目 `rules/`；日常修改优先使用菜单“分流规则”。完整链路由工具生成：EXIT_B设置dialer-proxy为ENTRY_A，目标选择B。无需在共享模板中预填任何人的实际出口IP。


## 自己的订阅填在哪里

运行 `~/.local/bin/ai-proxy`，进入“订阅管理 → 添加订阅”，名称自己取，URL 使用供应商给你的 HTTPS 订阅地址；然后选择“更新订阅”。已有订阅用“修改订阅 URL”，不要将 URL 写进 README、源码或命令行参数。

“从本地文件导入 URL”要求该文件只有一行订阅 URL、属于当前用户、不是符号链接且权限为 600。不要把其他说明或 B 的信息混在这个文件里。

## 分流规则填在哪里

优先使用菜单“分流规则”。新增加的个人域名规则写在自己的 `~/.config/ai-proxy/custom-rules.json`；仓库 `rules/ai.json`、`rules/direct.json` 提供通用 AI 与下载规则，`rules/custom.example.json` 只作示例。GPT/Claude 已有默认完整代理规则，无需填写个人 IP 来启用。更多见 [规则说明](routing-policy.md)。

向别人分享时保留原样的无效地址/占位密码模板，让对方填自己的信息。只有供应商明确提供的代理服务才能作为 B；供应商所在地或美国 IP 本身不保证 Claude/GPT 的账号及应用访问成功。
