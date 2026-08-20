#!/usr/bin/env python3
"""
Antigravity Telegram Native Bridge - Core Communication Engine
=============================================================
Direct, zero-third-party, native bidirectional bridge between Telegram and Google Antigravity IDE.
"""

import os
import sys
import json
import asyncio
import subprocess
import shutil
import re
import time
import fcntl
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

# ==============================================================================
# 路径与全局常量
# ==============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
LOG_PATH = SCRIPT_DIR / "bridge.log"
DOWNLOADS_DIR = SCRIPT_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

HOME_DIR = Path.home()
BRAIN_DIR = HOME_DIR / ".gemini" / "antigravity-ide" / "brain"
AGENTAPI_BIN = HOME_DIR / ".gemini" / "antigravity-ide" / "bin" / "agentapi"

# 运行时全局状态
RUNTIME_STATE = {
    "current_workspace": None,
    "active_conversation_id": None,
}


def log(msg: str):
    """统一记录日志：输出到 stdout 并由启动器统一写入 bridge.log"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted, flush=True)


# ==============================================================================
# 配置管理
# ==============================================================================
def load_config() -> Dict[str, Any]:
    """读取配置文件"""
    default_config = {
        "telegram_token": "",
        "allowed_user_ids": [],
        "default_workspace": os.path.expanduser("~/Desktop/test"),
        "proxy": "",
        "auto_open_ide": True,
        "send_diff_after_task": True,
        "stream_updates": True,
    }
    if not CONFIG_PATH.exists():
        save_config(default_config)
        return default_config
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            for k, v in default_config.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception:
        return default_config


def save_config(cfg: Dict[str, Any]):
    """持久化保存配置"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log(f"❌ 写入配置文件失败: {e}")


def get_current_workspace() -> str:
    """获取当前工作区路径"""
    if RUNTIME_STATE["current_workspace"]:
        return RUNTIME_STATE["current_workspace"]
    cfg = load_config()
    RUNTIME_STATE["current_workspace"] = cfg.get("default_workspace", str(Path.home() / "Desktop" / "test"))
    return RUNTIME_STATE["current_workspace"]


# ==============================================================================
# Antigravity IDE 会话追踪与动态端口探测
# ==============================================================================
def get_active_conversation_id(force_refresh: bool = True, target_workspace: Optional[str] = None) -> Optional[str]:
    """获取指定工作区当前绑定的专属 Antigravity IDE 会话 ID（支持多项目严格隔离）"""
    ws = target_workspace or get_current_workspace()
    ws_uri = Path(ws).resolve().as_uri().rstrip("/")

    if not force_refresh and RUNTIME_STATE.get("active_conversation_id"):
        return RUNTIME_STATE["active_conversation_id"]

    if not BRAIN_DIR.exists():
        return None

    dirs = [
        d for d in BRAIN_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("temp") and (d / ".system_generated" / "logs" / "transcript.jsonl").exists()
    ]
    if not dirs:
        return None

    dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    # 1. 优先通过 API 或会话首部匹配工作区 URI，确保绝对不与其他项目串台
    addr, csrf = find_working_ls_address_and_csrf()
    if addr:
        env = dict(os.environ, ANTIGRAVITY_LS_ADDRESS=addr)
        if csrf:
            env["ANTIGRAVITY_CSRF_TOKEN"] = csrf
        for d in dirs[:12]:
            cid = d.name
            try:
                p = subprocess.run(
                    [str(AGENTAPI_BIN), "get-conversation-metadata", cid],
                    env=env, capture_output=True, text=True, timeout=1.0
                )
                if p.returncode == 0:
                    data = json.loads(p.stdout)
                    ws_list = data.get("response", {}).get("conversationMetadata", {}).get("metadata", {}).get("workspaces", [])
                    for w in ws_list:
                        if w.get("workspaceFolderAbsoluteUri", "").rstrip("/") == ws_uri:
                            RUNTIME_STATE["active_conversation_id"] = cid
                            return cid
            except Exception:
                pass

    # 2. 兜底返回最近更新的有效会话
    RUNTIME_STATE["active_conversation_id"] = dirs[0].name
    return RUNTIME_STATE["active_conversation_id"]


def get_transcript_path(conversation_id: str) -> Path:
    """获取指定会话的 transcript.jsonl 日志路径"""
    return BRAIN_DIR / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"


