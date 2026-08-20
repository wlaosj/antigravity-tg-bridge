# Antigravity TG Bridge 自动化构建与工作流规则

## 核心工作流规范（修改代码后强制执行）
在针对本项目的任何代码修改、功能新增或 Bug 修复完成后，Agent **必须无条件自动执行**以下全闭环操作：

1. **自动重新编译打包与平滑重启**：
   - 自动执行 `/Users/dv/Desktop/test/tg_bridge/build_app.sh --restart`；
   - 确保桌面应用 `/Users/dv/Desktop/Antigravity TG Bridge.app` 与 `/Applications/Antigravity TG Bridge.app` 更新为最新版本；
   - 确保后台守护服务（`bridge_engine.py`）以独立会话（PPID=1）持续存活，且桌面控制面板自动在 Mac 屏幕上重启就绪。

2. **代码安全性与隐私防护**：
   - 严禁将包含真实私有 Telegram Token 的 `config.json` 提交到公开仓库，必须始终保持在 `.gitignore` 中被严格隔离；
   - 保持 `config.example.json` 为干净的安全配置模板。

3. **云端 Git 自动同步与中文提交日志规范**：
   - 代码变动后，自动执行 `git add .`、`git commit -m "..."` 并推送到 GitHub 远程仓库（`git push origin main`）；
   - **Git 提交日志（Commit Message）必须一律使用清晰优雅的中文**（例如：`修复: 优化消息流式回传过滤机制`、`功能: 新增应用一键平滑重启选项`）。

4. **纯净 Telegram 回复规范**：
   - 严禁将终端调试日志（如 `Created At:`、`The command exited...`、`Task id...`）回传给 Telegram 用户，只允许展示真正的人类友好中文回复。

5. **大模型原生生图准则**：
   - 当用户要求“画图 / 生图 / 生成图片 / 绘制架构图”时，必须**默认直接调用 Agent 大模型视觉生图工具（`generate_image`）**生成顶级 AI 画面，严禁使用简陋 Python 脚本画图，并将渲染出的高清原图直接发送给 Telegram 用户。
