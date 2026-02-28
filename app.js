const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

// ─── Конфігурація ─────────────────────────────────────────────────────────────
const STORAGE_KEY = "pc_control_api_url";

function getApiUrl() {
  return localStorage.getItem(STORAGE_KEY) || "";
}

function getInitData() {
  return tg?.initData || "";
}

async function apiRequest(method, path, body = null) {
  const url = getApiUrl();
  if (!url) {
    showConfigPanel();
    throw new Error("API URL не налаштовано");
  }
  const opts = {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Init-Data": getInitData(),
    },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Помилка запиту");
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

// ─── Вивід ────────────────────────────────────────────────────────────────────
function showOutput(text, ok = true) {
  const card = document.getElementById("output-card");
  const pre = document.getElementById("output-text");
  pre.textContent = text;
  pre.style.color = ok ? "var(--text)" : "var(--danger)";
  card.style.display = "block";
  card.scrollIntoView({ behavior: "smooth" });
}

// ─── Команди ─────────────────────────────────────────────────────────────────
async function loadCommands() {
  try {
    const data = await apiRequest("GET", "/commands");
    renderCommands(data.commands);
  } catch (e) {
    // мовчки — якщо немає API URL
  }
}

function renderCommands(commands) {
  const grid = document.getElementById("commands-grid");
  grid.innerHTML = "";
  for (const cmd of commands) {
    const btn = document.createElement("button");
    btn.className = "cmd-btn";
    btn.innerHTML = `<span class="icon">${cmd.icon}</span><span class="label">${cmd.label}</span>`;
    btn.addEventListener("click", () => executeCommand(cmd.key, btn));
    grid.appendChild(btn);
  }
}

async function executeCommand(key, btn) {
  btn.classList.add("running");
  btn.disabled = true;
  try {
    const data = await apiRequest("POST", "/execute", { command: key });
    if (data.output && data.output.trim()) {
      showOutput(data.output, data.ok);
    } else {
      showToast(data.ok ? "✅ Виконано" : "❌ Помилка");
    }
  } catch (e) {
    showToast("❌ " + e.message);
  } finally {
    btn.classList.remove("running");
    btn.disabled = false;
  }
}

// ─── Статус системи ───────────────────────────────────────────────────────────
async function loadStatus() {
  const container = document.getElementById("status-container");
  try {
    const data = await apiRequest("GET", "/status");
    const lines = data.info.split("\n");
    container.innerHTML = lines.map(line => {
      const [label, value] = line.split(": ");
      return `<div class="status-row">
        <span class="status-label">${label}</span>
        <span class="status-value">${value ?? ""}</span>
      </div>`;
    }).join("");
  } catch (e) {
    container.innerHTML = `<span class="status-label">Немає з'єднання</span>`;
  }
}

// ─── Claude Hooks ─────────────────────────────────────────────────────────────
let hooksInterval;

async function loadPendingHooks() {
  const container = document.getElementById("hooks-container");
  try {
    const data = await apiRequest("GET", "/claude/pending");
    renderHooks(data.pending);
  } catch {
    // ігноруємо
  }
}

function renderHooks(items) {
  const container = document.getElementById("hooks-container");
  if (!items.length) {
    container.innerHTML = '<p class="no-pending">Немає очікуючих дій</p>';
    return;
  }
  container.innerHTML = items.map(item => `
    <div class="hook-item" data-id="${item.id}">
      <div class="hook-tool">🔧 ${item.tool}</div>
      <div class="hook-desc">${item.description}</div>
      <div class="hook-actions">
        <button class="btn-approve" onclick="decideHook('${item.id}', true)">✅ Дозволити</button>
        <button class="btn-deny" onclick="decideHook('${item.id}', false)">❌ Заборонити</button>
      </div>
    </div>
  `).join("");
}

window.decideHook = async function (hookId, approved) {
  try {
    await apiRequest("POST", `/claude/decide/${hookId}`, { approved });
    showToast(approved ? "✅ Дозволено" : "❌ Заборонено");
    loadPendingHooks();
  } catch (e) {
    showToast("❌ " + e.message);
  }
};

// ─── Конфіг панель ───────────────────────────────────────────────────────────
function showConfigPanel() {
  document.getElementById("config-panel").style.display = "block";
  document.getElementById("api-url-input").value = getApiUrl();
}

document.getElementById("save-config-btn").addEventListener("click", () => {
  const url = document.getElementById("api-url-input").value.trim().replace(/\/$/, "");
  localStorage.setItem(STORAGE_KEY, url);
  document.getElementById("config-panel").style.display = "none";
  showToast("✅ Збережено");
  init();
});

document.getElementById("config-btn").addEventListener("click", showConfigPanel);

// ─── Ініціалізація ────────────────────────────────────────────────────────────
async function init() {
  if (!getApiUrl()) {
    showConfigPanel();
    return;
  }
  await Promise.all([loadCommands(), loadStatus(), loadPendingHooks()]);

  clearInterval(hooksInterval);
  hooksInterval = setInterval(loadPendingHooks, 5000);
}

init();
