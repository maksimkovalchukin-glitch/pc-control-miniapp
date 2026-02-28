"""
Локальний клієнт — запускається на ПК.
Поллінгує хмарний сервер і виконує команди локально.
"""
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Завантажити .env
env_file = Path(__file__).parent.parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SERVER_URL = os.getenv("SERVER_URL", "").rstrip("/")
POLL_SECRET = os.getenv("POLL_SECRET", "change-me-poll-secret")
POLL_INTERVAL = 2

if not SERVER_URL:
    print("SERVER_URL не задано в .env")
    sys.exit(1)


def type_text(text: str) -> dict:
    """Вставити текст в активне вікно через буфер обміну."""
    try:
        import pyperclip
        import pyautogui
        pyperclip.copy(text)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        return {"ok": True, "output": f"Вставлено: {text[:60]}"}
    except Exception as e:
        return {"ok": False, "output": str(e)}


def get_system_info() -> str:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:/")
        return (
            f"CPU: {cpu}%\n"
            f"RAM: {ram.used // 1024 // 1024} MB / {ram.total // 1024 // 1024} MB ({ram.percent}%)\n"
            f"Диск C: {disk.used // 1024 ** 3} GB / {disk.total // 1024 ** 3} GB ({disk.percent}%)"
        )
    except ImportError:
        return "psutil не встановлено"


def run_command(cmd: dict) -> dict:
    key = cmd.get("key", "")

    if key == "system_info":
        return {"ok": True, "output": get_system_info()}

    if key == "type_text":
        return type_text(cmd.get("text", ""))

    return {"ok": False, "output": f"Невідома команда: {key}"}


def api_get(path: str) -> dict:
    req = urllib.request.Request(
        SERVER_URL + path,
        headers={"X-Poll-Secret": POLL_SECRET},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def api_post(path: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        SERVER_URL + path,
        data=body,
        headers={"Content-Type": "application/json", "X-Poll-Secret": POLL_SECRET},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    print(f"PC Control client started")
    print(f"Server: {SERVER_URL}")

    fail_count = 0
    while True:
        try:
            data = api_get("/api/poll")
            for cmd in data.get("commands", []):
                print(f">> {cmd.get('key')}: {cmd.get('text', '')[:50]}")
                result = run_command(cmd)
                api_post(f"/api/result/{cmd['id']}", result)
            fail_count = 0
        except Exception as e:
            fail_count += 1
            if fail_count % 10 == 1:
                print(f"Server unavailable: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
