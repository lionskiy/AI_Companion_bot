from fastapi import APIRouter
from fastapi.responses import HTMLResponse

ui_router = APIRouter(prefix="/admin/ui", tags=["admin-ui"])

_HTML = """<!DOCTYPE html>
<html lang="ru" data-bs-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mirror Admin</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<style>
/* ── Base ── */
:root{
  --bg-base:#0d1117;
  --bg-surface:#161b22;
  --bg-elevated:#1c2230;
  --border:#30363d;
  --text-primary:#e6edf3;
  --text-secondary:#8b949e;
  --text-muted:#6e7681;
  --accent:#7c3aed;
  --accent-hover:#6d28d9;
  --accent-glow:rgba(124,58,237,.3);
}
body{background:var(--bg-base);color:var(--text-primary);min-height:100vh;font-size:.92rem}

/* ── Bootstrap dark overrides ── */
.form-control,.form-select{background:var(--bg-elevated)!important;border-color:var(--border)!important;color:var(--text-primary)!important}
.form-control:focus,.form-select:focus{border-color:var(--accent)!important;box-shadow:0 0 0 .2rem var(--accent-glow)!important;background:var(--bg-elevated)!important;color:var(--text-primary)!important}
.form-control::placeholder{color:var(--text-muted)!important}
.form-control:disabled,.form-select:disabled{background:#12161d!important;color:var(--text-muted)!important;opacity:.6}
.form-check-input{background-color:var(--bg-elevated);border-color:var(--border)}
.input-group-text{background:var(--bg-elevated);border-color:var(--border);color:var(--text-secondary)}
label,.form-label{color:#c0c8d4!important}

/* ── Sidebar ── */
.sidebar{width:220px;min-height:100vh;background:var(--bg-surface);border-right:1px solid var(--border);position:fixed;top:0;left:0;z-index:100;display:flex;flex-direction:column}
.sidebar .logo{padding:20px 16px 12px;font-size:1.15rem;font-weight:700;color:#c084fc;border-bottom:1px solid var(--border)}
.sidebar .logo span{font-size:.72rem;color:var(--text-muted);display:block;font-weight:400;margin-top:2px}
.sidebar .nav-link{color:#9ca3af;padding:9px 14px;border-radius:7px;margin:1px 8px;font-size:.875rem;transition:background .15s,color .15s}
.sidebar .nav-link:hover,.sidebar .nav-link.active{background:#21262d;color:#f0f6fc}
.sidebar .nav-link i{width:18px;margin-right:6px}
.sidebar-footer{padding:12px 8px;border-top:1px solid var(--border);margin-top:auto}

/* ── Main ── */
.main{margin-left:220px;padding:28px 32px}

/* ── Cards ── */
.card{background:var(--bg-surface);border:1px solid var(--border);border-radius:10px}
.card-header{background:var(--bg-elevated);border-bottom:1px solid var(--border);border-radius:10px 10px 0 0!important;font-weight:600;color:var(--text-primary);padding:.75rem 1rem}

/* ── Stat cards ── */
.stat-card{border-radius:8px;padding:.55rem .75rem;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.15rem;text-align:center}
.stat-card.blue{background:linear-gradient(135deg,#1a1f4e,#252d6e);border:1px solid #3d4fb5}
.stat-card.green{background:linear-gradient(135deg,#0a2318,#0d3321);border:1px solid #1a5e38}
.stat-card.purple{background:linear-gradient(135deg,#21104a,#2d1666);border:1px solid #5b2fa6}
.stat-card.rose{background:linear-gradient(135deg,#3a0a18,#5a1228);border:1px solid #8b1a35}
.stat-num{font-size:1.45rem;font-weight:700;color:#f1f5f9;line-height:1;white-space:nowrap}
.stat-label{font-size:.68rem;color:#94a3b8;letter-spacing:.04em;text-transform:uppercase;line-height:1.3}

/* ── Tables ── */
.table{color:var(--text-primary);--bs-table-bg:transparent;--bs-table-striped-bg:rgba(255,255,255,.02);--bs-table-hover-bg:rgba(255,255,255,.04)}
.table th{border-color:var(--border);color:var(--text-muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;font-weight:600;padding:.6rem .75rem;background:var(--bg-elevated)}
.table td{border-color:var(--border);color:var(--text-primary);vertical-align:middle}
.table-hover tbody tr:hover td{background:rgba(124,58,237,.06)}

/* ── Buttons ── */
.btn-primary{background:var(--accent);border-color:var(--accent);font-weight:500}
.btn-primary:hover,.btn-primary:focus{background:var(--accent-hover);border-color:var(--accent-hover)}
.btn-outline-secondary{border-color:var(--border);color:#9ca3af}
.btn-outline-secondary:hover{background:var(--bg-elevated);color:var(--text-primary);border-color:#6b7280}
.btn-save{background:#1a3a1a;border:1px solid #2e6b2e;color:#6fcf6f;font-size:.8rem;padding:3px 12px;border-radius:6px;white-space:nowrap}
.btn-save:hover{background:#22442a;border-color:#4caf50;color:#90ee90}

/* ── Routing table ── */
.routing-row td{padding:.65rem .75rem}
.routing-row:hover td{background:rgba(124,58,237,.05)}
.task-label{font-weight:500;color:var(--text-primary);font-size:.85rem}
.task-code{font-size:.72rem;color:var(--text-muted);font-family:monospace}
.provider-btn{padding:3px 10px;font-size:.78rem;border-radius:20px;border:1px solid var(--border);background:var(--bg-elevated);color:var(--text-secondary);cursor:pointer;transition:all .15s}
.provider-btn.active-openai{background:#0a2a1a;border-color:#22c55e;color:#4ade80}
.provider-btn.active-anthropic{background:#1a1230;border-color:#a78bfa;color:#c4b5fd}

/* ── Misc ── */
.section{display:none}.section.active{display:block}
.toast-container{position:fixed;bottom:20px;right:20px;z-index:9999}
pre{background:#0a0e14;border:1px solid var(--border);border-radius:8px;padding:12px;font-size:.8rem;color:#a5f3fc}
textarea.form-control{font-family:monospace;font-size:.85rem}
.badge{font-weight:500}
.text-secondary{color:var(--text-secondary)!important}

/* ── Login ── */
#login-screen{position:fixed;inset:0;background:var(--bg-base);display:flex;align-items:center;justify-content:center;z-index:9999}
.login-box{background:var(--bg-surface);border:1px solid var(--border);border-radius:16px;padding:40px;width:360px}
.login-box h4{color:#c084fc;font-weight:700}
@keyframes kb-pulse{0%,100%{opacity:.5;transform:scaleX(.7)}50%{opacity:1;transform:scaleX(1)}}
/* ── Config page ── */
.cfg-section-hdr{font-size:.69rem;text-transform:uppercase;letter-spacing:.07em;color:#6e7681;font-weight:600;margin-bottom:.6rem;padding-bottom:.3rem;border-bottom:1px solid #1c2230}
.cfg-item-title{font-size:.83rem;font-weight:500;color:#c9d1d9;line-height:1.3}
.cfg-item-syskey{font-size:.69rem;color:#6e7681;font-family:monospace;font-weight:400}
.cfg-item-desc{font-size:.73rem;color:#8b949e;line-height:1.38}
.cfg-prompt-card{border-color:#252d40!important;background:#0f141d!important}
.cfg-textarea{font-family:monospace;font-size:.8rem!important}
.cfg-compact{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:.55rem .65rem;height:100%}
.cfg-ctrl-row{display:flex;align-items:center;gap:.4rem}
.cfg-ctrl-small{width:88px!important;flex-shrink:0}
.cfg-save-sm{padding:2px 8px!important;font-size:.73rem!important;flex-shrink:0;white-space:nowrap}
</style>
</head>
<body>

<!-- Login -->
<div id="login-screen">
  <div class="login-box">
    <h4 class="mb-1"><i class="bi bi-shield-lock"></i> Mirror Admin</h4>
    <p class="text-secondary mb-4" style="font-size:.85rem">Введи логин и пароль</p>
    <div class="mb-3">
      <input type="text" id="login-input" class="form-control mb-2" placeholder="Логин" autocomplete="username">
      <input type="password" id="password-input" class="form-control" placeholder="Пароль" autocomplete="current-password">
    </div>
    <button class="btn btn-primary w-100" onclick="doLogin()">Войти</button>
    <div id="login-error" class="text-danger mt-2" style="font-size:.85rem"></div>
  </div>
</div>

<!-- Sidebar -->
<div class="sidebar">
  <div class="logo">Mirror Admin<span>Stage 1</span></div>
  <nav class="nav flex-column mt-2">
    <a class="nav-link active" href="#stats"><i class="bi bi-bar-chart-line"></i> Dashboard</a>
    <a class="nav-link" href="#config"><i class="bi bi-sliders"></i> Конфиг</a>
    <a class="nav-link" href="#routing"><i class="bi bi-diagram-3"></i> LLM Routing</a>
    <a class="nav-link" href="#quota"><i class="bi bi-speedometer2"></i> Квоты</a>
    <a class="nav-link" href="#users"><i class="bi bi-people"></i> Пользователи</a>
    <a class="nav-link" href="#kb"><i class="bi bi-database"></i> База знаний</a>
    <div style="border-top:1px solid #30363d;margin:8px 8px 4px;padding-top:8px;font-size:.7rem;color:#8b949e;text-transform:uppercase;letter-spacing:.05em;padding-left:8px">Инфраструктура</div>
    <a class="nav-link" href="http://localhost:19104/dashboard" target="_blank"><i class="bi bi-boxes"></i> Qdrant <i class="bi bi-box-arrow-up-right" style="font-size:.65rem;opacity:.5"></i></a>
    <a class="nav-link" href="http://localhost:19107" target="_blank"><i class="bi bi-hdd-network"></i> RabbitMQ <i class="bi bi-box-arrow-up-right" style="font-size:.65rem;opacity:.5"></i></a>
    <a class="nav-link" href="http://localhost:19109" target="_blank"><i class="bi bi-lightning-charge"></i> NATS <i class="bi bi-box-arrow-up-right" style="font-size:.65rem;opacity:.5"></i></a>
    <a class="nav-link" href="http://localhost:19101" target="_blank"><i class="bi bi-window"></i> Appsmith <i class="bi bi-box-arrow-up-right" style="font-size:.65rem;opacity:.5"></i></a>
    <a class="nav-link" href="http://localhost:19100/docs" target="_blank"><i class="bi bi-code-slash"></i> API Docs <i class="bi bi-box-arrow-up-right" style="font-size:.65rem;opacity:.5"></i></a>
  </nav>
  <div class="sidebar-footer">
    <button class="btn btn-outline-secondary btn-sm w-100" onclick="logout()"><i class="bi bi-box-arrow-left"></i> Выйти</button>
  </div>
</div>

<!-- Main -->
<div class="main">

  <!-- Stats -->
  <div id="sec-stats" class="section active">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h5 class="mb-0">Dashboard</h5>
      <button class="btn btn-outline-secondary btn-sm" onclick="refreshSection('stats')"><i class="bi bi-arrow-clockwise"></i> Обновить</button>
    </div>
    <!-- Stats: одна строка из 7 карточек -->
    <div class="row g-2 mb-4" style="flex-wrap:nowrap">
      <div class="col"><div class="stat-card blue">
        <div class="stat-label">Всего юзеров</div>
        <div class="stat-num" id="s-users">—</div>
      </div></div>
      <div class="col"><div class="stat-card green">
        <div class="stat-label">Активны сегодня</div>
        <div class="stat-num" id="s-active">—</div>
      </div></div>
      <div class="col"><div class="stat-card rose">
        <div class="stat-label">Сообщений сегодня</div>
        <div class="stat-num" id="s-msgs">—</div>
      </div></div>
      <div class="col"><div class="stat-card purple">
        <div class="stat-label">Ритуалов сегодня</div>
        <div class="stat-num" id="s-rituals">—</div>
      </div></div>
      <div class="col"><div class="stat-card" style="background:linear-gradient(135deg,#1a1230,#261848);border:1px solid #7c3aed">
        <div class="stat-label">🔮 Таро сегодня</div>
        <div class="stat-num" id="s-tarot">—</div>
      </div></div>
      <div class="col"><div class="stat-card" style="background:linear-gradient(135deg,#0a1e2e,#0f2d42);border:1px solid #0ea5e9">
        <div class="stat-label">⭐ Астро сегодня</div>
        <div class="stat-num" id="s-astro">—</div>
      </div></div>
      <div class="col"><div class="stat-card" style="background:linear-gradient(135deg,#1a1f1a,#212b21);border:1px solid #4ade80">
        <div class="stat-label">💬 Чат сегодня</div>
        <div class="stat-num" id="s-chat">—</div>
      </div></div>
    </div>
    <div class="card"><div class="card-header p-3">Последние пользователи</div>
      <div class="card-body p-0">
        <table class="table table-hover mb-0" id="users-table-mini">
          <thead><tr><th>User ID</th><th>ФИО</th><th>@username</th><th>TG</th><th>Тариф</th><th>Ритуал</th><th>Создан</th></tr></thead>
          <tbody id="users-tbody-mini"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Config -->
  <div id="sec-config" class="section">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h5 class="mb-0">Конфиг приложения</h5>
      <button class="btn btn-outline-secondary btn-sm" onclick="refreshSection('config')"><i class="bi bi-arrow-clockwise"></i> Обновить</button>
    </div>
    <div id="config-list"></div>
  </div>

  <!-- Routing -->
  <div id="sec-routing" class="section">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h5 class="mb-0">LLM Routing</h5>
      <button class="btn btn-outline-secondary btn-sm" onclick="refreshSection('routing')"><i class="bi bi-arrow-clockwise"></i> Обновить</button>
    </div>

    <!-- Keys 2-col -->
    <div class="row g-4 mb-4">

      <!-- LEFT: LLM providers -->
      <div class="col-md-6">
        <div class="card h-100">
          <div class="card-header p-3 d-flex justify-content-between align-items-center">
            <span><i class="bi bi-key"></i> API-ключи LLM провайдеров</span>
            <button class="btn btn-sm btn-outline-secondary" onclick="showAddLLMForm()"><i class="bi bi-plus-lg"></i> Добавить</button>
          </div>
          <div class="card-body">
            <p style="font-size:.8rem;color:#8b949e;margin-bottom:.75rem">Хранятся в памяти до перезапуска. Для постоянного — пропишите в <code>.env</code>.</p>
            <div id="llm-keys-list"></div>
            <div id="add-llm-form" style="display:none;margin-top:.75rem;padding:.75rem;border:1px solid #30363d;border-radius:8px">
              <div class="mb-2">
                <select class="form-select form-select-sm" id="new-llm-provider"></select>
              </div>
              <div class="input-group input-group-sm">
                <input type="password" class="form-control" id="new-llm-key" placeholder="API ключ..." autocomplete="new-password">
                <button class="btn btn-primary btn-sm" onclick="saveNewLLMKey()">Добавить</button>
                <button class="btn btn-outline-secondary btn-sm" onclick="hideAddLLMForm()">✕</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- RIGHT: Telegram bots -->
      <div class="col-md-6">
        <div class="card h-100">
          <div class="card-header p-3 d-flex justify-content-between align-items-center">
            <span><i class="bi bi-telegram"></i> Telegram боты</span>
            <button class="btn btn-sm btn-outline-secondary" onclick="showAddTgForm()"><i class="bi bi-plus-lg"></i> Добавить бота</button>
          </div>
          <div class="card-body">
            <p style="font-size:.8rem;color:#8b949e;margin-bottom:.75rem">Все добавленные боты работают параллельно. Хранятся в памяти — после перезапуска нужно добавить повторно.</p>
            <div id="tg-bots-list"></div>
            <div id="add-tg-form" style="display:none;margin-top:.75rem;padding:.75rem;border:1px solid #30363d;border-radius:8px">
              <div class="mb-2">
                <input type="text" class="form-control form-control-sm" id="new-tg-name" placeholder="Название (например: Prod Bot)">
              </div>
              <div class="input-group input-group-sm mb-2">
                <input type="password" class="form-control" id="new-tg-token" placeholder="123456789:ABCdef..." autocomplete="new-password">
              </div>
              <div class="d-flex gap-2">
                <button class="btn btn-primary btn-sm" onclick="addTgBot()"><i class="bi bi-plus-lg"></i> Добавить и подключить</button>
                <button class="btn btn-outline-secondary btn-sm ms-auto" onclick="hideAddTgForm()">✕</button>
              </div>
              <div id="add-tg-result" style="font-size:.8rem;margin-top:.5rem"></div>
            </div>
          </div>
        </div>
      </div>

    </div>

    <!-- Routing table -->
    <div class="card">
      <div class="card-header p-3 d-flex justify-content-between align-items-center">
        <span><i class="bi bi-diagram-3"></i> Маршрутизация задач → модели</span>
        <span style="font-size:.75rem;color:#8b949e">Изменения применяются сразу, без перезапуска</span>
      </div>
      <div class="card-body p-0">
        <table class="table table-hover mb-0" style="font-size:.83rem">
          <thead>
            <tr>
              <th style="width:200px">task_kind</th>
              <th style="width:70px">Tier</th>
              <th style="width:110px">Provider</th>
              <th style="width:210px">Model</th>
              <th style="width:90px">Max tokens</th>
              <th style="width:65px">Temp</th>
              <th style="width:200px">Fallback model</th>
              <th style="width:50px"></th>
            </tr>
          </thead>
          <tbody id="routing-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Quota -->
  <div id="sec-quota" class="section">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h5 class="mb-0">Квоты по тарифам</h5>
      <button class="btn btn-outline-secondary btn-sm" onclick="refreshSection('quota')"><i class="bi bi-arrow-clockwise"></i> Обновить</button>
    </div>
    <div id="quota-list" class="row g-3"></div>
  </div>

  <!-- Users -->
  <div id="sec-users" class="section">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h5 class="mb-0">Пользователи</h5>
      <button class="btn btn-outline-secondary btn-sm" onclick="refreshSection('users')"><i class="bi bi-arrow-clockwise"></i> Обновить</button>
    </div>
    <div class="card"><div class="card-body p-0">
      <table class="table table-hover mb-0">
        <thead><tr><th>User ID</th><th>ФИО</th><th>@username</th><th>TG</th><th>Тариф</th><th>Ритуал</th><th>Создан</th></tr></thead>
        <tbody id="users-tbody"></tbody>
      </table>
    </div></div>
  </div>

  <!-- KB -->
  <div id="sec-kb" class="section">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h5 class="mb-0">База знаний</h5>
      <button class="btn btn-outline-secondary btn-sm" onclick="refreshSection('kb')"><i class="bi bi-arrow-clockwise"></i> Обновить</button>
    </div>

    <!-- Collection management -->
    <div class="card mb-3">
      <div class="card-header p-3 d-flex justify-content-between align-items-center">
        <span><i class="bi bi-collection"></i> Управление коллекциями</span>
        <button class="btn btn-sm btn-outline-secondary" onclick="document.getElementById('kb-new-col-form').style.display=document.getElementById('kb-new-col-form').style.display==='none'?'':'none'">
          <i class="bi bi-plus-lg"></i> Создать
        </button>
      </div>
      <div class="card-body">
        <div id="kb-new-col-form" style="display:none;margin-bottom:1rem;padding:12px;background:#0d1117;border-radius:8px;border:1px solid #30363d">
          <div style="font-size:.85rem;color:#c8cdd4;margin-bottom:.5rem">Новая коллекция (только латиница, цифры, _)</div>
          <div class="d-flex gap-2">
            <input type="text" id="new-col-name" class="form-control form-control-sm" placeholder="knowledge_dreams" style="max-width:260px">
            <button class="btn btn-sm btn-primary" onclick="createCollection()"><i class="bi bi-plus-lg"></i> Создать</button>
          </div>
          <div style="font-size:.75rem;color:#8b949e;margin-top:.4rem">Коллекция сразу доступна для импорта данных. Вектор: 3072, cosine.</div>
        </div>
        <div id="kb-collections-list">
          <div style="color:#8b949e;font-size:.85rem">Загрузка...</div>
        </div>
      </div>
    </div>

    <div class="card mb-4">
      <div class="card-header p-3"><i class="bi bi-plus-circle"></i> Добавить записи</div>
      <div class="card-body">
        <!-- Tabs -->
        <ul class="nav nav-tabs mb-3" style="border-color:#30363d">
          <li class="nav-item">
            <a class="nav-link active" id="kb-tab-text" onclick="kbTab('text');return false;" href="javascript:void(0)" style="color:#8b949e;border-color:#30363d transparent transparent">
              <i class="bi bi-pencil-square"></i> Текст вручную
            </a>
          </li>
          <li class="nav-item">
            <a class="nav-link" id="kb-tab-url" onclick="kbTab('url');return false;" href="javascript:void(0)" style="color:#8b949e">
              <i class="bi bi-link-45deg"></i> По URL
            </a>
          </li>
          <li class="nav-item">
            <a class="nav-link" id="kb-tab-file" onclick="kbTab('file');return false;" href="javascript:void(0)" style="color:#8b949e">
              <i class="bi bi-file-earmark-arrow-up"></i> Загрузить файл
            </a>
          </li>
          <li class="nav-item">
            <a class="nav-link" id="kb-tab-dataset" onclick="kbTab('dataset');return false;" href="javascript:void(0)" style="color:#8b949e">
              <i class="bi bi-database-add"></i> Датасеты
            </a>
          </li>
        </ul>

        <!-- Tab: Text -->
        <div id="kb-pane-text">
          <div class="row g-3">
            <div class="col-md-4">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">КОЛЛЕКЦИЯ</label>
              <select class="form-select" id="kb-col"></select>
            </div>
            <div class="col-md-8">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">ТЕМА / НАЗВАНИЕ</label>
              <input type="text" class="form-control" id="kb-topic" placeholder="Например: Шут, Овен, Когнитивные искажения">
            </div>
            <div class="col-12">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">ТЕКСТ</label>
              <textarea class="form-control" id="kb-text" rows="6" placeholder="Содержимое записи..."></textarea>
            </div>
            <div class="col-12">
              <button class="btn btn-primary" onclick="addKBEntry()" id="kb-add-btn">
                <i class="bi bi-cloud-upload"></i> Добавить
              </button>
            </div>
          </div>
        </div>

        <!-- Tab: URL -->
        <div id="kb-pane-url" style="display:none">
          <div class="row g-3">
            <div class="col-md-4">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">КОЛЛЕКЦИЯ</label>
              <select class="form-select" id="kb-url-col"></select>
            </div>
            <div class="col-md-4">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">ТЕМА (необязательно)</label>
              <input type="text" class="form-control" id="kb-url-topic" placeholder="Оставь пустым — возьмём из URL">
            </div>
            <div class="col-md-4">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">ЯЗЫК ИСТОЧНИКА</label>
              <select class="form-select" id="kb-url-lang">
                <option value="auto">Авто</option><option value="en">EN</option><option value="ru">RU</option>
              </select>
            </div>
            <div class="col-12">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">URL</label>
              <input type="url" class="form-control" id="kb-url-input" placeholder="https://...">
            </div>
            <div class="col-12">
              <button class="btn btn-primary" onclick="addKBUrl()" id="kb-url-btn">
                <i class="bi bi-cloud-download"></i> Загрузить и добавить
              </button>
              <span id="kb-url-result" class="ms-3 text-secondary" style="font-size:.85rem"></span>
            </div>
          </div>
        </div>

        <!-- Tab: File (multi-upload) -->
        <div id="kb-pane-file" style="display:none">
          <div id="kb-drop-zone"
               onclick="document.getElementById('kb-file-input').click()"
               ondragover="event.preventDefault();this.style.borderColor='#a78bfa'"
               ondragleave="this.style.borderColor='#30363d'"
               ondrop="onFilesDrop(event)"
               style="border:2px dashed #30363d;border-radius:8px;padding:22px 20px;text-align:center;cursor:pointer;transition:border-color .15s;margin-bottom:.75rem">
            <i class="bi bi-cloud-upload" style="font-size:1.6rem;color:#6e7681"></i>
            <div style="color:#8b949e;margin-top:6px;font-size:.9rem">Перетащи файлы или <span style="color:#a78bfa">выбери</span></div>
            <div style="font-size:.73rem;color:#555;margin-top:3px">PDF, DOCX, EPUB, FB2, TXT, ZIP · Можно несколько файлов сразу</div>
          </div>
          <input type="file" id="kb-file-input" style="display:none" multiple
                 accept=".txt,.md,.pdf,.docx,.epub,.fb2,.json,.csv,.zip,.rst,.log"
                 onchange="onFilesSelected(this.files)">

          <!-- Per-file preview table -->
          <div id="kb-file-list" style="display:none;margin-bottom:.75rem;overflow-x:auto">
            <table style="width:100%;font-size:.8rem;border-collapse:collapse">
              <thead>
                <tr style="color:#6e7681;font-size:.71rem;text-transform:uppercase;letter-spacing:.04em">
                  <th style="padding:.3rem .5rem;border-bottom:1px solid #21262d">Файл</th>
                  <th style="padding:.3rem .5rem;border-bottom:1px solid #21262d;width:210px">Коллекция <span style="color:#555;font-weight:400">(авто из имени)</span></th>
                  <th style="padding:.3rem .5rem;border-bottom:1px solid #21262d;width:190px">Тема (необязательно)</th>
                  <th style="padding:.3rem .5rem;border-bottom:1px solid #21262d;width:22px"></th>
                </tr>
              </thead>
              <tbody id="kb-file-rows"></tbody>
            </table>
          </div>

          <div class="d-flex align-items-center gap-3">
            <button class="btn btn-primary" id="kb-file-btn" style="display:none" onclick="uploadAllFiles()">
              <i class="bi bi-upload"></i> Загрузить все
            </button>
            <span id="kb-file-result" style="font-size:.85rem"></span>
          </div>
        </div>

        <!-- Tab: Dataset -->
        <div id="kb-pane-dataset" style="display:none">
          <div class="alert" style="background:#1a2535;border:1px solid #2d4a6e;border-radius:8px;font-size:.82rem;color:#7cb9e8;margin-bottom:1rem">
            <i class="bi bi-info-circle me-2"></i>
            <strong>Поддерживаются три источника:</strong><br>
            <span style="color:#a8d8f0">📄 Файл</span> — прямая ссылка на .json/.jsonl/.csv (Raw-ссылка на GitHub)<br>
            <span style="color:#a8d8f0">📦 GitHub репо</span> — ссылка <code style="color:#7dd3fc">github.com/user/repo</code> — скачает весь репозиторий<br>
            <span style="color:#a8d8f0">🤗 HuggingFace</span> — ссылка <code style="color:#7dd3fc">huggingface.co/datasets/user/repo</code><br>
            <span style="color:#86efac">Все записи сохраняются в двух языковых версиях (оригинал + перевод)</span> для точного семантического поиска.
          </div>
          <div class="row g-3">
            <div class="col-md-4">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">КОЛЛЕКЦИЯ</label>
              <select class="form-select" id="kb-ds-col"></select>
            </div>
            <div class="col-md-8">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">ПРЕФИКС ТЕМЫ (необязательно)</label>
              <input type="text" class="form-control" id="kb-ds-prefix" placeholder="Например: КПТ, RECCON, Терапия">
            </div>
            <div class="col-12">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">URL ФАЙЛА ДАТАСЕТА</label>
              <input type="url" class="form-control" id="kb-ds-url" placeholder="https://huggingface.co/.../raw/main/data.json">
            </div>
            <div class="col-md-6">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">ПОЛЕ ВОПРОСА (авто если пусто)</label>
              <input type="text" class="form-control form-control-sm" id="kb-ds-qfield" placeholder="question / context / input">
            </div>
            <div class="col-md-6">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">ПОЛЕ ОТВЕТА (авто если пусто)</label>
              <input type="text" class="form-control form-control-sm" id="kb-ds-afield" placeholder="answer / response / output">
            </div>
            <div class="col-md-4">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">ЛИМИТ ЗАПИСЕЙ (0 = все)</label>
              <input type="number" class="form-control form-control-sm" id="kb-ds-limit" value="0" min="0">
            </div>
            <div class="col-md-4">
              <label class="form-label" style="font-size:.8rem;color:#8b949e">ЯЗЫК ИСТОЧНИКА</label>
              <select class="form-select form-select-sm" id="kb-ds-lang">
                <option value="auto">Авто-определение</option>
                <option value="en">English</option>
                <option value="ru">Русский</option>
              </select>
            </div>
            <div class="col-md-4 d-flex align-items-end">
              <div style="font-size:.76rem;color:#6fcf6f;line-height:1.4">
                <i class="bi bi-translate"></i> Обе языковые версии<br>сохраняются автоматически
              </div>
            </div>
            <div class="col-12">
              <button class="btn btn-primary" onclick="addKBDataset()" id="kb-ds-btn">
                <i class="bi bi-cloud-arrow-down"></i> Импортировать датасет
              </button>
              <span id="kb-ds-result" class="ms-3 text-secondary" style="font-size:.85rem"></span>
            </div>
          </div>

        </div>
      </div>
    </div>

    <!-- Jobs queue (always visible in KB section) -->
    <div class="card mt-3" id="ingest-jobs-card">
      <div class="card-header p-3 d-flex justify-content-between align-items-center">
        <span><i class="bi bi-layers"></i> Очередь загрузок</span>
        <button class="btn btn-sm" style="font-size:.72rem;padding:2px 8px;background:#1a2535;border:1px solid #2d4a6e;color:#7cb9e8" onclick="loadIngestJobs()">
          <i class="bi bi-arrow-clockwise"></i> Обновить
        </button>
      </div>
      <div class="card-body p-2">
        <div id="ingest-jobs-list">
          <div style="font-size:.8rem;color:#555;padding:.4rem">Загрузка...</div>
        </div>
      </div>
    </div>

    <!-- HuggingFace Catalog Search -->
    <div class="card mt-3">
      <div class="card-header p-3"><i class="bi bi-search"></i> 🤗 Поиск датасетов HuggingFace</div>
      <div class="card-body">
        <div class="row g-2 mb-3">
          <div class="col">
            <input type="text" id="hf-search-q" class="form-control" placeholder="Поиск: psychology, CBT, therapy, mental health..." onkeydown="if(event.key==='Enter')searchHF()">
          </div>
          <div class="col-auto">
            <button class="btn btn-outline-secondary" onclick="searchHF()"><i class="bi bi-search"></i> Найти</button>
          </div>
        </div>
        <div style="font-size:.75rem;color:#b0bec5;margin-bottom:.5rem">Быстрые теги:</div>
        <div class="d-flex flex-wrap gap-1 mb-3" id="hf-quick-tags">
          <button class="btn btn-sm" style="background:#21262d;color:#a78bfa;border:1px solid #4338ca;font-size:.75rem" onclick="searchHFTag('mental-health')">mental-health</button>
          <button class="btn btn-sm" style="background:#21262d;color:#a78bfa;border:1px solid #4338ca;font-size:.75rem" onclick="searchHFTag('psychology')">psychology</button>
          <button class="btn btn-sm" style="background:#21262d;color:#a78bfa;border:1px solid #4338ca;font-size:.75rem" onclick="searchHFQ('CBT therapy')">CBT therapy</button>
          <button class="btn btn-sm" style="background:#21262d;color:#a78bfa;border:1px solid #4338ca;font-size:.75rem" onclick="searchHFQ('counseling conversation')">counseling</button>
          <button class="btn btn-sm" style="background:#21262d;color:#a78bfa;border:1px solid #4338ca;font-size:.75rem" onclick="searchHFQ('emotion dialogue')">emotion dialogue</button>
        </div>
        <div id="hf-results" style="min-height:40px"></div>
      </div>
    </div>

    <div class="card mt-3">
      <div class="card-header p-3 d-flex justify-content-between align-items-center">
        <span><i class="bi bi-list-ul"></i> Записи</span>
        <div class="d-flex gap-2 align-items-center">
          <select class="form-select form-select-sm" id="kb-browse-col" style="width:200px" onchange="loadKBEntries()"></select>
          <button class="btn btn-outline-secondary btn-sm" onclick="loadKBEntries()"><i class="bi bi-arrow-clockwise"></i></button>
        </div>
      </div>
      <div class="card-body p-0">
        <table class="table table-hover mb-0">
          <thead><tr><th style="width:200px">Тема</th><th>Превью текста</th><th style="width:80px"></th></tr></thead>
          <tbody id="kb-entries-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

</div>

<!-- Toast -->
<div class="toast-container">
  <div id="toast" class="toast align-items-center text-white border-0" role="alert">
    <div class="d-flex"><div class="toast-body" id="toast-body"></div>
    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const API = '';
let TOKEN = sessionStorage.getItem('admin_token') || '';
const KB_COLLECTIONS = ['knowledge_tarot', 'knowledge_astro', 'knowledge_psych'];

// ── Auth ──────────────────────────────────────────────────────────────────────
async function doLogin() {
  const username = document.getElementById('login-input').value.trim();
  const password = document.getElementById('password-input').value;
  const errEl = document.getElementById('login-error');
  errEl.textContent = '';
  try {
    const res = await fetch(API + '/admin/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username, password}),
    });
    if (!res.ok) { errEl.textContent = 'Неверный логин или пароль'; return; }
    const data = await res.json();
    TOKEN = data.token;
    sessionStorage.setItem('admin_token', TOKEN);
    showApp();
  } catch(e) { errEl.textContent = 'Ошибка соединения'; }
}
function logout() { sessionStorage.removeItem('admin_token'); location.reload(); }
document.getElementById('password-input').addEventListener('keydown', e => { if(e.key==='Enter') doLogin(); });

function showApp() {
  document.getElementById('login-screen').style.display = 'none';
  const initial = location.hash.replace('#', '') || 'stats';
  nav(initial);
}

// ── API ───────────────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: {'X-Admin-Token': TOKEN} };
  if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
const apiGet    = path => api('GET', path).catch(() => null);
const apiPut    = (path, body) => api('PUT', path, body);
const apiPost   = (path, body) => api('POST', path, body);
const apiDelete = path => api('DELETE', path);

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg, ok=true) {
  const el = document.getElementById('toast');
  el.className = `toast align-items-center text-white border-0 bg-${ok?'success':'danger'}`;
  document.getElementById('toast-body').textContent = msg;
  new bootstrap.Toast(el, {delay:3000}).show();
}

// ── Nav ───────────────────────────────────────────────────────────────────────
const _loadedSections = new Set();
const _SECTIONS = ['stats', 'config', 'routing', 'quota', 'users', 'kb'];

function nav(name) {
  if (!_SECTIONS.includes(name)) name = 'stats';
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  const sec = document.getElementById('sec-' + name);
  if (sec) sec.classList.add('active');
  document.querySelectorAll('.sidebar .nav-link').forEach(l => {
    l.classList.toggle('active', l.getAttribute('href') === '#' + name);
  });
  if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  loadSection(name);
}
function loadSection(name, force=false) {
  if (!force && _loadedSections.has(name)) return;
  _loadedSections.add(name);
  const fn = {stats: loadStats, config: loadConfig, routing: loadRouting, quota: loadQuota, users: loadUsers, kb: loadKB};
  if (fn[name]) fn[name]();
}
function refreshSection(name) {
  _loadedSections.delete(name);
  loadSection(name);
}
window.addEventListener('hashchange', () => {
  const name = location.hash.replace('#', '') || 'stats';
  nav(name);
});

// ── Stats ─────────────────────────────────────────────────────────────────────
async function loadStats() {
  const [stats, users] = await Promise.all([apiGet('/admin/stats'), apiGet('/admin/users?limit=5')]);
  if (!stats) return;
  document.getElementById('s-users').textContent = stats.total_users;
  document.getElementById('s-active').textContent = stats.active_today;
  document.getElementById('s-rituals').textContent = stats.rituals_sent_today;
  document.getElementById('s-msgs').textContent = stats.messages_today;
  document.getElementById('s-tarot').textContent = stats.tarot_today ?? 0;
  document.getElementById('s-astro').textContent = stats.astrology_today ?? 0;
  document.getElementById('s-chat').textContent = stats.chat_today ?? 0;
  const tbody = document.getElementById('users-tbody-mini');
  tbody.innerHTML = (users||[]).map(userRow).join('');
}

// ── Config metadata ───────────────────────────────────────────────────────────
const CONFIG_META = {
  kb_enrichment_context_prompt: {
    label: 'Промпт: описание документа',
    desc: 'Инструкция для LLM при генерации краткого резюме всего документа. Добавляется как контекст к вектору каждого чанка.',
    type: 'prompt',
  },
  kb_enrichment_metadata_prompt: {
    label: 'Промпт: теги и категория',
    desc: 'Инструкция для извлечения ключевых слов и классификации отдельного фрагмента.',
    type: 'prompt',
  },
  kb_enrichment_context: {
    label: 'Контекст документа',
    desc: 'LLM пишет краткое описание всего документа — добавляется к вектору каждого чанка',
    type: 'bool',
  },
  kb_enrichment_metadata: {
    label: 'Теги и категория чанков',
    desc: 'LLM извлекает ключевые слова и категорию для каждого фрагмента',
    type: 'bool',
  },
  kb_enrich_concurrency: {
    label: 'Параллельность обогащения',
    desc: 'Число одновременных LLM-запросов при чанкинге',
    type: 'number',
  },
  kb_max_zip_size_mb: {
    label: 'Лимит ZIP (МБ)',
    desc: 'Максимальный размер загружаемого ZIP-архива',
    type: 'number',
  },
  kb_category_list: {
    label: 'Таксономия контента',
    desc: 'Темы через запятую — LLM относит каждый чанк к одной из них при обогащении. Это НЕ коллекции Qdrant, а тематика внутри документов. Если пусто — категории не назначаются, поиск работает нормально.',
    type: 'text',
  },
};

// ── Config ────────────────────────────────────────────────────────────────────
async function loadConfig() {
  const items = await apiGet('/admin/config');
  if (!items) return;

  const TYPE_ORDER = {prompt:0, bool:1, number:2, text:3};
  const detectType = item => {
    const m = CONFIG_META[item.key];
    if (m) return m.type;
    const v = (item.value||'').trim().toLowerCase();
    if (v==='true'||v==='false') return 'bool';
    if (/^\d+(\.\d+)?$/.test(v)) return 'number';
    return item.value.length > 100 ? 'prompt' : 'text';
  };

  const sorted = [...items].sort((a,b) => (TYPE_ORDER[detectType(a)]??4)-(TYPE_ORDER[detectType(b)]??4));
  const prompts = sorted.filter(i => detectType(i)==='prompt');
  const compact = sorted.filter(i => detectType(i)!=='prompt');
  let html = '';

  // Промпты — 2 колонки
  if (prompts.length) {
    html += `<div class="mb-4">
      <div class="cfg-section-hdr">Промпты</div>
      <div class="row g-3">`;
    for (const item of prompts) {
      const m = CONFIG_META[item.key]||{};
      html += `<div class="col-md-6">
        <div class="card h-100 cfg-prompt-card">
          <div class="card-body p-3">
            <div class="cfg-item-title">${m.label||item.key} <span class="cfg-item-syskey">(${item.key})</span></div>
            ${m.desc?`<div class="cfg-item-desc mb-2">${m.desc}</div>`:''}
            <textarea class="form-control cfg-textarea mb-2" id="cfg-${item.key}" rows="5">${escHtml(item.value)}</textarea>
            <button class="btn btn-save" onclick="saveConfig('${item.key}')"><i class="bi bi-check2"></i> Сохранить</button>
          </div>
        </div>
      </div>`;
    }
    html += '</div></div>';
  }

  // Компактные параметры: bool/number — 3 колонки, text — 2 колонки
  if (compact.length) {
    html += `<div>
      <div class="cfg-section-hdr">Параметры</div>
      <div class="row g-2">`;
    for (const item of compact) {
      const m = CONFIG_META[item.key]||{};
      const type = detectType(item);
      const label = m.label||item.key;
      const desc = m.desc||'';
      const colCls = type==='text' ? 'col-md-6' : 'col-md-4';
      let inner = '';
      if (type==='bool') {
        const yes = (item.value||'').trim().toLowerCase()==='true';
        inner = `<div class="cfg-ctrl-row mb-1">
          <div style="flex:1;min-width:0"><div class="cfg-item-title">${label} <span class="cfg-item-syskey">(${item.key})</span></div></div>
          <select class="form-select form-select-sm cfg-ctrl-small" id="cfg-${item.key}">
            <option value="true"${yes?' selected':''}>Да</option>
            <option value="false"${!yes?' selected':''}>Нет</option>
          </select>
          <button class="btn btn-save cfg-save-sm" onclick="saveConfig('${item.key}')"><i class="bi bi-check2"></i></button>
        </div>${desc?`<div class="cfg-item-desc">${desc}</div>`:''}`;
      } else if (type==='number') {
        inner = `<div class="cfg-ctrl-row mb-1">
          <div style="flex:1;min-width:0"><div class="cfg-item-title">${label} <span class="cfg-item-syskey">(${item.key})</span></div></div>
          <input type="number" class="form-control form-control-sm cfg-ctrl-small" id="cfg-${item.key}" value="${escHtml(item.value)}">
          <button class="btn btn-save cfg-save-sm" onclick="saveConfig('${item.key}')"><i class="bi bi-check2"></i></button>
        </div>${desc?`<div class="cfg-item-desc">${desc}</div>`:''}`;
      } else {
        const autoBtn = item.key==='kb_category_list'
          ? `<button class="btn btn-outline-secondary btn-sm cfg-save-sm" title="Заполнить из коллекций Qdrant" onclick="fillCategoriesFromCollections()"><i class="bi bi-stars"></i> Авто</button>`
          : '';
        inner = `<div class="cfg-item-title mb-1">${label} <span class="cfg-item-syskey">(${item.key})</span></div>
          ${desc?`<div class="cfg-item-desc mb-1">${desc}</div>`:''}
          <div class="d-flex gap-1 mt-1">
            <input type="text" class="form-control form-control-sm" id="cfg-${item.key}" value="${escHtml(item.value)}">
            ${autoBtn}
            <button class="btn btn-save cfg-save-sm" onclick="saveConfig('${item.key}')"><i class="bi bi-check2"></i></button>
          </div>`;
      }
      html += `<div class="${colCls}"><div class="cfg-compact">${inner}</div></div>`;
    }
    html += '</div></div>';
  }

  document.getElementById('config-list').innerHTML = html||'<div class="text-secondary py-3 text-center">Нет настроек</div>';
}

async function saveConfig(key) {
  const value = document.getElementById('cfg-'+key).value;
  try { await apiPut('/admin/config/'+key, {value}); toast('Сохранено: '+key); }
  catch(e) { toast('Ошибка: '+e.message, false); }
}

async function fillCategoriesFromCollections() {
  const cols = await apiGet('/admin/kb/collections');
  if (!cols||!cols.length) { toast('Нет коллекций', false); return; }
  const COL_LABELS = {
    knowledge_tarot:'Таро', knowledge_astro:'Астрология', knowledge_psych:'Психология',
    knowledge_dreams:'Сонник', knowledge_numerology:'Нумерология',
  };
  const SYSTEM = ['user_episodes','user_facts'];
  const cats = cols
    .filter(c => !SYSTEM.includes(c.name))
    .map(c => COL_LABELS[c.name] || c.name.replace(/^knowledge_/,'').replace(/_/g,' '))
    .join(', ');
  const el = document.getElementById('cfg-kb_category_list');
  if (el) { el.value = cats; toast('Категории из коллекций — сохрани если нужно'); }
}

// ── Routing ───────────────────────────────────────────────────────────────────
const TASK_KIND_LABELS = {
  main_chat: 'Чат (free/basic)',
  main_chat_premium: 'Чат (plus/pro)',
  intent_classify: 'Классификация интента',
  crisis_classify: 'Кризисный детектор',
  memory_summarize: 'Сжатие памяти',
  memory_extract_facts: 'Извлечение фактов',
  tarot_interpret: 'Таро: интерпретация',
  astro_interpret: 'Астрология: интерпретация',
  game_narration: 'Нарратив игры',
  proactive_compose: 'Проактивные сообщения',
  persona_evolve: 'Развитие персоны',
  embedding: 'Эмбеддинг (Qdrant)',
};

// Cache of models per provider, loaded once
const _modelCache = {openai: [], anthropic: []};

async function _loadModels(provider) {
  if (_modelCache[provider].length) return _modelCache[provider];
  const res = await apiGet('/admin/llm-models?provider=' + provider);
  if (res && res.models) _modelCache[provider] = res.models;
  return _modelCache[provider];
}

function _buildModelSelect(id, models, currentValue, style='') {
  // Always include current value even if not in list
  const hasValue = models.some(m => m.id === currentValue);
  const extra = (!hasValue && currentValue) ? `<option value="${escHtml(currentValue)}" selected>${escHtml(currentValue)}</option>` : '';
  const opts = models.map(m =>
    `<option value="${m.id}" ${m.id===currentValue?'selected':''}>${m.label||m.id}</option>`
  ).join('');
  return `<select class="form-select form-select-sm" id="${id}" style="min-width:200px${style?';'+style:''}">${extra}${opts}</select>`;
}

async function loadRouting() {
  loadLLMKeys();
  loadTgBots();
  // Only fetch model lists if cache is empty
  const needOAI = !_modelCache.openai.length;
  const needAnt = !_modelCache.anthropic.length;
  const fetches = [apiGet('/admin/routing')];
  if (needOAI) fetches.push(apiGet('/admin/llm-models?provider=openai'));
  if (needAnt) fetches.push(apiGet('/admin/llm-models?provider=anthropic'));
  const results = await Promise.all(fetches);
  const items = results[0];
  let idx = 1;
  if (needOAI) { const r = results[idx++]; if (r?.models) _modelCache.openai = r.models; }
  if (needAnt) { const r = results[idx++]; if (r?.models) _modelCache.anthropic = r.models; }
  if (!items) return;

  document.getElementById('routing-tbody').innerHTML = items.map(r => {
    const fb = (r.fallback_chain||[]).map(f => f.model_id).join(', ');
    const label = TASK_KIND_LABELS[r.task_kind] || r.task_kind;
    const isEmbed = r.task_kind === 'embedding';
    const isOAI = r.provider_id === 'openai';
    const models = isOAI ? _modelCache.openai : _modelCache.anthropic;
    const fbModels = [..._modelCache.openai, ..._modelCache.anthropic];
    return `<tr class="routing-row" id="row-${r.task_kind}">
      <td>
        <div class="task-label">${label}</div>
        <div class="task-code">${r.task_kind}</div>
      </td>
      <td><span class="badge bg-secondary" style="font-size:.72rem">${r.tier}</span></td>
      <td>
        <div class="d-flex gap-1">
          <button type="button" class="provider-btn ${isOAI?'active-openai':''}" onclick="_setProvider('${r.task_kind}','openai')" id="r-btn-openai-${r.task_kind}">OpenAI</button>
          <button type="button" class="provider-btn ${!isOAI?'active-anthropic':''}" onclick="_setProvider('${r.task_kind}','anthropic')" id="r-btn-anthropic-${r.task_kind}">Anthropic</button>
        </div>
        <input type="hidden" id="r-prov-${r.task_kind}" value="${r.provider_id}">
      </td>
      <td>${_buildModelSelect('r-model-'+r.task_kind, models, r.model_id)}</td>
      <td><input class="form-control form-control-sm" type="number" id="r-tok-${r.task_kind}" value="${r.max_tokens}" style="width:80px" ${isEmbed?'disabled':''}></td>
      <td><input class="form-control form-control-sm" type="number" step="0.1" min="0" max="2" id="r-temp-${r.task_kind}" value="${r.temperature}" style="width:65px" ${isEmbed?'disabled':''}></td>
      <td>${isEmbed
        ? '<span style="color:var(--text-muted);font-size:.8rem">—</span>'
        : _buildModelSelect('r-fb-'+r.task_kind, fbModels, fb)
      }</td>
      <td><button class="btn btn-save" onclick="saveRouting('${r.task_kind}')"><i class="bi bi-check2"></i> Сохранить</button></td>
    </tr>`;
  }).join('');
}

async function _setProvider(kind, provider) {
  document.getElementById('r-prov-' + kind).value = provider;
  document.getElementById('r-btn-openai-' + kind).className = 'provider-btn' + (provider==='openai'?' active-openai':'');
  document.getElementById('r-btn-anthropic-' + kind).className = 'provider-btn' + (provider==='anthropic'?' active-anthropic':'');
  // Reload model dropdown for this row
  const models = await _loadModels(provider);
  const currentModel = document.getElementById('r-model-' + kind)?.value || '';
  const cell = document.getElementById('r-model-' + kind)?.parentElement;
  if (cell) cell.innerHTML = _buildModelSelect('r-model-' + kind, models, currentModel);
}

// ── LLM keys ──────────────────────────────────────────────────────────────────
let _llmProvidersMeta = {};

async function loadLLMKeys() {
  const data = await apiGet('/admin/llm-keys');
  if (!data) return;
  _llmProvidersMeta = data.providers || {};
  const keys = data.keys || {};
  const setList = Object.entries(keys).filter(([,v]) => v);
  document.getElementById('llm-keys-list').innerHTML = setList.length ? setList.map(([id, masked]) => {
    const m = _llmProvidersMeta[id] || {label: id, color: '#888', placeholder: '...'};
    return `<div class="d-flex align-items-center gap-2 mb-2 px-2 py-2" style="border:1px solid #2d3748;border-radius:8px;min-height:38px">
      <span style="font-size:.75rem;font-weight:600;color:${m.color};min-width:110px">${m.label}</span>
      <span style="font-size:.72rem;color:#4ade80">●</span>
      <span style="font-size:.72rem;color:#8b949e;font-family:monospace;flex:1;overflow:hidden;text-overflow:ellipsis">${masked}</span>
      <input type="password" class="form-control form-control-sm" id="key-input-${id}" placeholder="${m.placeholder}" style="max-width:140px" autocomplete="new-password">
      <button class="btn btn-sm btn-outline-secondary px-2" onclick="saveLLMKey('${id}')" title="Обновить ключ"><i class="bi bi-cloud-upload"></i></button>
      <button class="btn btn-sm btn-outline-danger px-2" onclick="deleteLLMKey('${id}')" title="Удалить ключ"><i class="bi bi-trash3"></i></button>
    </div>`;
  }).join('') : '<p style="font-size:.82rem;color:#8b949e">Ключи не заданы</p>';
  // Populate add-form dropdown with providers that have no key set
  const setIds = new Set(setList.map(([k]) => k));
  const unset = Object.keys(_llmProvidersMeta).filter(p => !setIds.has(p));
  const sel = document.getElementById('new-llm-provider');
  if (sel) sel.innerHTML = unset.map(p => `<option value="${p}">${_llmProvidersMeta[p].label}</option>`).join('');
}

async function saveLLMKey(provider) {
  const inp = document.getElementById('key-input-' + provider);
  const key = inp ? inp.value.trim() : '';
  if (!key) { toast('Введи ключ', false); return; }
  try {
    await fetch('/admin/llm-keys/' + provider, {
      method: 'PUT', headers: {'Content-Type':'application/json','X-Admin-Token': TOKEN},
      body: JSON.stringify({key}),
    });
    toast('Ключ сохранён: ' + (_llmProvidersMeta[provider]?.label || provider));
    if (inp) inp.value = '';
    loadLLMKeys();
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

function showAddLLMForm() { document.getElementById('add-llm-form').style.display = ''; }
function hideAddLLMForm() { document.getElementById('add-llm-form').style.display = 'none'; }

async function saveNewLLMKey() {
  const provider = document.getElementById('new-llm-provider').value;
  const key = document.getElementById('new-llm-key').value.trim();
  if (!provider) { toast('Выбери провайдера', false); return; }
  if (!key) { toast('Введи ключ', false); return; }
  try {
    await fetch('/admin/llm-keys/' + provider, {
      method: 'PUT', headers: {'Content-Type':'application/json','X-Admin-Token': TOKEN},
      body: JSON.stringify({key}),
    });
    toast('Ключ добавлен: ' + (_llmProvidersMeta[provider]?.label || provider));
    document.getElementById('new-llm-key').value = '';
    hideAddLLMForm();
    loadLLMKeys();
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

async function deleteLLMKey(provider) {
  const label = _llmProvidersMeta[provider]?.label || provider;
  if (!confirm(`Удалить ключ ${label}? Провайдер станет недоступен до следующей установки.`)) return;
  try {
    const r = await fetch('/admin/llm-keys/' + provider, {
      method: 'DELETE', headers: {'X-Admin-Token': TOKEN},
    });
    const data = await r.json();
    if (!r.ok) { toast('✗ ' + (data.detail || 'Ошибка'), false); return; }
    toast('Ключ удалён: ' + label);
    loadLLMKeys();
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

// ── Telegram bots ─────────────────────────────────────────────────────────────
async function loadTgBots() {
  const data = await apiGet('/admin/tg-bots');
  if (!data) return;
  const bots = data.bots || [];
  document.getElementById('tg-bots-list').innerHTML = bots.length ? bots.map(b => `
    <div class="d-flex align-items-center gap-2 mb-2 px-2 py-2" style="border:1px solid #2a3a5c;border-radius:8px;min-height:40px">
      <span title="Подключён" style="font-size:1rem;color:#4ade80">●</span>
      <div style="flex:1;min-width:0">
        <div style="font-size:.78rem;font-weight:600;color:#e6edf3">${b.name}${b.username?` <span style="font-weight:400;color:#8b949e">@${b.username}</span>`:''}</div>
        <div style="font-size:.7rem;color:#6e7681;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${b.masked}${b.tg_id?` · ID: ${b.tg_id}`:''}</div>
      </div>
      <button class="btn btn-sm btn-outline-secondary px-2" onclick="reconnectTgBot('${b.name}')" title="Переподключить webhook"><i class="bi bi-arrow-repeat"></i></button>
      <button class="btn btn-sm btn-outline-danger px-2" onclick="removeTgBot('${b.name}')" title="Удалить бота"><i class="bi bi-trash3"></i></button>
    </div>`).join('') : '<p style="font-size:.82rem;color:#8b949e">Нет подключённых ботов</p>';
}

function showAddTgForm() { document.getElementById('add-tg-form').style.display = ''; }
function hideAddTgForm() {
  document.getElementById('add-tg-form').style.display = 'none';
  document.getElementById('add-tg-result').textContent = '';
  document.getElementById('new-tg-name').value = '';
  document.getElementById('new-tg-token').value = '';
}

async function addTgBot() {
  const name = document.getElementById('new-tg-name').value.trim();
  const token = document.getElementById('new-tg-token').value.trim();
  const res = document.getElementById('add-tg-result');
  if (!name) { res.textContent = '✗ Укажи название'; res.style.color = '#f87171'; return; }
  if (!token) { res.textContent = '✗ Укажи токен'; res.style.color = '#f87171'; return; }
  res.textContent = 'Проверяем токен...'; res.style.color = '#8b949e';
  try {
    const r = await fetch('/admin/tg-bots', {
      method: 'POST', headers: {'Content-Type':'application/json','X-Admin-Token': TOKEN},
      body: JSON.stringify({name, token}),
    });
    const data = await r.json();
    if (!r.ok) { res.textContent = '✗ ' + (data.detail || 'Ошибка'); res.style.color = '#f87171'; return; }
    res.textContent = `✓ @${data.username} подключён`;
    res.style.color = '#4ade80';
    setTimeout(() => { hideAddTgForm(); loadTgBots(); }, 1200);
  } catch(e) { res.textContent = '✗ ' + e.message; res.style.color = '#f87171'; }
}

async function reconnectTgBot(name) {
  try {
    const r = await fetch('/admin/tg-bots/' + encodeURIComponent(name) + '/activate', {
      method: 'PUT', headers: {'X-Admin-Token': TOKEN},
    });
    const data = await r.json();
    if (!r.ok) { toast('✗ ' + (data.detail || 'Ошибка'), false); return; }
    toast(`✓ Webhook переподключён: @${data.username}`);
    loadTgBots();
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

async function removeTgBot(name) {
  if (!confirm(`Удалить бота "${name}"?\nWebhook будет отключён, бот перестанет получать сообщения.`)) return;
  try {
    const r = await fetch('/admin/tg-bots/' + encodeURIComponent(name), {
      method: 'DELETE', headers: {'X-Admin-Token': TOKEN},
    });
    const data = await r.json();
    if (!r.ok) { toast('✗ ' + (data.detail || 'Ошибка'), false); return; }
    toast('Бот отключён и удалён');
    loadTgBots();
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

async function saveRouting(kind) {
  try {
    const fbModelId = document.getElementById('r-fb-' + kind)?.value?.trim() || '';
    const fallback_chain = fbModelId
      ? [{ provider_id: fbModelId.startsWith('claude') ? 'anthropic' : 'openai', model_id: fbModelId }]
      : [];
    await apiPut('/admin/routing/' + kind, {
      provider_id: document.getElementById('r-prov-' + kind).value,
      model_id: document.getElementById('r-model-' + kind).value,
      max_tokens: +(document.getElementById('r-tok-' + kind)?.value || 1000),
      temperature: +(document.getElementById('r-temp-' + kind)?.value || 0.7),
      fallback_chain,
    });
    toast('✓ Сохранено: ' + kind);
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

// ── Quota ─────────────────────────────────────────────────────────────────────
async function loadQuota() {
  const items = await apiGet('/admin/quota');
  if (!items) return;
  document.getElementById('quota-list').innerHTML = items.map(q => `
    <div class="col-md-6">
      <div class="card">
        <div class="card-header p-3"><span class="badge ${q.tier==='free'?'bg-secondary':'bg-primary'} me-2">${q.tier}</span>тариф</div>
        <div class="card-body">
          <div class="mb-2">
            <label class="form-label" style="font-size:.8rem;color:#8b949e">СООБЩЕНИЙ В ДЕНЬ</label>
            <input type="number" class="form-control" id="q-msg-${q.tier}" value="${q.daily_messages}">
          </div>
          <div class="mb-2">
            <label class="form-label" style="font-size:.8rem;color:#8b949e">ТАРО В ДЕНЬ</label>
            <input type="number" class="form-control" id="q-tarot-${q.tier}" value="${q.tarot_per_day}">
          </div>
          <div class="mb-3">
            <label class="form-label" style="font-size:.8rem;color:#8b949e">АСТРОЛОГИЯ В ДЕНЬ</label>
            <input type="number" class="form-control" id="q-astro-${q.tier}" value="${q.astrology_per_day}">
          </div>
          <button class="btn btn-primary btn-sm" onclick="saveQuota('${q.tier}')">
            <i class="bi bi-save"></i> Сохранить
          </button>
        </div>
      </div>
    </div>`).join('');
}
async function saveQuota(tier) {
  try {
    await apiPut('/admin/quota/' + tier, {
      daily_messages: +document.getElementById('q-msg-' + tier).value,
      tarot_per_day: +document.getElementById('q-tarot-' + tier).value,
      astrology_per_day: +document.getElementById('q-astro-' + tier).value,
    });
    toast('Квоты обновлены: ' + tier);
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

// ── Users ─────────────────────────────────────────────────────────────────────
async function loadUsers() {
  const items = await apiGet('/admin/users?limit=50');
  if (!items) return;
  document.getElementById('users-tbody').innerHTML = (items||[]).map(userRow).join('');
}
function userRow(u) {
  const tgBadge = u.is_premium
    ? '<span title="Telegram Premium" style="color:#f59e0b;font-size:.85rem"><i class="bi bi-star-fill"></i></span>'
    : '<span style="color:#374151;font-size:.8rem"><i class="bi bi-telegram"></i></span>';
  return `<tr>
    <td><code style="font-size:.75rem;color:#8b949e">${u.user_id.slice(0,8)}…</code></td>
    <td style="font-size:.85rem">${u.full_name || '<span class="text-secondary">—</span>'}</td>
    <td style="font-size:.82rem;color:#7dd3fc">${u.tg_username ? '@'+u.tg_username : '<span class="text-secondary">—</span>'}</td>
    <td>${tgBadge}</td>
    <td><span class="badge ${u.tier==='free'?'bg-secondary':'bg-primary'}">${u.tier}</span></td>
    <td>${u.daily_ritual_enabled
      ? '<span class="text-success"><i class="bi bi-check-circle"></i></span>'
      : '<span class="text-danger"><i class="bi bi-x-circle"></i></span>'}</td>
    <td style="font-size:.8rem;color:#8b949e">${u.created_at.slice(0,10)}</td>
  </tr>`;
}

function escHtml(t) { return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── KB ────────────────────────────────────────────────────────────────────────
const KB_LABELS = {knowledge_tarot:'Таро',knowledge_astro:'Астрология',knowledge_psych:'Психология/НЛП'};

function kbTab(name) {
  ['text','url','file','dataset'].forEach(t => {
    document.getElementById('kb-pane-' + t).style.display = t === name ? '' : 'none';
    const tab = document.getElementById('kb-tab-' + t);
    tab.classList.toggle('active', t === name);
    tab.style.color = t === name ? '#e0e0e0' : '#8b949e';
  });
  loadIngestJobs();
}

function _fillCollectionSelects(names) {
  // Selects where "— выбери —" placeholder is needed (no pre-selection)
  ['kb-col','kb-url-col','kb-ds-col'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '<option value="" disabled selected>— выбери коллекцию —</option>' +
      names.map(n => `<option value="${n}">${n}</option>`).join('');
    if (names.includes(prev)) sel.value = prev;
  });
  // Browse select — keep current or pick first
  const browse = document.getElementById('kb-browse-col');
  if (browse) {
    const prev = browse.value;
    browse.innerHTML = names.map(n => `<option value="${n}">${n}</option>`).join('');
    if (names.includes(prev)) browse.value = prev;
  }
}

const _KB_STATUS_STYLE = {
  green:   {dot:'#4ade80', label:'OK'},
  yellow:  {dot:'#fbbf24', label:'Индексируется'},
  red:     {dot:'#f87171', label:'Ошибка'},
  unknown: {dot:'#6b7280', label:'—'},
};

async function loadKB() {
  const cols = await apiGet('/admin/kb/collections');
  if (!cols) return;
  _fillCollectionSelects(cols.map(c => c.name));
  const SYSTEM = ['user_episodes','user_facts'];
  const totalPoints = cols.reduce((s, c) => s + (c.count || 0), 0);

  document.getElementById('kb-collections-list').innerHTML =
    `<div style="font-size:.78rem;color:#8b949e;margin-bottom:.75rem">
      Коллекций: <strong style="color:#e6edf3">${cols.length}</strong>
      &nbsp;·&nbsp; Всего записей: <strong style="color:#e6edf3">${totalPoints.toLocaleString()}</strong>
    </div>` +
    '<div class="table-responsive"><table class="table table-hover mb-0" style="font-size:.84rem">' +
    '<thead><tr>' +
    '<th>Коллекция</th>' +
    '<th style="width:90px">Записей</th>' +
    '<th style="width:90px">Сегментов</th>' +
    '<th style="width:90px">Статус</th>' +
    '<th style="width:210px">Действия</th>' +
    '</tr></thead><tbody>' +
    cols.map(c => {
      const st = _KB_STATUS_STYLE[c.status] || _KB_STATUS_STYLE.unknown;
      return `<tr>
        <td style="color:#e8eaed;font-weight:500">
          ${c.name}
          ${SYSTEM.includes(c.name)?'<span style="font-size:.7rem;color:#f87171;margin-left:6px">system</span>':''}
        </td>
        <td><strong>${c.count.toLocaleString()}</strong></td>
        <td style="color:#8b949e">${c.segments ?? '—'}</td>
        <td><span style="display:inline-flex;align-items:center;gap:5px;font-size:.78rem">
          <span style="width:8px;height:8px;border-radius:50%;background:${st.dot};flex-shrink:0"></span>
          <span style="color:${st.dot}">${st.label}</span>
        </span></td>
        <td>
          ${!SYSTEM.includes(c.name)?`
          <button class="btn btn-sm btn-outline-secondary me-1" style="font-size:.75rem" onclick="clearCollection('${c.name}')"><i class="bi bi-trash"></i> Очистить</button>
          <button class="btn btn-sm" style="font-size:.75rem;background:#4c0519;border-color:#be123c;color:#fca5a5" onclick="dropCollection('${c.name}')"><i class="bi bi-x-circle"></i> Удалить</button>
          ` : '<span style="color:#555;font-size:.75rem">нельзя удалять</span>'}
        </td>
      </tr>`;
    }).join('') +
    '</tbody></table></div>';
  // Entries are loaded on demand via the select+button, not auto-loaded
  loadIngestJobs();
}

async function loadKBEntries() {
  const col = document.getElementById('kb-browse-col').value;
  const entries = await apiGet('/admin/kb/entries/' + col);
  const tbody = document.getElementById('kb-entries-tbody');
  if (!entries || entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="text-center text-secondary py-4">Нет записей</td></tr>';
    return;
  }
  tbody.innerHTML = entries.map(e => `<tr>
    <td><strong style="font-size:.85rem">${escHtml(e.topic)}</strong></td>
    <td style="font-size:.8rem;color:#8b949e">${escHtml(e.text_preview)}${e.text_preview.length>=200?'…':''}</td>
    <td><button class="btn btn-outline-danger btn-sm" onclick="deleteKBEntry('${col}','${e.point_id}')"><i class="bi bi-trash"></i></button></td>
  </tr>`).join('');
}

async function addKBEntry() {
  const col = document.getElementById('kb-col').value;
  const topic = document.getElementById('kb-topic').value.trim();
  const text = document.getElementById('kb-text').value.trim();
  if (!col) { toast('Выбери коллекцию', false); return; }
  if (!topic || !text) { toast('Заполни тему и текст', false); return; }
  const btn = document.getElementById('kb-add-btn');
  btn.disabled = true; btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Встраиваем...';
  try {
    await apiPost('/admin/kb/add', {collection: col, topic, text});
    toast('Добавлено: ' + topic);
    document.getElementById('kb-topic').value = '';
    document.getElementById('kb-text').value = '';
    refreshSection('kb');
  } catch(e) { toast('Ошибка: ' + e.message, false); }
  finally { btn.disabled = false; btn.innerHTML = '<i class="bi bi-cloud-upload"></i> Добавить'; }
}

async function addKBUrl() {
  const col = document.getElementById('kb-url-col').value;
  const url = document.getElementById('kb-url-input').value.trim();
  const topic = document.getElementById('kb-url-topic').value.trim();
  const source_lang = document.getElementById('kb-url-lang').value;
  if (!col) { toast('Выбери коллекцию', false); return; }
  if (!url) { toast('Введи URL', false); return; }
  const btn = document.getElementById('kb-url-btn');
  const res = document.getElementById('kb-url-result');
  btn.disabled = true; btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Загружаем...';
  res.textContent = '';
  try {
    const data = await apiPost('/admin/kb/ingest-url', {collection: col, url, topic, source_lang});
    toast(`Добавлено ${data.chunks_added} чанков из URL`);
    res.textContent = `✓ ${data.chunks_added} фрагментов добавлено`;
    res.style.color = '#4ade80';
    document.getElementById('kb-url-input').value = '';
    document.getElementById('kb-url-topic').value = '';
    refreshSection('kb');
  } catch(e) { toast('Ошибка: ' + e.message, false); res.textContent = ''; }
  finally { btn.disabled = false; btn.innerHTML = '<i class="bi bi-cloud-download"></i> Загрузить и добавить'; }
}

// ── Multi-file upload ─────────────────────────────────────────────────────────
const _TRANSLIT = {
  'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
  'и':'i','й':'j','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
  'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
  'щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
};

function _slugify(s) {
  s = s.toLowerCase().split('').map(c => _TRANSLIT[c] ?? c).join('');
  s = s.replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  if (s.length < 3) s = 'kb_' + s;
  return s.slice(0, 50);
}

function _deriveCollection(filename) {
  return _slugify(filename.replace(/\.[^.]+$/, ''));
}

function _fmtSize(b) {
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
  return (b/1048576).toFixed(1) + ' MB';
}

let _filesToUpload = [];

function onFilesDrop(e) {
  e.preventDefault();
  document.getElementById('kb-drop-zone').style.borderColor = '#30363d';
  onFilesSelected(e.dataTransfer.files);
}

function onFilesSelected(files) {
  const arr = Array.from(files);
  if (!arr.length) return;
  _filesToUpload = arr;
  const tbody = document.getElementById('kb-file-rows');
  tbody.innerHTML = arr.map((f, i) => {
    const col = _deriveCollection(f.name);
    const bad = !/^[a-z][a-z0-9_]{2,49}$/.test(col);
    return `<tr id="kf-row-${i}" style="border-bottom:1px solid #1a2030">
      <td style="padding:.4rem .5rem">
        <div style="color:#c9d1d9;word-break:break-all">${escHtml(f.name)}</div>
        <div style="font-size:.7rem;color:#6e7681">${_fmtSize(f.size)}</div>
      </td>
      <td style="padding:.4rem .5rem">
        <input type="text" class="form-control form-control-sm${bad?' border-warning':''}"
               id="kf-col-${i}" value="${escHtml(col)}" placeholder="knowledge_...">
        ${bad?`<div style="font-size:.68rem;color:#f59e0b;margin-top:2px"><i class="bi bi-exclamation-triangle"></i> Скорректируй имя</div>`:''}
      </td>
      <td style="padding:.4rem .5rem">
        <input type="text" class="form-control form-control-sm" id="kf-topic-${i}" placeholder="авто из имени файла">
      </td>
      <td style="padding:.35rem .5rem;text-align:center">
        <button style="background:none;border:none;color:#555;cursor:pointer;font-size:1.1rem;padding:0;line-height:1"
                title="Убрать" onclick="document.getElementById('kf-row-${i}').remove();_filesToUpload[${i}]=null">✕</button>
      </td>
    </tr>`;
  }).join('');
  document.getElementById('kb-file-list').style.display = '';
  document.getElementById('kb-file-btn').style.display = '';
  document.getElementById('kb-file-result').textContent = '';
}

async function uploadAllFiles() {
  const btn = document.getElementById('kb-file-btn');
  const res = document.getElementById('kb-file-result');
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Загружаем...';
  res.textContent = '';
  let ok = 0, fail = 0;
  for (let i = 0; i < _filesToUpload.length; i++) {
    const file = _filesToUpload[i];
    if (!file) continue;
    const col = document.getElementById('kf-col-' + i)?.value?.trim() || '';
    const topic = document.getElementById('kf-topic-' + i)?.value?.trim() || '';
    if (!col) { toast(`Укажи коллекцию для: ${file.name}`, false); fail++; continue; }
    if (!/^[a-z][a-z0-9_]{2,49}$/.test(col)) {
      toast(`Некорректное имя коллекции «${col}» для: ${file.name}`, false); fail++; continue;
    }
    try {
      const fd = new FormData();
      fd.append('collection', col);
      fd.append('topic', topic);
      fd.append('source_lang', 'auto');
      fd.append('file', file);
      const r = await fetch(API + '/admin/kb/ingest-file', {
        method: 'POST', headers: {'X-Admin-Token': TOKEN}, body: fd,
      });
      if (!r.ok) throw new Error(await r.text());
      ok++;
      const row = document.getElementById('kf-row-' + i);
      if (row) { row.style.opacity = '.4'; row.style.pointerEvents = 'none'; }
    } catch(e) {
      toast(`${file.name}: ${e.message}`, false);
      fail++;
    }
  }
  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-upload"></i> Загрузить все';
  if (ok) {
    res.textContent = `✓ ${ok} файл${ok===1?'':ok<5?'а':'ов'} в очереди${fail?', ошибок: '+fail:''}`;
    res.style.color = fail ? '#f59e0b' : '#4ade80';
    document.getElementById('kb-file-input').value = '';
    _filesToUpload = [];
    loadIngestJobs();
  } else {
    res.textContent = 'Ничего не загружено';
    res.style.color = '#f87171';
  }
}

let _jobsPollTimer = null;
let _jobsHadRunning = false;
let _jobsPollActive = false;

function _escAttr(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function loadIngestJobs() {
  const container = document.getElementById('ingest-jobs-list');
  if (!container) return;
  clearTimeout(_jobsPollTimer);
  try {
    const r = await fetch(API + '/admin/kb/jobs', {headers: {'X-Admin-Token': TOKEN}});
    if (!r.ok) return;
    const jobs = await r.json();
    if (!jobs.length) {
      container.innerHTML = '<div style="font-size:.8rem;color:#555;padding:.4rem">Задач нет</div>';
      _jobsHadRunning = false;
      return;
    }
    const hasActive = jobs.some(j => j.status === 'running' || j.status === 'queued');
    container.innerHTML = jobs.map(j => {
      const icons = {running: '⏳', queued: '🕐', done: '✅', error: '❌'};
      const ic = icons[j.status] || '❓';
      const ts = new Date(j.created_at).toLocaleString('ru-RU', {hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'});
      const errText = _escAttr(j.error || '');
      const elapsedSec = Math.floor((Date.now() - new Date(j.updated_at || j.created_at).getTime()) / 1000);
      const elapsedStr = elapsedSec >= 60 ? `${Math.floor(elapsedSec/60)}м ${elapsedSec%60}с` : `${elapsedSec}с`;

      let actionBtn;
      if (j.status === 'running' || j.status === 'queued') {
        actionBtn = `<button onclick="cancelJob('${j.id}')" style="font-size:.7rem;padding:1px 6px;background:transparent;border:1px solid #f87171;color:#f87171;border-radius:4px;cursor:pointer">Стоп</button>`;
      } else if (j.status === 'error') {
        actionBtn = `<button onclick="retryJob('${j.id}')" style="font-size:.7rem;padding:1px 6px;background:transparent;border:1px solid #7cb9e8;color:#7cb9e8;border-radius:4px;cursor:pointer;margin-right:2px">↻</button>`
                  + `<button onclick="deleteJob('${j.id}')" style="font-size:.7rem;padding:1px 6px;background:transparent;border:1px solid #444;color:#666;border-radius:4px;cursor:pointer">✕</button>`;
      } else {
        actionBtn = `<button onclick="deleteJob('${j.id}')" style="font-size:.7rem;padding:1px 6px;background:transparent;border:1px solid #444;color:#666;border-radius:4px;cursor:pointer">✕</button>`;
      }

      // Inline status summary for non-running jobs
      let statusLine = '';
      if (j.status === 'done') {
        statusLine = `<span style="color:#4ade80;font-size:.72rem">✓ ${j.chunks_added} фрагментов</span>`;
      } else if (j.status === 'queued') {
        statusLine = `<span style="color:#8b949e;font-size:.72rem">в очереди</span>`;
      } else if (j.status === 'error') {
        statusLine = `<span style="color:#f87171;font-size:.72rem" title="${errText}">${_escAttr((j.error||'').slice(0,80))}</span>`;
      }

      // 3 progress bars for running jobs
      let progressBars = '';
      if (j.status === 'running') {
        const ft = Math.max(j.files_total || 1, 1);
        const fe = j.files_extracted || 0;
        const fc = j.files_chunked || 0;
        const ct = j.chunks_total || 0;
        const cd = j.chunks_done || 0;
        const pctEx  = Math.min(100, Math.round(fe / ft * 100));
        const pctChk = Math.min(100, Math.round(fc / ft * 100));
        const pctEmb = ct > 0 ? Math.min(100, Math.round(cd / ct * 100)) : 0;
        const mkBar = (pct, grad, lbl) => {
          return `<div style="display:flex;align-items:center;gap:.45rem;margin-top:3px">
            <div style="width:110px;height:5px;background:#1e2d3d;border-radius:3px;overflow:hidden;flex-shrink:0">
              <div style="height:100%;width:${pct}%;background:${grad};transition:width .4s ease"></div>
            </div>
            <span style="font-size:.67rem;color:#8b949e;white-space:nowrap">${lbl}</span>
          </div>`;
        };
        progressBars = `<div style="margin-top:5px;padding-left:18px">
          ${mkBar(pctEx,  'linear-gradient(90deg,#38bdf8,#60a5fa)', `Разархивация: ${fe} / ${j.files_total||'?'} файлов`)}
          ${mkBar(pctChk, 'linear-gradient(90deg,#a78bfa,#c084fc)', `Чанкинг: ${fc} / ${j.files_total||'?'} файлов`)}
          ${mkBar(pctEmb, 'linear-gradient(90deg,#4ade80,#86efac)', `Эмбеддинг: ${cd} / ${ct||'?'} фр. · ${elapsedStr}`)}
        </div>`;
      }

      return `<div style="padding:.45rem .5rem;border-bottom:1px solid #1e2d3d;font-size:.78rem">
        <div style="display:flex;align-items:center;gap:.5rem">
          <span>${ic}</span>
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#c9d1d9" title="${_escAttr(j.filename)}">${_escAttr(j.filename)}</span>
          <span style="color:#7cb9e8;white-space:nowrap;flex-shrink:0">${_escAttr(j.collection)}</span>
          ${statusLine ? `<span style="white-space:nowrap;flex-shrink:0">${statusLine}</span>` : ''}
          <span style="color:#555;white-space:nowrap;flex-shrink:0">${ts}</span>
          <span style="white-space:nowrap;flex-shrink:0">${actionBtn}</span>
        </div>
        ${progressBars}
      </div>`;
    }).join('');
    // refresh KB stats when transitioning active → all done
    if (_jobsHadRunning && !hasActive) refreshSection('kb');
    _jobsHadRunning = hasActive;
    // poll every 2s while any job is active
    const freshActive = jobs.some(j => j.status === 'running' || j.status === 'queued');
    _jobsPollActive = freshActive;
    if (freshActive) _jobsPollTimer = setTimeout(loadIngestJobs, 2000);
  } catch(e) { /* silent */ }
}

async function cancelJob(jobId) {
  try {
    const r = await fetch(API + '/admin/kb/jobs/' + jobId + '/cancel', {
      method: 'POST', headers: {'X-Admin-Token': TOKEN}
    });
    if (!r.ok) throw new Error(await r.text());
    toast('Задача отменена');
    loadIngestJobs();
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

async function deleteJob(jobId) {
  try {
    const r = await fetch(API + '/admin/kb/jobs/' + jobId, {
      method: 'DELETE', headers: {'X-Admin-Token': TOKEN}
    });
    if (!r.ok) throw new Error(await r.text());
    loadIngestJobs();
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

async function retryJob(jobId) {
  try {
    const r = await fetch(API + '/admin/kb/jobs/' + jobId + '/retry', {
      method: 'POST', headers: {'X-Admin-Token': TOKEN}
    });
    if (!r.ok) throw new Error(await r.text());
    toast('Задача поставлена в очередь повторно');
    loadIngestJobs();
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

async function deleteKBEntry(col, id) {
  if (!confirm('Удалить запись?')) return;
  try {
    await apiDelete('/admin/kb/entry/' + col + '/' + id);
    toast('Удалено');
    loadKBEntries();
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

// ── Collection management ─────────────────────────────────────────────────────
async function createCollection() {
  const name = document.getElementById('new-col-name').value.trim();
  if (!name) { toast('Введи имя коллекции', false); return; }
  try {
    const r = await apiPost('/admin/kb/collections', {name});
    toast('Коллекция ' + r.created + ' создана');
    document.getElementById('new-col-name').value = '';
    document.getElementById('kb-new-col-form').style.display = 'none';
    refreshSection('kb');
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

async function clearCollection(name) {
  if (!confirm('Очистить все записи в «' + name + '»? Это нельзя отменить.')) return;
  try {
    await apiDelete('/admin/kb/collections/' + name + '?confirm=yes');
    toast('Коллекция ' + name + ' очищена');
    refreshSection('kb');
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}

async function dropCollection(name) {
  if (!confirm('УДАЛИТЬ коллекцию «' + name + '» полностью? Все данные будут потеряны!')) return;
  if (!confirm('Подтверди ещё раз: удалить «' + name + '»?')) return;
  try {
    await apiDelete('/admin/kb/collections/' + name + '?confirm=drop');
    toast('Коллекция ' + name + ' удалена');
    refreshSection('kb');
  } catch(e) { toast('Ошибка: ' + e.message, false); }
}


async function addKBDataset() {
  const url = document.getElementById('kb-ds-url').value.trim();
  const col = document.getElementById('kb-ds-col').value;
  const prefix = document.getElementById('kb-ds-prefix').value.trim();
  const qfield = document.getElementById('kb-ds-qfield').value.trim();
  const afield = document.getElementById('kb-ds-afield').value.trim();
  const limit = parseInt(document.getElementById('kb-ds-limit').value) || 0;
  const source_lang = document.getElementById('kb-ds-lang').value;
  if (!col) { toast('Выбери коллекцию', false); return; }
  if (!url) { toast('Введи URL датасета', false); return; }

  const btn = document.getElementById('kb-ds-btn');
  const res = document.getElementById('kb-ds-result');
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Загружаем и встраиваем...';
  res.textContent = 'Скачиваем → встраиваем оригинал + перевод (займёт несколько минут)...';
  res.style.color = '#8b949e';
  try {
    const data = await apiPost('/admin/kb/ingest-dataset', {
      collection: col,
      dataset_url: url,
      question_field: qfield,
      answer_field: afield,
      topic_prefix: prefix,
      source_lang,
      limit,
    });
    toast(`Добавлено ${data.chunks_added} записей из датасета`);
    res.textContent = `✓ ${data.chunks_added} записей добавлено`;
    res.style.color = '#4ade80';
    document.getElementById('kb-ds-url').value = '';
    refreshSection('kb');
  } catch(e) {
    toast('Ошибка: ' + e.message, false);
    res.textContent = 'Ошибка — см. детали в toast';
    res.style.color = '#f87171';
  }
  finally { btn.disabled = false; btn.innerHTML = '<i class="bi bi-cloud-arrow-down"></i> Импортировать датасет'; }
}

// ── HuggingFace catalog search ────────────────────────────────────────────────
async function searchHF() {
  const q = document.getElementById('hf-search-q').value.trim();
  if (!q) { toast('Введи запрос для поиска', false); return; }
  await _renderHFResults(await apiGet('/admin/kb/hf-search?q=' + encodeURIComponent(q) + '&limit=20'));
}

async function searchHFTag(tag) {
  document.getElementById('hf-search-q').value = '';
  await _renderHFResults(await apiGet('/admin/kb/hf-search?tag=' + encodeURIComponent(tag) + '&limit=20'));
}

async function searchHFQ(q) {
  document.getElementById('hf-search-q').value = q;
  await _renderHFResults(await apiGet('/admin/kb/hf-search?q=' + encodeURIComponent(q) + '&limit=20'));
}

async function _renderHFResults(results) {
  const el = document.getElementById('hf-results');
  if (!results || !results.length) { el.innerHTML = '<div style="color:#8b949e;font-size:.85rem">Ничего не найдено</div>'; return; }
  el.innerHTML = '<div class="row g-2">' + results.map(d => `
    <div class="col-md-6">
      <div class="card p-2" style="cursor:pointer;border-color:#2d4a6e" onclick="importHFDataset('${d.id}')">
        <div class="d-flex justify-content-between align-items-start">
          <div style="font-size:.85rem;font-weight:600;color:#e8eaed">${d.id}</div>
          <div style="font-size:.72rem;color:#b0bec5;white-space:nowrap;margin-left:8px">⬇ ${(d.downloads||0).toLocaleString()}</div>
        </div>
        <div style="font-size:.72rem;margin-top:3px">${d.tags.map(t=>`<span style="background:#21262d;color:#a78bfa;border:1px solid #333;border-radius:10px;padding:1px 6px;margin-right:3px">${t}</span>`).join('')}</div>
        <div style="font-size:.75rem;color:#4ade80;margin-top:4px">▶ Импортировать</div>
      </div>
    </div>
  `).join('') + '</div>';
}

function importHFDataset(repoId) {
  // Switch to Datasets tab and fill in the HF URL
  kbTab('dataset');
  const url = 'https://huggingface.co/datasets/' + repoId;
  document.getElementById('kb-ds-url').value = url;
  document.getElementById('kb-ds-col').value = 'knowledge_psych';
  document.getElementById('kb-ds-prefix').value = repoId.split('/').pop();
  document.getElementById('kb-ds-translate').checked = true;
  toast('Датасет выбран: ' + repoId + '. Настрой параметры и нажми «Импортировать».');
}

// ── Init ──────────────────────────────────────────────────────────────────────
if (TOKEN) {
  apiGet('/admin/stats').then(r => { if(r) showApp(); });
}
</script>
</body>
</html>"""


@ui_router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_ui():
    return HTMLResponse(_HTML)
