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
import urllib.error
from pathlib import Path

# Фікс для Windows терміналу (cp1251 не підтримує емоджі)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Завантажити .env якщо є
env_file = Path(__file__).parent.parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SERVER_URL = os.getenv("SERVER_URL", "").rstrip("/")
POLL_SECRET = os.getenv("POLL_SECRET", "change-me-poll-secret")
POLL_INTERVAL = 2  # секунди між запитами

if not SERVER_URL:
    print("❌ SERVER_URL не задано в .env")
    sys.exit(1)

VSCODE = r"C:\Users\maksi\AppData\Local\Programs\Microsoft VS Code\Code.exe"

COMMANDS = {
    "open_vscode": {
        "cmd": [VSCODE, "c:\\claude project"],
        "capture": False,
    },
    "open_terminal": {
        "cmd": ["cmd.exe", "/c", "start", "cmd.exe"],
        "capture": False,
        "shell": True,
    },
    "git_status": {
        "cmd": ["git", "-C", "c:\\claude project", "status"],
        "capture": True,
    },
    "system_info": {
        "builtin": "system_info",
    },
    "restart_tg_service": {
        "cmd": [sys.executable, "c:\\claude project\\rayton_tg_service\\main.py"],
        "capture": False,
    },
}


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
        return "psutil не встановлено. Запусти: pip install psutil"


def run_command(key: str) -> dict:
    if key not in COMMANDS:
        return {"ok": False, "output": f"Невідома команда: {key}"}

    defn = COMMANDS[key]

    if defn.get("builtin") == "system_info":
        return {"ok": True, "output": get_system_info()}

    capture = defn.get("capture", False)
    try:
        proc = subprocess.Popen(
            defn["cmd"],
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
            shell=defn.get("shell", False),
            text=True,
        )
        if capture:
            stdout, stderr = proc.communicate(timeout=10)
            return {"ok": proc.returncode == 0, "output": (stdout or stderr or "").strip()[:1000]}
        return {"ok": True, "output": f"✅ Запущено"}
    except Exception as e:
        return {"ok": False, "output": str(e)}


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
    print(f"🟢 PC Control клієнт запущено")
    print(f"   Сервер: {SERVER_URL}")
    print(f"   Поллінг кожні {POLL_INTERVAL} сек\n")

    fail_count = 0

    while True:
        try:
            data = api_get("/api/poll")
            commands = data.get("commands", [])
            fail_count = 0

            for cmd in commands:
                cmd_id = cmd["id"]
                key = cmd["key"]
                print(f"▶ Виконую: {key}")
                result = run_command(key)
                api_post(f"/api/result/{cmd_id}", result)
                status = "✅" if result["ok"] else "❌"
                print(f"  {status} {result['output'][:80]}")

        except Exception as e:
            fail_count += 1
            if fail_count % 10 == 1:
                print(f"⚠ Сервер недоступний: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
