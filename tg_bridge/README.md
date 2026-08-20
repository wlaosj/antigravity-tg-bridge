# 🛸 Antigravity Telegram Native Bridge (macOS App)

> **零中转·零第三方·直连 Mac 本地 Google Antigravity IDE**

---

## 🌟 核心特性

- **纯图形化桌面应用**：双击桌面图标即可打开暗黑科技风控制中心，进行可视化偏好设置与运行监控。
- **动态语言服务器探测**：自动识别 Antigravity IDE 重启后分配的动态端口（`ANTIGRAVITY_LS_ADDRESS`），彻底解决断连与超时。
- **多模态图片/截图支持**：手机发送报错截图或设计图，自动调用 IDE 视觉多模态能力进行排查与看图写代码。
- **打字机流式输出**：实时在 Telegram 中查看代码生成进度与工具调用详情。
- **手机端原生弹窗**：点击快捷按钮直接在手机屏幕正中央弹出工作区路径与 Git Diff 摘要。

---

## 📂 项目结构

```
tg_bridge/
├── app.py                 # 🚀 macOS 桌面 GUI 主程序（看板 + 图形化设置 + 实时日志）
├── bridge_engine.py       # ⚡️ 核心通信引擎（Telegram ↔ Antigravity IDE）
├── config.json            # ⚙️ 配置文件（Token、代理、工作区、用户白名单）
├── AppIcon.icns           # 🎨 高清 App 图标
├── build_app.sh           # 🔨 一键打包生成 Antigravity TG Bridge.app
├── downloads/             # 🖼 手机上传的截图暂存目录
└── README.md              # 📖 项目文档
```

---

## 🚀 使用指南

### 1. 运行与管理
- **直接双击桌面上的应用**：`/Users/dv/Desktop/Antigravity TG Bridge.app`
- 即可打开可视化控制中心，随时查看服务状态、实时日志、切换项目工作区或启动/停止服务。

### 2. 图形化设置
- 在 App 的 **【⚙️ 图形化设置】** 标签页中：
  - 修改 Telegram Bot Token
  - 设置授权用户 ID 白名单
  - 配置代理网络（支持直连或本地代理）
  - 勾选任务偏好（自动拉起 IDE、回传 Git Diff 等）
  - 点击 **【💾 保存并应用配置】** 立即生效！

### 3. 手机 Telegram 常用指令
- `/pwd` - 弹窗查看当前工作区路径与 Git 分支
- `/pin` - 发送并置顶当前工作区状态看板
- `/diff` - 查看未提交代码变动
- `/commit <msg>` - 自动提交代码到 Git
- `/open` - 在 Mac 电脑上唤起 Antigravity IDE 窗口
- `/workspace <path>` - 切换工作区路径
- `/run <command>` - 在工作区执行终端 Shell 命令
- **直接发文字/图片** - 调度 Agent 编写代码与修复 Bug
