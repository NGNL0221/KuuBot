# KuuBot

🖥️ QQ 渠道的 AI 桌面助手 —— 手机 QQ 发消息，电脑自动执行任务。

## ✨ 功能

| 类别 | 能力 |
|------|------|
| 💬 聊天 | DeepSeek 驱动的 AI 对话，支持 Function Calling |
| 📁 文件操作 | 读写、编辑、创建、删除、复制、压缩、解压 |
| 🔍 搜索 | 文件名搜索、内容搜索、Web 搜索 |
| 📄 文档 | 创建 Word 文档、全屏截图 |
| ⏰ 自动提醒 | `/remind` 定时提醒、每日早安/晚安 |
| 💤 休眠提醒 | 深夜自动提醒该睡觉了，说"晚安"自动闭嘴 |
| 💡 随机搭话 | 白天每 30-60 分钟主动搭话 |
| 🗨️ 多会话 | `/new` `/switch` `/rename` `/delete` 会话管理 |
| 🎮 闲聊模式 | `/casual` 真人聊天——短句、分条发、模拟打字 |

## 🚀 快速开始

### 1. 准备环境

```bash
pip install websocket-client requests python-docx Pillow
```

### 2. 创建 QQ Bot

1. 打开 [q.qq.com](https://q.qq.com) → 创建机器人
2. 获取 **AppID** 和 **AppSecret**

### 3. 获取 DeepSeek Key

1. 打开 [platform.deepseek.com](https://platform.deepseek.com)
2. 创建 API Key

### 4. 配置

```bash
cp config.example.json kuu_bot/config.json
```

编辑 `kuu_bot/config.json`：

| 字段 | 说明 |
|------|------|
| `qq_app_id` | QQ Bot 的 AppID |
| `qq_app_secret` | QQ Bot 的 AppSecret |
| `deepseek_api_key` | DeepSeek API Key |
| `admin_openid` | **先留空**，首次启动后 Bot 会告诉你 |

### 5. 首次运行

1. 双击 `KuuBot.pyw` 启动 Bot
2. 手机 QQ 扫码加好友
3. 发任意消息 → Bot 回复你的 OpenID
4. 将 OpenID 填入 `config.json` 的 `admin_openid` → 重启 Bot
5. Bot 已锁定，只有你能使用

### 6. 日常启动

```bash
# 桌面托盘模式（静默运行）
pythonw KuuBot.pyw

# 控制台模式（可看日志）
python KuuBot.pyw
```

## ⚠️ 重要安全警告

> **本 Bot 可以通过 QQ 远程操控你的电脑文件系统和执行终端命令。**
>
> 请务必做到：
> - **不要让陌生人添加 Bot 为好友**
> - 在 `config.json` 中配置 `admin_openid` 为你的 QQ OpenID，Bot 将只响应你的消息
> - 谨慎使用管理员权限启动（可写入系统关键目录）
> - Bot 默认只响应私聊，不处理群聊消息
>
> 🔴 **这不是开玩笑。错误配置可能导致文件被他人删除或修改。**

## ⌨️ 指令列表

| 命令 | 效果 |
|------|------|
| `/help` | 显示指令列表 |
| `/casual` | 真人闲聊模式 |
| `/formal` | 恢复正常模式 |
| `/new` | 创建新会话 |
| `/list` | 列出所有会话 |
| `/switch <编号\|名称>` | 切换会话 |
| `/rename <新名称>` | 重命名 |
| `/delete <编号\|名称\|all>` | 删除 |
| `/remind <时间> <内容>` | 设置提醒 |
| `/reminders` | 查看提醒 |
| `/cancel <编号\|all>` | 取消提醒 |

## ⚙️ 自定义人设

编辑 `kuu_bot/persona.txt` 即可更改 AI 的性格和说话风格。仓库自带 `persona_public.txt` 作为示例模板。

## 📁 项目结构

```
KuuBot/
├── KuuBot.pyw              ← 启动入口
├── config.example.json     ← 配置模板
├── kuu_bot/
│   ├── __main__.py         ← 主路由 / 命令 / cron 调度
│   ├── agent.py            ← DeepSeek API / Function Calling
│   ├── tools.py            ← 12 个文件&系统工具
│   ├── qq_bot.py           ← QQ WebSocket 连接
│   ├── cron.py             ← 早安/晚安/搭话
│   ├── session.py          ← 会话存储
│   ├── tray.py             ← 托盘图标
│   └── persona_public.txt  ← 公开人设模板
├── .gitignore
├── LICENSE
└── README.md
```

## 📋 依赖

| 库 | 用途 |
|------|------|
| `websocket-client` | QQ Bot WebSocket 连接 |
| `requests` | DeepSeek API + HTTP |
| `python-docx` | Word 文档读写 |
| `Pillow` | 截图 |

## 📄 License

MIT
