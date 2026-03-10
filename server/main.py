import hashlib
import hmac
import json
import os
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
ALLOWED_USERNAME = os.getenv("ALLOWED_USERNAME", "kovalchukym")
POLL_SECRET = os.getenv("POLL_SECRET", "change-me-poll-secret")
PORT = int(os.getenv("PORT", "8000"))
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI(title="PC Control Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Черга команд (хмарний сервер ↔ локальний клієнт) ────────────────────────
# {cmd_id: {type, payload, status, result, ts}}
_cmd_queue: dict[str, dict] = {}

# Черга очікуючих Claude hook дозволів
# {hook_id: {tool, description, ts, approved: None|bool}}
_hook_queue: dict[str, dict] = {}

# Chat ID зберігається після першого /start від дозволеного юзера
_allowed_chat_id: Optional[int] = None


# ─── Статика (Mini App) ───────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent.parent

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/style.css")
async def serve_css():
    return FileResponse(STATIC_DIR / "style.css")

@app.get("/app.js")
async def serve_js():
    return FileResponse(STATIC_DIR / "app.js")


# ─── Валідація Telegram initData ──────────────────────────────────────────────
def validate_init_data(init_data: str) -> dict:
    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise ValueError("Відсутній hash")

    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise ValueError("Невірний підпис")

    auth_date = int(parsed.get("auth_date", 0))
    if time.time() - auth_date > 86400:
        raise ValueError("initData застаріло")

    user = json.loads(parsed.get("user", "{}"))
    if user.get("username") != ALLOWED_USERNAME:
        raise ValueError("Доступ заборонено")
    return user


def auth_user(request: Request) -> dict:
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data:
        raise HTTPException(status_code=401, detail="Відсутній X-Init-Data")
    try:
        return validate_init_data(init_data)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


def auth_client(request: Request):
    secret = request.headers.get("X-Poll-Secret", "")
    if secret != POLL_SECRET:
        raise HTTPException(status_code=403, detail="Невірний секрет")


# ─── Telegram Bot Webhook ─────────────────────────────────────────────────────
async def send_tg(chat_id: int, text: str, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        await client.post(f"{TG_API}/sendMessage", json=payload)


@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = await request.json()

    # Callback (кнопки Claude hook або inline)
    if cb := update.get("callback_query"):
        if cb["from"].get("username") != ALLOWED_USERNAME:
            return {"ok": True}

        data = cb.get("data", "")

        if data.startswith("claude_"):
            _, action, hook_id = data.split("_", 2)
            if hook_id in _hook_queue:
                _hook_queue[hook_id]["approved"] = (action == "approve")
            answer = "✅ Дозволено" if action == "approve" else "❌ Заборонено"
            async with httpx.AsyncClient() as client:
                await client.post(f"{TG_API}/answerCallbackQuery",
                                  json={"callback_query_id": cb["id"], "text": answer})
                await client.post(f"{TG_API}/editMessageReplyMarkup",
                                  json={"chat_id": cb["message"]["chat"]["id"],
                                        "message_id": cb["message"]["message_id"],
                                        "reply_markup": {"inline_keyboard": []}})
        return {"ok": True}

    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if not chat_id or msg.get("from", {}).get("username") != ALLOWED_USERNAME:
        return {"ok": True}

    global _allowed_chat_id
    _allowed_chat_id = chat_id

    if text == "/start":
        server_url = os.getenv("SERVER_URL", "")
        webapp_url = server_url or "https://pc-control.up.railway.app"
        await send_tg(chat_id, (
            "👋 <b>PC Control</b>\n\n"
            "Керуй своїм ПК прямо з Telegram."
        ), reply_markup={
            "inline_keyboard": [[{
                "text": "🖥️ Відкрити панель",
                "web_app": {"url": webapp_url}
            }]]
        })

    elif text == "/status":
        pending = sum(1 for c in _cmd_queue.values() if c["status"] == "pending")
        await send_tg(chat_id, f"📊 Команд у черзі: {pending}")

    return {"ok": True}


# ─── API для Mini App (авторизація через initData) ───────────────────────────
async def enqueue_and_wait(key: str, extra: dict = {}, timeout: int = 15) -> dict:
    cmd_id = str(uuid.uuid4())
    _cmd_queue[cmd_id] = {"key": key, **extra, "status": "pending", "result": None, "ts": time.time(), "type": "command"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.3)
        cmd = _cmd_queue.get(cmd_id, {})
        if cmd.get("status") == "done":
            return {"ok": cmd.get("ok", False), "output": cmd.get("result", "")}
    return {"ok": False, "output": "Таймаут — клієнт на ПК не відповідає"}


@app.post("/send")
async def send_text(request: Request):
    """Надіслати текст у активне вікно на ПК."""
    auth_user(request)
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Порожній текст")
    return await enqueue_and_wait("type_text", {"text": text})


@app.get("/status")
async def system_status(request: Request):
    auth_user(request)
    return await enqueue_and_wait("system_info", timeout=10)


@app.get("/claude/pending")
async def claude_pending(request: Request):
    auth_user(request)
    items = [
        {"id": k, "tool": v["tool"], "description": v["description"]}
        for k, v in _hook_queue.items()
        if v.get("approved") is None
    ]
    return {"pending": items}


@app.post("/claude/decide/{hook_id}")
async def claude_decide(hook_id: str, request: Request):
    auth_user(request)
    body = await request.json()
    if hook_id in _hook_queue:
        _hook_queue[hook_id]["approved"] = body.get("approved", False)
    return {"ok": True}


# ─── API для локального клієнта на ПК (авторизація через POLL_SECRET) ─────────
@app.get("/api/poll")
async def poll_commands(request: Request):
    """Локальний клієнт тут отримує команди для виконання."""
    auth_client(request)
    pending = [
        {k2: v2 for k2, v2 in v.items() if k2 not in ("status", "result", "ts")} | {"id": k}
        for k, v in _cmd_queue.items()
        if v["status"] == "pending"
    ]
    return {"commands": pending}


@app.post("/api/result/{cmd_id}")
async def post_result(cmd_id: str, request: Request):
    """Локальний клієнт надсилає результат виконання."""
    auth_client(request)
    body = await request.json()
    if cmd_id in _cmd_queue:
        _cmd_queue[cmd_id]["status"] = "done"
        _cmd_queue[cmd_id]["ok"] = body.get("ok", False)
        _cmd_queue[cmd_id]["result"] = body.get("output", "")
    return {"ok": True}


@app.post("/api/claude/hook")
async def claude_hook_from_client(request: Request):
    """Локальний клієнт надсилає Claude hook → бот надсилає в Telegram."""
    auth_client(request)
    body = await request.json()
    hook_id = str(uuid.uuid4())
    tool = body.get("tool", "?")
    description = body.get("description", "")

    _hook_queue[hook_id] = {
        "tool": tool,
        "description": description,
        "approved": None,
        "ts": time.time(),
    }

    if _allowed_chat_id:
        await send_tg(_allowed_chat_id, (
            f"🤖 <b>Claude хоче виконати дію</b>\n\n"
            f"<b>Інструмент:</b> <code>{tool}</code>\n"
            f"<b>Деталі:</b> {description[:400]}"
        ), reply_markup={"inline_keyboard": [[
            {"text": "✅ Дозволити", "callback_data": f"claude_approve_{hook_id}"},
            {"text": "❌ Заборонити", "callback_data": f"claude_deny_{hook_id}"},
        ]]})

    return {"ok": True, "hook_id": hook_id}


@app.get("/api/claude/result/{hook_id}")
async def claude_hook_result(hook_id: str, request: Request):
    """Локальний hook скрипт перевіряє результат."""
    auth_client(request)
    item = _hook_queue.get(hook_id)
    if not item:
        return {"ready": False, "approved": None}
    approved = item.get("approved")
    return {"ready": approved is not None, "approved": approved}


import asyncio

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
