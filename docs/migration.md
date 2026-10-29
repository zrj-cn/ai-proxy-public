# 新服务器迁移

1. 新机器准备自己的账号、代理节点及应用登录，先阅读 [新手部署](quickstart.md)。公开仓库通过 HTTPS 克隆；若使用私有副本，需要由仓库所有者授权，可使用仅此仓库的只读 deploy key。私钥留在新机器，不复制个人长期 token。
2. 克隆并检查环境；共享服务器先确认两个监听端口都未被其他实例占用：

```bash
git clone https://github.com/zrj-cn/ai-proxy-public.git
cd ai-proxy
./install.sh --check
./install.sh
```

3. 首次安装通过菜单输入缺失 A/B 或从受限文件导入：

```bash
chmod 600 /安全路径/nodes.json
./install.sh --non-interactive --nodes-file /安全路径/nodes.json --entry my-A --exit my-B --configure-claude
~/.local/bin/ai-proxy app configure codex
```

节点模板为仓库 [`templates/nodes.example.json`](../templates/nodes.example.json)，具体字段见 [配置填写位置](node-configuration.md)，示例不能运行。API/入口随机认证每台机器单独生成。不要把真实模板提交回仓库。

4. 可先从旧机器 `ai-proxy backup export /安全路径/public.tar`，安全传输后在新机器 `ai-proxy backup import /安全路径/public.tar`。该包只含规则/开关，**不含节点、订阅、密码、应用登录**。工具不自动导出秘密；秘密另行安全提供，应用在新机器按正常流程登录。
5. 核实端口与用户服务，检查 Linger。缺失时请管理员执行 `loginctl enable-linger 新机器用户名`。不修改整机 DNS、路由或其他账号。不同用户名/路径/架构由安装器重新检测，规则包不覆盖机器端口。
6. `ai-proxy doctor --network`、`exit-ip`、`negative-test`、`app-test codex` / `app-test claude`。Desktop SSH 需要新建/重连对应服务器会话，检查实际 helper 环境。机器重启验证需另约维护窗口，不从启用状态推断。

## 已有实例升级

重新运行安装器会应用配置并可能关闭已有代理连接，**不保证零中断**。先安排维护窗口，停止依赖长连接的任务或准备重连；要求连接持续可用时不要直接重装、重启或重载。

源代码升级：先在克隆仓库 `git pull --ff-only`，审查后重跑 `./install.sh --non-interactive`；内置规则从新的程序副本读取，自定义规则和秘密不在仓库。程序上一副本保存为 `~/.local/share/ai-proxy/app.previous`，若源代码安装中断，可用该副本的 `ai-proxy` 重新安装；核心版本用 `update` / `rollback version`。上线前跑自动测试。默认安装固定版本，不会因重新安装自动降级已升级核心。
