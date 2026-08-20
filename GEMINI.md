# Antigravity TG Bridge 项目规则与行为指引

## 自动化闭环准则（每次修改代码后必须触发）
1. **自动编译与重启**：执行 `/Users/dv/Desktop/test/tg_bridge/build_app.sh --restart`，打包最新 App 并拉起守护进程与 GUI 控制台。
2. **隐私隔离**：`config.json` 永不上云，使用 `config.example.json` 保持公开仓库安全。
3. **云端同步与中文日志**：自动 `git add`、`commit` 并 `push` 到 GitHub，**所有提交信息（Commit Message）必须一律使用清晰中文**。
4. **输出规范**：严禁向 Telegram 转发内部命令行日志，始终提供优雅纯净的中文回复。
5. **大模型原生画图准则**：当用户提出“画图 / 生图 / 生成图片 / 制作架构图 / 视觉图”等需求时，**必须默认直接调用 Agent 大模型原生视觉算力（`generate_image` 工具）生成高精度 AI 图像**，严禁使用简陋的 Python 脚本绘图，并在生成后将高清原图直传给 Telegram。
