# host-shipRenew 自动续期脚本

### 1.⭐ **觉得有用？给个 Star 支持一下！**
> 注册地址：[https://panel.host-ship.com/auth/login]

### 2. 配置 Telegram 通知（可选）

进入仓库 `Settings` → `Secrets and variables` → `Actions`，添加以下 Secrets：

| Secret 名称 | 必填 | 说明 | 示例 |
|------------|------|------|------|
| `TG_BOT_TOKEN` | ❌ | Telegram Bot Token | `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
| `TG_CHAT_ID` | ❌ | 接收消息的 Chat ID | `123456789` |
| HOSTSHIP_USERNAME | ✅ | 登录账号
| HOSTSHIP_PASSWORD | ✅ | 登录密码
| PROXY_SERVER | ❌ | 代理

> 不配置这两个 Secret 时，脚本仍会正常运行，只是不会发送 Telegram 通知。

**获取方式：**
- **Bot Token**：向 [@BotFather](https://t.me/BotFather) 发送 `/newbot` 创建机器人，获得 token。
- **Chat ID**：向 [@userinfobot](https://t.me/userinfobot) 发送任意消息即可获取。


###3. 使用方法

### 方法 1：定时自动运行（默认）

Fork 本仓库并完成上述配置后，工作流会按以下时间自动执行（UTC 时间）：

- `0 0,11,22 * * *`  → 每天 00:00、11:00、22:00（UTC）
- `30 5,16 * * *`  → 每天 05:30、16:30（UTC）

如需修改频率，编辑 `.github/workflows/Host2Play_Renew.yml` 中的 `schedule` 部分即可。

常用 cron 示例：
- `0 */6 * * *`  每 6 小时一次
- `0 0,12 * * *` 每天 0 点和 12 点（UTC）

### 方法 2：手动触发（GitHub 网页）

1. 进入仓库的 `Actions` 页面
2. 选择 **Host2Play 续期** 工作流
3. 点击 **Run workflow** → 点击绿色的 **Run workflow** 按钮

### 方法 3：API 调用

```bash
curl -X POST \
  -H "Authorization: Bearer ghp_你的Token" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/你的用户名/你的仓库名/actions/workflows/Host2Play_Renew.yml/dispatches \
  -d '{"ref":"main"}'
```


## 📄 许可证

MIT License

---

**⚠️ 免责声明**：本脚本仅供学习交流使用，使用者需遵守 Host2Play 的服务条款。因使用本脚本造成的任何问题，作者不承担任何责任。
