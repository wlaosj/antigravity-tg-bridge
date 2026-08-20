#!/usr/bin/env python3
"""
Antigravity Telegram Bridge - macOS 桌面控制中心与图形化设置应用
================================================================
纯原生现代质感 UI，解决 macOS 系统默认按钮发白发虚问题，提供极致对比度与实时日志流滚动。
"""

import os
import sys
import subprocess
import threading
import time
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

DIR = Path(__file__).resolve().parent
LOG_FILE = DIR / "bridge.log"
CONFIG_FILE = DIR / "config.json"
PID_FILE = DIR / "bridge.pid"
VENV_PYTHON = DIR / ".venv" / "bin" / "python"
ENGINE_PY = DIR / "bridge_engine.py"


# ==============================================================================
# 配置与服务管理工具
# ==============================================================================
def load_config() -> dict:
    default_cfg = {
        "telegram_token": "",
        "allowed_user_ids": [],
        "default_workspace": str(Path.home() / "Desktop" / "test"),
        "proxy": "",
        "auto_open_ide": True,
        "send_diff_after_task": True,
        "stream_updates": True,
    }
    if not CONFIG_FILE.exists():
        save_config(default_cfg)
        return default_cfg
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            for k, v in default_cfg.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception:
        return default_cfg


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"❌ 保存配置失败: {e}")


def is_service_running() -> bool:
    """检查后台 bridge_engine 是否运行中"""
    try:
        res = subprocess.run(["pgrep", "-f", "bridge_engine.py"], capture_output=True, text=True)
        pids = [p.strip() for p in res.stdout.splitlines() if p.strip()]
        my_pid = str(os.getpid())
        pids = [p for p in pids if p != my_pid]
        return len(pids) > 0
    except Exception:
        return False


def get_service_pid() -> str:
    """获取后台服务 PID"""
    try:
        res = subprocess.run(["pgrep", "-f", "bridge_engine.py"], capture_output=True, text=True)
        pids = [p.strip() for p in res.stdout.splitlines() if p.strip()]
        my_pid = str(os.getpid())
        pids = [p for p in pids if p != my_pid]
        return pids[0] if pids else ""
    except Exception:
        return ""


def start_service():
    """启动后台守护服务 (macOS 兼容的独立会话创建，PPID 脱离)"""
    if is_service_running():
        return
    cfg = load_config()
    if not cfg.get("telegram_token", "").strip():
        return
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        log_fd = open(LOG_FILE, "a", encoding="utf-8")
        subprocess.Popen(
            [str(VENV_PYTHON), str(ENGINE_PY)],
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            env=env,
            cwd=str(DIR)
        )
    except Exception as e:
        pass


def stop_service():
    """停止后台服务"""
    try:
        subprocess.run(["pkill", "-f", "bridge_engine.py"])
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ==============================================================================
# UI 调色盘与通用组件
# ==============================================================================
C_BG_DARK = "#0B0F19"       # 窗口背景
C_CARD_BG = "#161F30"       # 卡片背景
C_INPUT_BG = "#0D1322"      # 输入框背景
C_TEXT_WHITE = "#FFFFFF"    # 纯白标题
C_TEXT_PRIMARY = "#F8FAFC"  # 核心文字
C_TEXT_MUTED = "#CBD5E1"    # 次级文字（清晰浅银灰）
C_ACCENT_CYAN = "#38BDF8"   # 亮青蓝
C_GREEN_TEXT = "#34D399"    # 亮绿文字
C_GREEN_BG = "#064E3B"      # 绿底色
C_RED_TEXT = "#FCA5A5"      # 亮红文字
C_RED_BG = "#7F1D1D"        # 红底色


class ModernButton(tk.Label):
    """专为 macOS 打造的高对比度质感交互按钮（彻底摆脱原生白框）"""
    def __init__(
        self, parent, text, command=None,
        bg_color="#2563EB", hover_color="#1D4ED8", fg_color="#FFFFFF",
        font=("Helvetica", 10, "bold"), padx=16, pady=8, **kwargs
    ):
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.command = command
        super().__init__(
            parent,
            text=text,
            bg=bg_color,
            fg=fg_color,
            font=font,
            padx=padx,
            pady=pady,
            cursor="pointinghand",
            relief=tk.FLAT,
            **kwargs
        )
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda e: self.config(bg=self.hover_color))
        self.bind("<Leave>", lambda e: self.config(bg=self.bg_color))

    def _on_click(self, event):
        if self.command:
            self.command()

    def set_theme(self, text, bg_color, hover_color, fg_color="#FFFFFF"):
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.config(text=text, bg=bg_color, fg=fg_color)


