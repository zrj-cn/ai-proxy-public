# 隐私与分享

本仓库分享程序、通用规则、无效地址模板与使用说明。真实代理和运行数据保存在每个人自己的账号下；源码仓库公开不会自动共享服务器上的代理服务。

## 可以提交什么

- 源码、测试、通用分流规则和文档。
- 使用 `.invalid` 示例域名及 `YOUR_...` 占位文字的模板。
- 经人工审查、去除个人域名和业务信息的自定义规则。

## 不要提交什么

- 节点真实连接地址、端口组合、用户名、密码、UUID、订阅 URL/token，以及真实美国静态/家宽出口 IP。
- 原服务器的主机名、公网 IP、账号、个人绝对路径、SSH 密钥、应用登录和内部业务域名。
- `~/.config/ai-proxy/`、`~/.local/state/ai-proxy/`、私有备份、原始日志或配置截图。
- 填好真实信息的节点模板。请在仓库外创建 600 文件，再从菜单导入。

`.gitignore` 只降低误提交概率，已经被跟踪的文件仍会进入提交。`backup export` 排除节点与认证，但自定义规则的域名也可能敏感，分享前仍需检查。流量面板会显示最终目标，截图同样需要审查。

## 提交前检查

```bash
git status --short
# 只添加自己逐项检查过的源码或文档，不把整个 HOME 加进仓库
git diff --cached --stat
git diff --cached --check
python3 scripts/audit_staged.py
```

脚本检查 Git 索引中的文本、当前本地配置中的已知秘密和部分凭证格式；不输出匹配值。它不等于历史扫描，无法识别所有未知秘密。人工检查文件内容和改动范围仍是必要步骤。

提交 Issue 请提供系统/工具版本、复现步骤和脱敏错误文字；不要上传原始 `nodes.json`、`runtime.json`、订阅或认证截图。不要在公开 Issue 中报告秘密本身。

## 将私有项目公开之前

应检查所有分支、标签、历史提交，以及 PR/Issue、Releases、Actions 日志与附件。只删除最新版文件不会清除旧提交。历史包含个人信息时，可以选择用审查过的快照建立全新仓库，或协调历史清理、旧引用与缓存；不要直接将旧仓库改为 public。

若实际凭证曾泄露，先在供应商处撤销/更换，再处理历史。修改历史会影响现有克隆，需要协调协作者。GitHub 的说明见 [删除敏感数据](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)；公开仓库会公开相关 Actions 历史，见 [更改可见性](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility)。