def count_transcript_lines(conversation_id: str) -> int:
    """统计当前会话 transcript.jsonl 的行数"""
    path = get_transcript_path(conversation_id)
    if not path.exists():
        return 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def find_working_ls_address_and_csrf(conv_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """通过扫描活动进程精准提取 Language Server 的活动端口与 CSRF Token"""
    # 1. 优先验证已缓存的地址与 Token
    cached_addr = RUNTIME_STATE.get("working_ls_address")
    cached_csrf = RUNTIME_STATE.get("working_csrf_token")
    if cached_addr:
        env = dict(os.environ, ANTIGRAVITY_LS_ADDRESS=cached_addr)
        if cached_csrf:
            env["ANTIGRAVITY_CSRF_TOKEN"] = cached_csrf
        try:
            p = subprocess.run(
                [str(AGENTAPI_BIN), "get-conversation-metadata", "probe-test-id"],
                env=env, capture_output=True, text=True, timeout=1.0
            )
            if "trajectory not found" in p.stdout or "conversationMetadata" in p.stdout:
                return cached_addr, cached_csrf
        except Exception:
            pass
        RUNTIME_STATE["working_ls_address"] = None
        RUNTIME_STATE["working_csrf_token"] = None

    # 2. 从系统进程表中提取所有 language_server 的 PID 与 CSRF Token
    try:
        res = subprocess.run("ps aux", shell=True, capture_output=True, text=True)
        ls_candidates = []
        for line in res.stdout.splitlines():
            if "language_server" in line:
                parts = line.split()
                if len(parts) > 1:
                    m_pid = parts[1]
                    m_csrf = re.search(r"--csrf_token\s+([a-zA-Z0-9\-]+)", line)
                    token = m_csrf.group(1) if m_csrf else None
                    ls_candidates.append((m_pid, token))

        for pid, csrf_token in ls_candidates:
            r_ports = subprocess.run(f"lsof -Pan -p {pid} -iTCP -sTCP:LISTEN", shell=True, capture_output=True, text=True)
            ports = list(set(re.findall(r"127\.0\.0\.1:(\d+)", r_ports.stdout)))
            for port in ports:
                addr = f"localhost:{port}"
                env = dict(os.environ, ANTIGRAVITY_LS_ADDRESS=addr)
                if csrf_token:
                    env["ANTIGRAVITY_CSRF_TOKEN"] = csrf_token
                try:
                    p = subprocess.run(
                        [str(AGENTAPI_BIN), "get-conversation-metadata", "probe-test-id"],
                        env=env, capture_output=True, text=True, timeout=1.5
                    )
                    if "trajectory not found" in p.stdout or "conversationMetadata" in p.stdout:
                        RUNTIME_STATE["working_ls_address"] = addr
                        RUNTIME_STATE["working_csrf_token"] = csrf_token
                        return addr, csrf_token
                except Exception:
                    pass
    except Exception:
        pass
    return None, None


def open_ide_window(workspace_path: Optional[str] = None) -> Tuple[bool, str]:
    """在 macOS 桌面唤醒并前台激活 Antigravity IDE 窗口"""
    target = workspace_path or get_current_workspace()
    try:
        subprocess.run(["open", "-a", "Antigravity IDE", target], check=True)
        log(f"🖥 已在 Mac 屏幕上唤醒 Antigravity IDE（{target}）")
        return True, f"已在 Mac 屏幕上唤醒 Antigravity IDE（{target}）"
    except Exception as e:
        log(f"❌ 唤醒 Antigravity IDE 失败: {e}")
        return False, f"唤醒 Antigravity IDE 失败: {e}"


async def wait_for_ide_ready(ws: str, conv_id: str, status_msg) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """拉起 IDE 并进行心跳握手探测，直至通信通道完全就绪"""
    log("🖥 检测到 IDE 未启动，正在自动唤起 Antigravity IDE 窗口...")
    open_ide_window(ws)
    try:
        await status_msg.edit_text(
            "🖥 **检测到 Antigravity IDE 尚未运行，正在自动为您在 Mac 上唤醒启动 IDE...**\n⏳ 正在自动探测通信服务与安全令牌...",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # 轮询探测最长 30 秒 (15 次 * 2 秒)
    for i in range(15):
        await asyncio.sleep(2.0)
        addr, csrf = find_working_ls_address_and_csrf()
        if addr:
            log(f"🔍 握手成功！探测到 Antigravity IDE 活动端口: {addr} (CSRF 已配对)")
            await asyncio.sleep(1.0)  # 等待会话就绪
            curr_id = get_active_conversation_id(force_refresh=True) or conv_id
            return curr_id, addr, csrf

    return get_active_conversation_id(force_refresh=True), None, None


# ==============================================================================
# 权限鉴权与辅助工具
# ==============================================================================
async def check_auth(update: Update) -> bool:
    """白名单鉴权机制"""
    cfg = load_config()
    allowed_users = cfg.get("allowed_user_ids", [])
    user_id = update.effective_user.id

    if not allowed_users:
        # 首次使用，自动将当前发起人加入白名单
        cfg["allowed_user_ids"] = [user_id]
        save_config(cfg)
        log(f"🔑 自动将首个交互用户 ID: {user_id} 绑定为管理员。")
        return True

    if user_id not in allowed_users:
        log(f"🚫 拦截未授权用户访问: ID {user_id}")
        await update.message.reply_text(
            f"🚫 **无权限访问**\n你的 Telegram User ID 是 `{user_id}`，不在本设备的授权白名单中。",
            parse_mode="Markdown"
        )
        return False
    return True


def run_shell(command: str, cwd: Optional[str] = None) -> str:
    """在指定工作区安全执行终端 Shell 命令"""
    target_cwd = cwd or get_current_workspace()
    try:
        res = subprocess.run(
            command,
            shell=True,
            cwd=target_cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (res.stdout + "\n" + res.stderr).strip()
        return output if output else "(无输出)"
    except Exception as e:
        return f"执行出错: {e}"


def get_workspace_quick_keyboard() -> InlineKeyboardMarkup:
    """生成快捷交互按钮"""
    keyboard = [
        [
            InlineKeyboardButton("📂 实时弹窗查看工作目录", callback_data="popup_workspace_info"),
        ],
        [
            InlineKeyboardButton("📋 查看 Diff 摘要", callback_data="popup_git_diff"),
            InlineKeyboardButton("🖥 唤起 IDE 窗口", callback_data="trigger_open_ide"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# ==============================================================================
# 核心 Agent 执行引擎（流式回传、图片视觉分析与自愈机制）
# ==============================================================================
async def keep_typing_action(bot, chat_id: int, stop_event: asyncio.Event):
    """在 Agent 执行任务期间，持续向 Telegram 发送 typing 状态"""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            pass


async def send_message_to_ide(conv_id: str, prompt: str, ws: str, status_msg) -> Tuple[bool, str, str]:
    """向 IDE 注入消息，包含动态端口探测与自动拉起自愈机制"""
    current_id = conv_id

    # 1. 动态探测当前可用的 Language Server 地址与 CSRF Token
    addr, csrf = find_working_ls_address_and_csrf(current_id)

    # 2. 如果当前没有可用地址（IDE 未启动或正在启动），进入自动唤醒流程
    if not addr:
        ready_id, ready_addr, ready_csrf = await wait_for_ide_ready(ws, current_id, status_msg)
        if ready_id:
            current_id = ready_id
        addr = ready_addr
        csrf = ready_csrf

    if not addr:
        return False, "未能连接到 Antigravity IDE 语言服务器端口（IDE 启动超时，请确保 Mac 上的 Antigravity IDE 软件存在）。", current_id

    env = dict(os.environ, ANTIGRAVITY_LS_ADDRESS=addr)
    if csrf:
        env["ANTIGRAVITY_CSRF_TOKEN"] = csrf

    # 3. 优先向当前已有会话发送消息
    if current_id:
        log(f"📤 正在向 IDE 会话 [{current_id}] (端口: {addr}) 注入任务...")
        proc = await asyncio.create_subprocess_exec(
            str(AGENTAPI_BIN),
            "send-message",
            "--title=Telegram",
            current_id,
            prompt,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return True, "", current_id

        log(f"⚠️ 会话注入未成功，正在重新扫描活动端口与 CSRF 自愈...")

    # 重新刷新探测最新活动端口与安全凭据
    fresh_addr, fresh_csrf = find_working_ls_address_and_csrf()
    if fresh_addr:
        addr = fresh_addr
        csrf = fresh_csrf
        env = dict(os.environ, ANTIGRAVITY_LS_ADDRESS=addr)
        if csrf:
            env["ANTIGRAVITY_CSRF_TOKEN"] = csrf

    # 4. 若无已有会话或旧会话失效，自愈创建全新会话
    log("🌱 正在通过 agentapi new-conversation 自动拉起全新 IDE 对话...")
    proc = await asyncio.create_subprocess_exec(
        str(AGENTAPI_BIN),
        "new-conversation",
        "--title=Telegram",
        prompt,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        await asyncio.sleep(1.0)
        new_id = get_active_conversation_id(force_refresh=True, target_workspace=ws) or current_id
        log(f"✨ 成功拉起新对话: {new_id}")
        return True, "", new_id

    err_msg = stderr.decode().strip() or stdout.decode().strip()
    return False, err_msg, current_id


async def safe_edit_message(msg, text: str, reply_markup=None, parse_mode: Optional[str] = "Markdown"):
    """安全编辑 Telegram 消息，防止 Markdown 实体错误导致丢帧卡死"""
    try:
        await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            # 降级为纯文本安全输出
            await msg.edit_text(text, reply_markup=reply_markup, parse_mode=None)
        except Exception:
            pass


def is_valid_model_response(step: dict) -> bool:
    """严格判断是否为 Agent 面向用户的真实回答，杜绝内部工具日志泄露"""
    if step.get("type") != "PLANNER_RESPONSE":
        return False
    content = step.get("content", "").strip()
    if not content:
        return False
    # 过滤系统和工具生成的内部日志
    if (
        content.startswith("Created At:")
        or content.startswith("Completed At:")
        or content.startswith("The command exited")
        or "<SYSTEM_MESSAGE>" in content
        or "Task id \"" in content
    ):
        return False
    return True


async def execute_agent_task(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, status_msg):
    """核心 Agent 任务执行、监控与流式回传处理"""
    cfg = load_config()
    ws = get_current_workspace()

    # 如果开启了 auto_open_ide，自动拉起桌面上的 IDE 窗口
    if cfg.get("auto_open_ide", False):
        open_ide_window(ws)

    # 1. 查找当前活动的 Antigravity IDE 会话 ID
    conv_id = get_active_conversation_id(force_refresh=True, target_workspace=ws)
    if not conv_id:
        open_ide_window(ws)
        await asyncio.sleep(2.5)
        conv_id = get_active_conversation_id(force_refresh=True, target_workspace=ws)

    if not conv_id:
        log("❌ 未找到 Antigravity IDE 的活动会话")
        await safe_edit_message(status_msg, "❌ 未找到 Antigravity IDE 的活动会话，请确保 Antigravity IDE 曾打开过至少一个对话。")
        return

    # 启动持续的 typing 状态广播
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        keep_typing_action(context.bot, update.effective_chat.id, stop_typing)
    )

    try:
        # 记录发送前 transcript.jsonl 的行数
        start_lines = count_transcript_lines(conv_id)

        # 2. 通过自愈机制将消息注入到 IDE 当前会话
        success, err_msg, actual_conv_id = await send_message_to_ide(conv_id, prompt, ws, status_msg)
        if not success:
            log(f"❌ 注入 IDE 失败: {err_msg}")
            await safe_edit_message(status_msg, f"❌ 注入 IDE 失败: {err_msg}")
            return

        conv_id = actual_conv_id
        transcript_file = get_transcript_path(conv_id)

        # 3. 异步监听 transcript.jsonl，打字机流式流向 Telegram
        last_status_text = ""
        final_answer = ""
        last_edit_time = 0.0
        max_wait_seconds = 300  # 最长等待 5 分钟
        start_time = asyncio.get_event_loop().time()
        is_task_complete = False

        while (asyncio.get_event_loop().time() - start_time) < max_wait_seconds:
            await asyncio.sleep(0.5)
            if not transcript_file.exists():
                continue

            # 读取新追加的行
            new_lines = []
            try:
                with open(transcript_file, "r", encoding="utf-8", errors="ignore") as f:
                    for idx, line in enumerate(f):
                        if idx >= start_lines:
                            line_str = line.strip()
                            if line_str:
                                try:
                                    new_lines.append(json.loads(line_str))
                                except Exception:
                                    pass
            except Exception:
                continue

            # 分析新产生的所有数据步
            for step in new_lines:
                tool_calls = step.get("tool_calls", [])

                # 捕获中间工具调用状态
                if tool_calls:
                    for t in tool_calls:
                        t_name = t.get("name", "")
                        t_args = t.get("args", {})
                        if t_name == "write_to_file":
                            fpath = t_args.get("TargetFile", "")
                            status_desc = f"📝 正在创建/写入文件: `{Path(fpath).name if fpath else ''}`"
                        elif t_name in ("replace_file_content", "multi_replace_file_content"):
                            fpath = t_args.get("TargetFile", "")
                            status_desc = f"✏️ 正在修改文件: `{Path(fpath).name if fpath else ''}`"
                        elif t_name == "run_command":
                            cmd = t_args.get("CommandLine", "")[:60]
                            status_desc = f"💻 正在运行命令: `{cmd}`"
                        elif t_name == "view_file":
                            fpath = t_args.get("AbsolutePath", "")
                            status_desc = f"🔍 正在查看文件/图片: `{Path(fpath).name if fpath else ''}`"
                        elif t_name == "grep_search":
                            status_desc = f"🔎 正在全局检索代码..."
                        elif t_name == "list_dir":
                            status_desc = f"📂 正在分析项目目录结构..."
                        else:
                            status_desc = f"⚡️ 正在调用工具 `{t_name}`..."

                        if status_desc != last_status_text:
                            last_status_text = status_desc
                            log(f"⚡️ [IDE Agent] {status_desc}")
                            now = asyncio.get_event_loop().time()
                            if (now - last_edit_time) >= 0.8:
                                await safe_edit_message(
                                    status_msg,
                                    f"⏳ **Agent 正在处理中...**\n━━━━━━━━━━━━━━━━━━━━\n{status_desc}"
                                )
                                last_edit_time = now

                # 捕获 Agent 真正的文本回答（杜绝内部工具日志）
                if is_valid_model_response(step):
                    final_answer = step.get("content", "").strip()
                    now = asyncio.get_event_loop().time()
                    if (now - last_edit_time) >= 1.0:
                        display_text = final_answer[:3800]
                        await safe_edit_message(
                            status_msg,
                            f"{display_text} ▌",
                            reply_markup=get_workspace_quick_keyboard()
                        )
                        last_edit_time = now

            # 真正完成的判定条件：必须是 PLANNER_RESPONSE，没有进行中的 tool_calls，并且内容已就绪
            if new_lines:
                last_step = new_lines[-1]
                if (
                    is_valid_model_response(last_step)
                    and last_step.get("status") == "DONE"
                    and len(last_step.get("tool_calls", [])) == 0
                ):
                    final_answer = last_step.get("content", "").strip()
                    is_task_complete = True
                    break

        # 4. 任务最终呈现
        if final_answer:
            diff_text = ""
            if cfg.get("send_diff_after_task", True):
                diff_stat = run_shell("git diff --stat", cwd=ws)
                if diff_stat and diff_stat != "(无输出)":
                    diff_text = f"\n\n📋 **Git 变更摘要**:\n```\n{diff_stat[:400]}\n```"

            full_reply = f"{final_answer}{diff_text}"
            if len(full_reply) > 4000:
                full_reply = full_reply[:3900] + "\n\n...(内容过长已截断)"

            await safe_edit_message(
                status_msg,
                full_reply,
                reply_markup=get_workspace_quick_keyboard()
            )
            log("✅ [IDE Agent] 任务执行完毕，已回传结果至 Telegram")
        else:
            await safe_edit_message(
                status_msg,
                "✅ 任务已注入 Antigravity IDE 执行完毕，如需查看详情请发送 `/diff` 或唤起 IDE 查看。",
                reply_markup=get_workspace_quick_keyboard()
            )
            log("✅ [IDE Agent] 任务注入完成")

    except Exception as e:
        log(f"❌ 执行异常: {e}")
        await safe_edit_message(status_msg, f"❌ 执行异常: {e}")
    finally:
        stop_typing.set()
        typing_task.cancel()


# ==============================================================================
# Telegram 消息与多模态图片 Handler
# ==============================================================================
async def handle_agent_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户发送的普通自然语言编程需求"""
    if not await check_auth(update):
        return

    prompt = update.message.text.strip()
    if not prompt:
        return

    user_id = update.effective_user.id
    log(f"📩 [Telegram] 收到消息 (用户 ID: {user_id}): {prompt}")

    # 智能识别自然语言切换工作区指令（例如：“切换目录到 /Users/dv/Desktop/my_project”）
    match_ws = re.match(r"^(?:切换工作区|切换目录|切换工作目录|修改工作目录|工作目录切换为|换到目录|cd到?)\s*(?:至|到)?\s*[:：]?\s*(~?/[\w\.\-\_\/\s]+)$", prompt, re.IGNORECASE)
    if match_ws:
        raw_path = match_ws.group(1).strip()
        p = Path(raw_path).expanduser().resolve()
        if p.exists() and p.is_dir():
            RUNTIME_STATE["current_workspace"] = str(p)
            cfg = load_config()
            cfg["default_workspace"] = str(p)
            save_config(cfg)
            open_ide_window(str(p))
            log(f"📂 自然语言触发：工作区已切换为: {p}")
            await update.message.reply_text(
                f"✅ **工作区已成功切换为**：\n`{p}`\n\n🖥 **已自动在 Mac 屏幕上唤醒 Antigravity IDE 加载新项目！**",
                reply_markup=get_workspace_quick_keyboard(),
                parse_mode="Markdown"
            )
            return
        else:
            await update.message.reply_text(f"❌ 路径不存在或不是文件夹：`{p}`", parse_mode="Markdown")
            return

    status_msg = await update.message.reply_text(
        "⏳ **正在连接并派发任务至 Antigravity IDE...**",
        parse_mode="Markdown"
    )
    await execute_agent_task(update, context, prompt, status_msg)


async def handle_agent_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户发送的报错截图或 UI 设计图"""
    if not await check_auth(update):
        return

    caption = update.message.caption or ""
    log(f"🖼 [Telegram] 收到图片/截图上传 (附加说明: {caption})")

    status_msg = await update.message.reply_text(
        "🖼 **正在接收并下载高清图片/截图...**",
        parse_mode="Markdown"
    )

    try:
        if update.message.photo:
            file_obj = await update.message.photo[-1].get_file()
        elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith("image/"):
            file_obj = await update.message.document.get_file()
        else:
            await status_msg.edit_text("❌ 未能识别图片格式，请发送标准图片文件。")
            return

        filename = f"tg_img_{int(time.time())}_{file_obj.file_unique_id}.jpg"
        save_path = DOWNLOADS_DIR / filename
        await file_obj.download_to_drive(custom_path=save_path)
        log(f"💾 图片已保存至本地: {save_path}")

        user_desc = caption.strip() if caption.strip() else "请仔细查看并分析这张图片/截图，根据图中的内容和问题完成代码编写或故障排查。"
        prompt = (
            f"【用户从 Telegram 上传了一张图片/截图】\n"
            f"本地图片绝对路径：{save_path.resolve()}\n"
            f"用户附带的需求说明：{user_desc}\n\n"
            f"请务必使用 view_file 工具查看该图片文件（路径：{save_path.resolve()}），"
            f"分析图片中的 UI、报错信息或代码，并给出针对性的解答或在当前项目中直接编写/修改代码。"
        )

        await status_msg.edit_text(
            f"🖼 **图片已保存至本地：** `{filename}`\n⏳ 正在让 Antigravity 调用多模态视觉模型进行读图与代码编写...",
            parse_mode="Markdown"
        )
        await execute_agent_task(update, context, prompt, status_msg)

    except Exception as e:
        log(f"❌ 接收并解析图片失败: {e}")
        await status_msg.edit_text(f"❌ 接收并解析图片失败: {e}")


# ==============================================================================
# Telegram 原生快捷指令 Handler
# ==============================================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    log(f"🛠 [Telegram] 用户触发指令: /start")
    ws = get_current_workspace()
    text = (
        "🚀 **欢迎使用 Google Antigravity Telegram Native Bridge**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✨ **零中转·零第三方·直连 Mac 本地 Antigravity IDE**\n\n"
        f"📂 **当前工作区**：`{ws}`\n"
        f"🔗 **绑定 IDE 会话**：`{get_active_conversation_id()}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 **使用方式**：\n"
        "• 直接发送文本：例如 *“在当前项目写一个贪吃蛇”*\n"
        "• 发送报错截图：附带说明 *“帮我看看这个报错怎么解决”*\n"
        "• 发送 `/help` 查看所有快捷管理指令"
    )
    await update.message.reply_text(text, reply_markup=get_workspace_quick_keyboard(), parse_mode="Markdown")


async def cmd_pwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    log(f"🛠 [Telegram] 用户触发指令: /pwd")
    ws = get_current_workspace()
    branch = run_shell("git rev-parse --abbrev-ref HEAD", cwd=ws)
    stat = run_shell("git status -s", cwd=ws)
    stat_summary = f"\n📝 未提交变更: {len(stat.splitlines())} 个文件" if stat and stat != "(无输出)" else "\n✨ 工作区干净"
    alert_text = f"📂 当前工作目录：\n`{ws}`\n\n🌿 Git 分支: `{branch}`{stat_summary}"
    await update.message.reply_text(alert_text, reply_markup=get_workspace_quick_keyboard(), parse_mode="Markdown")


async def cmd_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    log(f"🛠 [Telegram] 用户触发指令: /pin")
    ws = get_current_workspace()
    branch = run_shell("git rev-parse --abbrev-ref HEAD", cwd=ws)
    stat = run_shell("git status -s", cwd=ws)
    has_changes = "有未提交变动 ⚠️" if stat and stat != "(无输出)" else "代码已同步 ✅"
    pin_text = (
        "📌 **Antigravity 状态看板**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📂 **目录**：`{ws}`\n"
        f"🌿 **分支**：`{branch}` ({has_changes})\n"
        f"🔗 **IDE 会话**：`{get_active_conversation_id()}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 点击下方按钮可实时弹窗查看状态："
    )
    sent_msg = await update.message.reply_text(pin_text, reply_markup=get_workspace_quick_keyboard(), parse_mode="Markdown")
    try:
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=sent_msg.message_id)
    except Exception:
        pass


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    log(f"🛠 [Telegram] 用户触发指令: /help")
    help_text = (
        "🛠 **Antigravity 常用指令菜单**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• `/pwd` - 弹窗查看当前绝对路径与 Git 状态\n"
        "• `/pin` - 发送并置顶当前工作区状态条\n"
        "• `/status` - 查看 Git 状态与分支\n"
        "• `/diff` - 查看当前项目未提交的代码变更\n"
        "• `/commit <msg>` - 自动提交代码到 Git\n"
        "• `/open` - 在 Mac 电脑上唤起 Antigravity IDE 窗口\n"
        "• `/workspace <path>` - 切换工作区路径\n"
        "• `/run <command>` - 在工作区执行终端 Shell 命令\n"
        "• 直接发送文本/图片 - 调度 Agent 编写代码与看图修 Bug"
    )
    await update.message.reply_text(help_text, reply_markup=get_workspace_quick_keyboard(), parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    log(f"🛠 [Telegram] 用户触发指令: /status")
    ws = get_current_workspace()
    stat = run_shell("git status", cwd=ws)
    await update.message.reply_text(
        f"📊 **Git 状态 (`{ws}`)**:\n```\n{stat[:3800]}\n```",
        reply_markup=get_workspace_quick_keyboard(),
        parse_mode="Markdown"
    )


async def cmd_diff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    log(f"🛠 [Telegram] 用户触发指令: /diff")
    ws = get_current_workspace()
    diff = run_shell("git diff", cwd=ws)
    if not diff or diff == "(无输出)":
        await update.message.reply_text("✨ 当前工作区没有未提交的代码改动。", reply_markup=get_workspace_quick_keyboard())
        return
    await update.message.reply_text(
        f"📋 **Git Diff 变动详情**:\n```diff\n{diff[:3800]}\n```",
        reply_markup=get_workspace_quick_keyboard(),
        parse_mode="Markdown"
    )


async def cmd_commit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    log(f"🛠 [Telegram] 用户触发指令: /commit")
    msg = " ".join(context.args).strip() if context.args else f"Update via Telegram at {time.strftime('%Y-%m-%d %H:%M:%S')}"
    ws = get_current_workspace()
    run_shell("git add .", cwd=ws)
    out = run_shell(f'git commit -m "{msg}"', cwd=ws)
    log(f"✅ Git 提交完成: {msg}")
    await update.message.reply_text(f"✅ **Git 提交结果**:\n```\n{out}\n```", reply_markup=get_workspace_quick_keyboard(), parse_mode="Markdown")


async def cmd_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    log(f"🛠 [Telegram] 用户触发指令: /open")
    ws = get_current_workspace()
    success, msg = open_ide_window(ws)
    await update.message.reply_text(f"🖥 {msg}", reply_markup=get_workspace_quick_keyboard())


async def cmd_workspace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    if not context.args:
        ws = get_current_workspace()
        desktop_dirs = []
        try:
            desktop = Path.home() / "Desktop"
            for item in desktop.iterdir():
                if item.is_dir() and not item.name.startswith(".") and not item.name.endswith(".app"):
                    desktop_dirs.append(f"`/workspace {item}`")
        except Exception:
            pass

        recs = "\n".join(desktop_dirs[:5]) if desktop_dirs else "`无`"
        await update.message.reply_text(
            f"📂 **当前工作区**：\n`{ws}`\n\n"
            f"💡 **快捷切换指令**：\n`/workspace /绝对路径/或/相对路径`\n\n"
            f"📁 **桌面候选项目（点击可复制）**：\n{recs}",
            reply_markup=get_workspace_quick_keyboard(),
            parse_mode="Markdown",
        )
        return

    new_path = " ".join(context.args).strip()
    p = Path(new_path).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        await update.message.reply_text(f"❌ 路径不存在或不是文件夹：`{p}`", parse_mode="Markdown")
        return

    RUNTIME_STATE["current_workspace"] = str(p)
    cfg = load_config()
    cfg["default_workspace"] = str(p)
    save_config(cfg)
    open_ide_window(str(p))
    log(f"📂 工作区已切换为: {p}")
    await update.message.reply_text(
        f"✅ **工作区已切换为**：`{p}`\n🖥 **已自动在 Mac 屏幕上唤起 Antigravity IDE 加载新项目！**",
        reply_markup=get_workspace_quick_keyboard(),
        parse_mode="Markdown"
    )


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    if not context.args:
        await update.message.reply_text("💡 请指定要运行的命令，例如：`/run ls -la`")
        return
    cmd = " ".join(context.args)
    ws = get_current_workspace()
    log(f"💻 [Terminal] 执行命令: {cmd} (目录: {ws})")
    status_msg = await update.message.reply_text(f"⏳ 正在执行：`{cmd}`...", parse_mode="Markdown")
    out = run_shell(cmd, cwd=ws)
    log(f"💻 [Terminal] 命令执行完毕")
    await status_msg.edit_text(f"💻 **执行结果** (`{cmd}`):\n```\n{out[:3800]}\n```", parse_mode="Markdown")


# ==============================================================================
# 回调按钮（手机原生弹窗 show_alert=True）
# ==============================================================================
async def callback_settings_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "popup_workspace_info":
        ws = get_current_workspace()
        branch = run_shell("git rev-parse --abbrev-ref HEAD", cwd=ws)
        stat = run_shell("git status -s", cwd=ws)
        stat_summary = f"\n📝 未提交变更: {len(stat.splitlines())} 个文件" if stat and stat != "(无输出)" else "\n✨ 工作区干净"
        alert_text = f"📂 当前工作目录：\n{ws}\n\n🌿 Git 分支: {branch}{stat_summary}"
        await query.answer(alert_text, show_alert=True)
        log("📱 用户在手机上弹窗查看了工作区状态")
        return
    elif data == "popup_git_diff":
        ws = get_current_workspace()
        stat = run_shell("git diff --stat", cwd=ws)
        if not stat or stat == "(无输出)":
            await query.answer("✨ 当前没有未提交的代码变动", show_alert=True)
        else:
            await query.answer(f"📋 Git Diff 摘要：\n{stat[:180]}", show_alert=True)
        log("📱 用户在手机上弹窗查看了 Git Diff 摘要")
        return
    elif data == "trigger_open_ide":
        success, msg = open_ide_window()
        await query.answer(f"🖥 {msg}", show_alert=True)
        return


# ==============================================================================
# 启动入口与自愈重连轮询
# ==============================================================================
def main():
    # 使用操作系统级 fcntl 文件排他锁，彻底杜绝多实例竞争与 Telegram ConflictError
    global lock_fd
    lock_file_path = SCRIPT_DIR / "bridge.lock"
    try:
        lock_fd = open(lock_file_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
    except (IOError, BlockingIOError, OSError):
        log("ℹ️ 检测到后台已有活跃的 bridge_engine 守护进程正在运行，本启动请求自动优雅退出。")
        sys.exit(0)

    cfg = load_config()
    token = cfg.get("telegram_token", "").strip()

    if not token:
        log("❌ 错误: 未在 config.json 中配置 telegram_token！")
        sys.exit(1)

    proxy_url = cfg.get("proxy", "").strip() or None
    if proxy_url:
        log(f"🌐 使用代理连接 Telegram: {proxy_url}")

    request_obj = HTTPXRequest(
        proxy=proxy_url,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    async def post_init(application):
        commands = [
            BotCommand("start", "🚀 启动与欢迎信息"),
            BotCommand("pwd", "📂 弹窗查看当前工作目录"),
            BotCommand("pin", "📌 置顶当前工作区状态条"),
            BotCommand("status", "📊 查看工作区与 Git 分支"),
            BotCommand("diff", "📋 审查未提交代码 Diff"),
            BotCommand("commit", "✅ 提交代码变动到 Git"),
            BotCommand("open", "🖥 在电脑上打开 IDE 窗口"),
            BotCommand("workspace", "📂 查看或切换项目目录"),
            BotCommand("run", "💻 运行本地终端命令"),
            BotCommand("help", "❓ 查看全部指令帮助"),
        ]
        try:
            await application.bot.set_my_commands(commands)
            log("✨ 已自动向 Telegram 注册客户端原生快捷指令菜单！")
        except Exception as e:
            log(f"⚠️ 注册指令菜单失败: {e}")

    builder = ApplicationBuilder().token(token).request(request_obj).post_init(post_init)
    app = builder.build()

    # 注册 Handler
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pwd", cmd_pwd))
    app.add_handler(CommandHandler("pin", cmd_pin))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("diff", cmd_diff))
    app.add_handler(CommandHandler("commit", cmd_commit))
    app.add_handler(CommandHandler("open", cmd_open))
    app.add_handler(CommandHandler("workspace", cmd_workspace))
    app.add_handler(CommandHandler("cd", cmd_workspace))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CallbackQueryHandler(callback_settings_toggle))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_agent_chat))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, handle_agent_photo))

    log("=================================================================")
    log("🚀 Antigravity TG Bridge 核心引擎已就绪！")
    log(f"📂 默认工作区: {get_current_workspace()}")
    log(f"🔗 绑定 IDE 会话: {get_active_conversation_id()}")
    log("=================================================================")

    # 具备无限自动重连保护的守护轮询
    try:
        app.run_polling(
            drop_pending_updates=False,
            poll_interval=0.5,
            timeout=15,
            bootstrap_retries=-1,
            stop_signals=None,
        )
    except Exception as e:
        log(f"⚠️ Telegram 长轮询异常退出: {e}")


if __name__ == "__main__":
    main()
