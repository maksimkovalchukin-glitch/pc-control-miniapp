const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const API_URL = window.location.origin;

function getInitData() { return tg?.initData || ""; }

async function apiRequest(method, path, body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json", "X-Init-Data": getInitData() },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API_URL + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Помилка");
  }
  return res.json();
}

// ─── Toast ────────────────────────────────────────────────────────────────────
const toast = document.getElementById("toast");
let toastTimer;
function showToast(msg) {
  clearTimeout(toastTimer);
  toast.textContent = msg;
  toast.classList.add("show");
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2500);
}

// ─── Надіслати текст ──────────────────────────────────────────────────────────
const sendBtn = document.getElementById("send-btn");
const msgInput = document.getElementById("msg-input");

async function sendText() {
  const text = msgInput.value.trim();
  if (!text) return;
  sendBtn.disabled = true;
  sendBtn.textContent = "Надсилаю...";
  try {
    await apiRequest("POST", "/send", { text });
    msgInput.value = "";
    showToast("✅ Вставлено у вікно");
  } catch (e) {
    showToast("❌ " + e.message);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "Надіслати ↵";
  }
}

sendBtn.addEventListener("click", sendText);
msgInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendText();
});

// ─── Статус системи ───────────────────────────────────────────────────────────
async function loadStatus() {
  const c = document.getElementById("status-container");
  try {
    const data = await apiRequest("GET", "/status");
    c.innerHTML = (data.output || "").split("\n").map(line => {
      const [label, ...rest] = line.split(": ");
      return `<div class="status-row">
        <span class="status-label">${label}</span>
        <span class="status-value">${rest.join(": ")}</span>
      </div>`;
    }).join("");
  } catch {
    c.innerHTML = `<span class="status-label">ПК офлайн або клієнт не запущено</span>`;
  }
}

document.getElementById("refresh-btn").addEventListener("click", loadStatus);

// ─── Claude Hooks ─────────────────────────────────────────────────────────────
async function loadPendingHooks() {
  try {
    const data = await apiRequest("GET", "/claude/pending");
    renderHooks(data.pending || []);
  } catch { /* ігноруємо */ }
}

function renderHooks(items) {
  const c = document.getElementById("hooks-container");
  if (!items.length) {
    c.innerHTML = '<p class="no-pending">Немає очікуючих дій</p>';
    return;
  }
  c.innerHTML = items.map(item => `
    <div class="hook-item">
      <div class="hook-tool">🔧 ${item.tool}</div>
      <div class="hook-desc">${item.description}</div>
      <div class="hook-actions">
        <button class="btn-approve" onclick="decide('${item.id}',true)">✅ Дозволити</button>
        <button class="btn-deny" onclick="decide('${item.id}',false)">❌ Заборонити</button>
      </div>
    </div>`).join("");
}

window.decide = async (id, approved) => {
  try {
    await apiRequest("POST", `/claude/decide/${id}`, { approved });
    showToast(approved ? "✅ Дозволено" : "❌ Заборонено");
    loadPendingHooks();
  } catch (e) { showToast("❌ " + e.message); }
};

// ─── Init ─────────────────────────────────────────────────────────────────────
loadStatus();
loadPendingHooks();
setInterval(loadPendingHooks, 4000);
setInterval(loadStatus, 60000);
