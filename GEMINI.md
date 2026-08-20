# Antigravity TG Bridge 项目规则与行为指引

## 自动化闭环准则（每次修改代码后必须触发）
1. **自动编译与重启**：执行 `/Users/dv/Desktop/test/tg_bridge/build_app.sh --restart`，打包最新 App 并拉起守护进程与 GUI 控制台。
2. **隐私隔离**：`config.json` 永不上云，使用 `config.example.json` 保持公开仓库安全。
3. **云端同步**：自动 `git add`、`commit` 并 `push` 到 GitHub。
4. **输出规范**：严禁向 Telegram 转发内部命令行日志，始终提供优雅纯净的中文回复。
