#!/bin/bash
# ==============================================================================
# 构建原生 macOS 桌面应用程序 (Antigravity TG Bridge.app)
# ==============================================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_NAME="Antigravity TG Bridge"
DESKTOP_APP="$HOME/Desktop/$APP_NAME.app"
APPLICATIONS_APP="/Applications/$APP_NAME.app"

echo "🔨 正在构建原生 macOS 桌面应用程序: $APP_NAME.app..."

# 1. 清理旧 App
rm -rf "$DESKTOP_APP" "$APPLICATIONS_APP"

# 2. 创建 App Bundle 目录结构
mkdir -p "$DESKTOP_APP/Contents/MacOS"
mkdir -p "$DESKTOP_APP/Contents/Resources"

# 3. 复制高清图标
if [ -f "$DIR/AppIcon.icns" ]; then
    cp "$DIR/AppIcon.icns" "$DESKTOP_APP/Contents/Resources/AppIcon.icns"
fi

# 4. 生成 Info.plist
cat <<EOF > "$DESKTOP_APP/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>com.antigravity.tgbridge.app</string>
    <key>CFBundleVersion</key>
    <string>2.0.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# 5. 生成启动器脚本
cat <<'EOF' > "$DESKTOP_APP/Contents/MacOS/launcher"
#!/bin/bash
DIR="/Users/dv/Desktop/test/tg_bridge"
VENV_PYTHON="$DIR/.venv/bin/python"
ENGINE_PY="$DIR/bridge_engine.py"
APP_PY="$DIR/app.py"
LOG_FILE="$DIR/bridge.log"

# 自动确保后台守护服务已启动 (完全独立后台运行)
if ! pgrep -f "bridge_engine.py" > /dev/null 2>&1; then
    PYTHONUNBUFFERED=1 nohup "$VENV_PYTHON" "$ENGINE_PY" >> "$LOG_FILE" 2>&1 < /dev/null &
    disown
fi

export PYTHONUNBUFFERED=1
exec "$VENV_PYTHON" "$APP_PY"
EOF

chmod +x "$DESKTOP_APP/Contents/MacOS/launcher"
chmod +x "$DIR/app.py"
chmod +x "$DIR/bridge_engine.py"

# 6. 同时复制一份到 /Applications (应用程序目录)
cp -R "$DESKTOP_APP" "/Applications/"
xattr -cr "$DESKTOP_APP" "$APPLICATIONS_APP" 2>/dev/null || true

echo "================================================================="
echo "🎉 成功打包生成原生 macOS 桌面应用程序！"
echo "================================================================="
echo "📍 桌面图标: $DESKTOP_APP"
echo "📍 应用程序目录: $APPLICATIONS_APP"
echo "💡 双击运行即可打开暗黑科技风【控制看板】与【图形化设置】！"
echo "================================================================="

# 7. 如果传入了 --restart 或 -r 参数，自动平滑重启后台引擎与桌面应用
if [ "$1" == "--restart" ] || [ "$1" == "-r" ] || [ "$1" == "restart" ]; then
    echo "🔄 正在自动重启后台引擎与桌面控制面板..."
    pkill -f "bridge_engine.py" 2>/dev/null || true
    pkill -f "app.py" 2>/dev/null || true
    sleep 0.5
    open "$DESKTOP_APP"
    echo "✨ 桌面控制面板与后台引擎已全自动重启就绪！"
fi