# ==============================================================================
# GUI 桌面应用主类
# ==============================================================================
class AntigravityApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Antigravity TG Bridge - 桌面控制中心")
        self.geometry("820x660")
        self.minsize(740, 580)
        self.configure(bg=C_BG_DARK)

        # 启动置顶一次
        self.attributes("-topmost", True)
        self.after(350, lambda: self.attributes("-topmost", False))

        self.log_pos = 0
        self.running_state = False

        self.setup_styles()
        self.build_ui()
        # 初始化日志视窗内容
        self.init_log_view()
        # 自动确保后台守护服务拉起运行
        if not is_service_running():
            start_service()
        # 立即在主线程同步刷新一次初始状态
        self.refresh_status_ui()
        # 启动日志与状态后台监测
        self.start_log_and_status_monitor()

    def setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        
        # 选项卡样式 (高对比度设计)
        style.configure("TNotebook", background=C_BG_DARK, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#121826",
            foreground="#94A3B8",
            font=("Helvetica", 11, "bold"),
            padding=[26, 10]
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", C_CARD_BG)],
            foreground=[("selected", C_ACCENT_CYAN)]
        )

    def build_ui(self):
        # 1. 顶部 Header
        header = tk.Frame(self, bg=C_CARD_BG, padx=22, pady=16)
        header.pack(fill=tk.X)

        title_box = tk.Frame(header, bg=C_CARD_BG)
        title_box.pack(side=tk.LEFT)

        tk.Label(
            title_box, text="🛸 Antigravity TG Bridge",
            font=("Helvetica", 18, "bold"), fg=C_ACCENT_CYAN, bg=C_CARD_BG
        ).pack(anchor="w")

        tk.Label(
            title_box, text="Telegram ↔ Google Antigravity IDE 本地直连控制中心",
            font=("Helvetica", 10, "bold"), fg=C_TEXT_MUTED, bg=C_CARD_BG
        ).pack(anchor="w", pady=(2, 0))

        self.badge = tk.Label(
            header, text="● 检测中...",
            font=("Helvetica", 11, "bold"), fg=C_TEXT_MUTED, bg="#263147",
            padx=16, pady=7
        )
        self.badge.pack(side=tk.RIGHT)

        # 2. 选项卡组件
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)

        self.tab_dashboard = tk.Frame(self.notebook, bg=C_BG_DARK)
        self.tab_settings = tk.Frame(self.notebook, bg=C_BG_DARK)

        self.notebook.add(self.tab_dashboard, text=" 📊 控制看板 ")
        self.notebook.add(self.tab_settings, text=" ⚙️ 图形化设置 ")

        # 构建两个标签页
        self.build_dashboard_tab()
        self.build_settings_tab()

    # --------------------------------------------------------------------------
    # 选项卡 1：控制看板
    # --------------------------------------------------------------------------
    def build_dashboard_tab(self):
        # 1. 顶部工作区展示卡片
        ws_card = tk.Frame(self.tab_dashboard, bg=C_CARD_BG, padx=18, pady=12)
        ws_card.pack(fill=tk.X, pady=(10, 6))

        tk.Label(
            ws_card, text="📂 当前工作区：",
            font=("Helvetica", 11, "bold"), fg=C_TEXT_WHITE, bg=C_CARD_BG
        ).pack(side=tk.LEFT)

        self.ws_lbl = tk.Label(
            ws_card, text="",
            font=("Menlo", 10, "bold"), fg=C_ACCENT_CYAN, bg=C_CARD_BG
        )
        self.ws_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        btn_pick_ws = ModernButton(
            ws_card, text="切换目录",
            bg_color="#0284C7", hover_color="#0369A1", fg_color="#FFFFFF",
            padx=14, pady=5, font=("Helvetica", 10, "bold"),
            command=self.on_browse_workspace
        )
        btn_pick_ws.pack(side=tk.RIGHT)

        # 2. 底部操作按钮栏（吸底常驻）
        actions = tk.Frame(self.tab_dashboard, bg=C_CARD_BG, padx=18, pady=14)
        actions.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 4))

        self.btn_toggle = ModernButton(
            actions, text="🚀 启动服务",
            bg_color="#059669", hover_color="#047857", fg_color="#FFFFFF",
            padx=18, pady=8, font=("Helvetica", 11, "bold"),
            command=self.on_toggle_service
        )
        self.btn_toggle.pack(side=tk.LEFT, padx=(0, 8))

        btn_ide = ModernButton(
            actions, text="🖥 打开 IDE 窗口",
            bg_color="#2563EB", hover_color="#1D4ED8", fg_color="#FFFFFF",
            padx=14, pady=8, font=("Helvetica", 10, "bold"),
            command=self.on_open_ide
        )
        btn_ide.pack(side=tk.LEFT, padx=4)

        btn_restart = ModernButton(
            actions, text="🔄 重启服务",
            bg_color="#4F46E5", hover_color="#4338CA", fg_color="#FFFFFF",
            padx=12, pady=8, font=("Helvetica", 10, "bold"),
            command=self.on_restart_service
        )
        btn_restart.pack(side=tk.LEFT, padx=4)

        btn_quit = ModernButton(
            actions, text="退出面板",
            bg_color="#334155", hover_color="#475569", fg_color="#FCA5A5",
            padx=14, pady=8, font=("Helvetica", 10, "bold"),
            command=self.destroy
        )
        btn_quit.pack(side=tk.RIGHT)

        # 3. 中间实时日志视窗
        log_header = tk.Frame(self.tab_dashboard, bg=C_BG_DARK)
        log_header.pack(fill=tk.X, pady=(6, 4))

        tk.Label(
            log_header, text="📜 实时通信与任务日志流",
            font=("Helvetica", 11, "bold"), fg=C_TEXT_WHITE, bg=C_BG_DARK
        ).pack(side=tk.LEFT)
        
        btn_clear = ModernButton(
            log_header, text="清屏",
            bg_color="#334155", hover_color="#475569", fg_color=C_TEXT_MUTED,
            padx=10, pady=3, font=("Helvetica", 9, "bold"),
            command=self.on_clear_log
        )
        btn_clear.pack(side=tk.RIGHT)

        log_box = tk.Frame(self.tab_dashboard, bg="#1E293B", padx=1, pady=1)
        log_box.pack(fill=tk.BOTH, expand=True, pady=(2, 4))

        self.log_text = tk.Text(
            log_box, bg=C_INPUT_BG, fg=C_GREEN_TEXT,
            insertbackground=C_ACCENT_CYAN, font=("Menlo", 10),
            wrap=tk.WORD, relief=tk.FLAT, padx=12, pady=12
        )
        scroll = tk.Scrollbar(log_box, command=self.log_text.yview, bg=C_CARD_BG)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # --------------------------------------------------------------------------
    # 选项卡 2：图形化设置面板
    # --------------------------------------------------------------------------
    def build_settings_tab(self):
        container = tk.Frame(self.tab_settings, bg=C_CARD_BG, padx=26, pady=22)
        container.pack(fill=tk.BOTH, expand=True, pady=10)

        # 1. Token 输入
        tk.Label(container, text="🔑 Telegram Bot Token", font=("Helvetica", 11, "bold"), fg=C_TEXT_WHITE, bg=C_CARD_BG).pack(anchor="w")
        tk.Label(container, text="在 Telegram 找 @BotFather 获取的专属 API Token", font=("Helvetica", 9, "bold"), fg=C_TEXT_MUTED, bg=C_CARD_BG).pack(anchor="w", pady=(1, 4))
        
        token_row = tk.Frame(container, bg=C_CARD_BG)
        token_row.pack(fill=tk.X, pady=(0, 14))

        self.token_entry = tk.Entry(token_row, font=("Menlo", 10), bg=C_INPUT_BG, fg=C_ACCENT_CYAN, insertbackground=C_ACCENT_CYAN, relief=tk.FLAT, show="•")
        self.token_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 8))

        self.btn_show_token = ModernButton(
            token_row, text="显示",
            bg_color="#334155", hover_color="#475569", fg_color=C_TEXT_PRIMARY,
            padx=12, pady=5, font=("Helvetica", 9, "bold"),
            command=self.toggle_token_visibility
        )
        self.btn_show_token.pack(side=tk.RIGHT)

        # 2. 用户白名单
        tk.Label(container, text="👤 授权用户 ID (Allowed User IDs)", font=("Helvetica", 11, "bold"), fg=C_TEXT_WHITE, bg=C_CARD_BG).pack(anchor="w")
        tk.Label(container, text="允许交互的 Telegram 用户数字 ID（多个逗号隔开，留空则自动绑定首个交互人）", font=("Helvetica", 9, "bold"), fg=C_TEXT_MUTED, bg=C_CARD_BG).pack(anchor="w", pady=(1, 4))
        
        self.uid_entry = tk.Entry(container, font=("Menlo", 10), bg=C_INPUT_BG, fg=C_TEXT_PRIMARY, insertbackground=C_ACCENT_CYAN, relief=tk.FLAT)
        self.uid_entry.pack(fill=tk.X, ipady=6, pady=(0, 14))

        # 3. 代理设置
        tk.Label(container, text="🌐 网络代理 (Proxy)", font=("Helvetica", 11, "bold"), fg=C_TEXT_WHITE, bg=C_CARD_BG).pack(anchor="w")
        tk.Label(container, text="例如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080，直连留空即可", font=("Helvetica", 9, "bold"), fg=C_TEXT_MUTED, bg=C_CARD_BG).pack(anchor="w", pady=(1, 4))
        
        self.proxy_entry = tk.Entry(container, font=("Menlo", 10), bg=C_INPUT_BG, fg=C_TEXT_PRIMARY, insertbackground=C_ACCENT_CYAN, relief=tk.FLAT)
        self.proxy_entry.pack(fill=tk.X, ipady=6, pady=(0, 14))

        # 4. 默认工作区
        tk.Label(container, text="📂 默认项目目录 (Default Workspace)", font=("Helvetica", 11, "bold"), fg=C_TEXT_WHITE, bg=C_CARD_BG).pack(anchor="w")
        
        ws_row = tk.Frame(container, bg=C_CARD_BG)
        ws_row.pack(fill=tk.X, pady=(4, 14))
        
        self.ws_entry = tk.Entry(ws_row, font=("Menlo", 10), bg=C_INPUT_BG, fg=C_ACCENT_CYAN, insertbackground=C_ACCENT_CYAN, relief=tk.FLAT)
        self.ws_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 8))
        
        btn_sel_ws = ModernButton(
            ws_row, text="浏览...",
            bg_color="#334155", hover_color="#475569", fg_color=C_TEXT_PRIMARY,
            padx=14, pady=5, font=("Helvetica", 10, "bold"),
            command=self.on_settings_browse_workspace
        )
        btn_sel_ws.pack(side=tk.RIGHT)

        # 5. 开关选项
        switches_frame = tk.Frame(container, bg=C_CARD_BG)
        switches_frame.pack(fill=tk.X, pady=(0, 18))

        self.var_auto_open = tk.BooleanVar(value=True)
        self.var_send_diff = tk.BooleanVar(value=True)

        cb1 = tk.Checkbutton(
            switches_frame, text="收到 Telegram 任务时，自动在 Mac 上拉起 Antigravity IDE 窗口",
            variable=self.var_auto_open, font=("Helvetica", 10, "bold"),
            fg=C_TEXT_PRIMARY, bg=C_CARD_BG, selectcolor=C_INPUT_BG,
            activebackground=C_CARD_BG, activeforeground=C_ACCENT_CYAN
        )
        cb1.pack(anchor="w", pady=3)

        cb2 = tk.Checkbutton(
            switches_frame, text="任务编写完成后，自动在 Telegram 回传 Git Diff 变动摘要",
            variable=self.var_send_diff, font=("Helvetica", 10, "bold"),
            fg=C_TEXT_PRIMARY, bg=C_CARD_BG, selectcolor=C_INPUT_BG,
            activebackground=C_CARD_BG, activeforeground=C_ACCENT_CYAN
        )
        cb2.pack(anchor="w", pady=3)

        # 6. 保存按钮
        save_box = tk.Frame(container, bg=C_CARD_BG)
        save_box.pack(fill=tk.X, pady=(6, 0))

        btn_save = ModernButton(
            save_box, text="💾 保存并应用配置",
            bg_color="#059669", hover_color="#047857", fg_color="#FFFFFF",
            padx=22, pady=9, font=("Helvetica", 11, "bold"),
            command=self.on_save_settings
        )
        btn_save.pack(side=tk.LEFT)

        self.save_feedback_lbl = tk.Label(
            save_box, text="", font=("Helvetica", 10, "bold"),
            fg=C_GREEN_TEXT, bg=C_CARD_BG
        )
        self.save_feedback_lbl.pack(side=tk.LEFT, padx=14)

        # 填充当前配置值
        self.populate_settings()

    def populate_settings(self):
        cfg = load_config()
        self.token_entry.delete(0, tk.END)
        self.token_entry.insert(0, cfg.get("telegram_token", ""))

        uids = cfg.get("allowed_user_ids", [])
        self.uid_entry.delete(0, tk.END)
        self.uid_entry.insert(0, ", ".join(str(u) for u in uids))

        self.proxy_entry.delete(0, tk.END)
        self.proxy_entry.insert(0, cfg.get("proxy", ""))

        self.ws_entry.delete(0, tk.END)
        self.ws_entry.insert(0, cfg.get("default_workspace", ""))

        self.var_auto_open.set(cfg.get("auto_open_ide", True))
        self.var_send_diff.set(cfg.get("send_diff_after_task", True))

    def toggle_token_visibility(self):
        if self.token_entry.cget("show") == "":
            self.token_entry.config(show="•")
            self.btn_show_token.config(text="显示")
        else:
            self.token_entry.config(show="")
            self.btn_show_token.config(text="隐藏")

    def on_save_settings(self):
        cfg = load_config()
        cfg["telegram_token"] = self.token_entry.get().strip()

        uid_str = self.uid_entry.get().strip()
        uids = []
        if uid_str:
            for part in uid_str.split(","):
                part = part.strip()
                if part.isdigit():
                    uids.append(int(part))
        cfg["allowed_user_ids"] = uids

        cfg["proxy"] = self.proxy_entry.get().strip()
        cfg["default_workspace"] = self.ws_entry.get().strip()
        cfg["auto_open_ide"] = self.var_auto_open.get()
        cfg["send_diff_after_task"] = self.var_send_diff.get()

        save_config(cfg)
        self.ws_lbl.config(text=cfg["default_workspace"])

        self.save_feedback_lbl.config(text="✅ 配置已成功保存！")
        self.after(3000, lambda: self.save_feedback_lbl.config(text=""))

        # 如果正在运行，提示重启
        if is_service_running():
            if messagebox.askyesno("配置已保存", "配置已成功保存！是否立即重启服务以应用新配置？"):
                self.on_restart_service()

    def on_settings_browse_workspace(self):
        curr = self.ws_entry.get().strip() or os.path.expanduser("~")
        d = filedialog.askdirectory(initialdir=curr, title="选择默认项目工作区")
        if d:
            self.ws_entry.delete(0, tk.END)
            self.ws_entry.insert(0, d)

    def on_browse_workspace(self):
        cfg = load_config()
        curr = cfg.get("default_workspace", os.path.expanduser("~"))
        d = filedialog.askdirectory(initialdir=curr, title="选择新的项目工作区目录")
        if d:
            cfg["default_workspace"] = d
            save_config(cfg)
            self.ws_lbl.config(text=d)
            self.ws_entry.delete(0, tk.END)
            self.ws_entry.insert(0, d)
            self.append_log(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 📂 [控制面板] 工作区已切换为: {d}\n")

    # --------------------------------------------------------------------------
    # 服务控制操作
    # --------------------------------------------------------------------------
    def on_toggle_service(self):
        if self.running_state:
            stop_service()
            self.append_log(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🛑 [控制面板] 已停止后台桥接服务。\n")
        else:
            cfg = load_config()
            if not cfg.get("telegram_token", "").strip():
                messagebox.showerror("未配置 Token", "请先在【⚙️ 图形化设置】标签页中填写 Telegram Bot Token！")
                self.notebook.select(self.tab_settings)
                return
            start_service()
            self.append_log(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🚀 [控制面板] 正在启动后台通信引擎...\n")
        self.after(800, self.refresh_status_ui)

    def on_restart_service(self):
        stop_service()
        time.sleep(0.8)
        start_service()
        self.append_log(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🔄 [控制面板] 桥接服务已重新启动！\n")
        self.after(1000, self.refresh_status_ui)

    def on_open_ide(self):
        cfg = load_config()
        ws = cfg.get("default_workspace", str(Path.home() / "Desktop" / "test"))
        subprocess.run(["open", "-a", "Antigravity IDE", ws])
        self.append_log(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🖥 [控制面板] 已唤起 Antigravity IDE 窗口 ({ws})\n")

    def on_clear_log(self):
        self.log_text.delete("1.0", tk.END)
        if LOG_FILE.exists():
            try:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("")
                self.log_pos = 0
            except Exception:
                pass

    # --------------------------------------------------------------------------
    # 状态刷新与实时日志监测
    # --------------------------------------------------------------------------
    def init_log_view(self):
        """打开窗口时加载最新的历史日志"""
        if LOG_FILE.exists():
            try:
                size = LOG_FILE.stat().st_size
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    if size > 15000:
                        f.seek(size - 15000)
                        f.readline()  # 跳过半行
                    initial_content = f.read()
                    self.log_pos = f.tell()
                    if initial_content:
                        self.log_text.insert(tk.END, initial_content)
                        self.log_text.see(tk.END)
            except Exception:
                self.log_pos = 0
        else:
            self.log_pos = 0

        if not self.log_text.get("1.0", tk.END).strip():
            self.log_text.insert(tk.END, f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✨ [系统] 控制中心已就绪，正在监听实时通信...\n")

    def refresh_status_ui(self):
        running = is_service_running()
        pid = get_service_pid()
        self.running_state = running

        if running:
            self.badge.config(text=f"● 正常运行中 (PID: {pid})", fg=C_GREEN_TEXT, bg=C_GREEN_BG)
            self.btn_toggle.set_theme("🛑 停止服务", "#DC2626", "#B91C1C", "#FFFFFF")
        else:
            self.badge.config(text="● 服务已停止", fg=C_RED_TEXT, bg=C_RED_BG)
            self.btn_toggle.set_theme("🚀 启动服务", "#059669", "#047857", "#FFFFFF")

        cfg = load_config()
        self.ws_lbl.config(text=cfg.get("default_workspace", ""))

    def start_log_and_status_monitor(self):
        def monitor():
            watchdog_counter = 0
            while True:
                # 刷新状态
                self.after(0, self.refresh_status_ui)

                # 自动看门狗：如果服务未运行且已配置 Token，自动平滑拉起后台引擎
                watchdog_counter += 1
                if watchdog_counter >= 5:  # 每 2 秒巡检一次
                    watchdog_counter = 0
                    if not is_service_running():
                        cfg = load_config()
                        if cfg.get("telegram_token", "").strip():
                            start_service()

                # 读取实时日志追加
                if LOG_FILE.exists():
                    try:
                        file_size = LOG_FILE.stat().st_size
                        if file_size < self.log_pos:
                            self.log_pos = 0
                        
                        if file_size > self.log_pos:
                            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                                f.seek(self.log_pos)
                                new_text = f.read()
                                if new_text:
                                    self.log_pos = f.tell()
                                    self.after(0, self.append_log, new_text)
                    except Exception:
                        pass
                time.sleep(0.4)

        t = threading.Thread(target=monitor, daemon=True)
        t.start()

    def append_log(self, text):
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)


if __name__ == "__main__":
    app = AntigravityApp()
    app.mainloop()
