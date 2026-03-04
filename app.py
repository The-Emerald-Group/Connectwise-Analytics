import os
import requests
import base64
import urllib3
from flask import Flask, jsonify, render_template_string, request
from datetime import datetime, timedelta, timezone
from collections import defaultdict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

CW_SITE        = os.environ.get("CW_SITE", "api-eu.myconnectwise.net")
CW_COMPANY     = os.environ.get("CW_COMPANY", "")
CW_PUBLIC_KEY  = os.environ.get("CW_PUBLIC_KEY", "")
CW_PRIVATE_KEY = os.environ.get("CW_PRIVATE_KEY", "")
CW_CLIENT_ID   = os.environ.get("CW_CLIENT_ID", "")
HTTPS_PROXY    = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
REFRESH_INTERVAL = int(os.environ.get("CW_REFRESH_INTERVAL", "300"))
VERIFY_SSL     = os.environ.get("CW_VERIFY_SSL", "true").lower() != "false"
DAYS_BACK      = int(os.environ.get("CW_DAYS_BACK", "7"))

def get_session():
    s = requests.Session()
    if HTTPS_PROXY:
        s.proxies = {"https": HTTPS_PROXY, "http": HTTPS_PROXY}
    s.verify = VERIFY_SSL
    return s

def get_auth_header():
    creds = f"{CW_COMPANY}+{CW_PUBLIC_KEY}:{CW_PRIVATE_KEY}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "clientId": CW_CLIENT_ID,
        "Content-Type": "application/json"
    }

def cw_get(endpoint, params=None):
    url = f"https://{CW_SITE}/v4_6_release/apis/3.0{endpoint}"
    headers = get_auth_header()
    all_results = []
    page = 1
    page_size = 100
    if params is None:
        params = {}
    session = get_session()
    while True:
        paged_params = {**params, "page": page, "pageSize": page_size}
        response = session.get(url, headers=headers, params=paged_params, timeout=90)
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        all_results.extend(data)
        if len(data) < page_size:
            break
        page += 1
    return all_results


# ─────────────────────────────────────────────────────────────
#  SHARED HTML SHELL  (header + nav + page containers)
# ─────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CW Pulse — Analytics</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@700;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg:       #070810;
  --surface:  #0d0f1c;
  --panel:    #111327;
  --raised:   #161930;
  --border:   rgba(255,255,255,0.06);
  --border2:  rgba(255,255,255,0.1);
  --accent:   #5b6ef5;
  --accent2:  #38e8c5;
  --amber:    #f5c542;
  --red:      #f55b5b;
  --green:    #38e8c5;
  --blue:     #5b6ef5;
  --purple:   #b06ef5;
  --orange:   #f5934b;
  --text:     #e8eaf6;
  --text-dim: #6b7280;
  --text-mid: #9ca3af;
  --font-display: 'Syne', sans-serif;
  --font-body: 'DM Sans', sans-serif;
  --font-mono: 'DM Mono', monospace;
}
* { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { background:var(--bg); color:var(--text); font-family:var(--font-body); font-size:14px; min-height:100vh; overflow-x:hidden; }
body::before { content:''; position:fixed; inset:0; background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.03'/%3E%3C/svg%3E"); pointer-events:none; z-index:0; opacity:0.4; }

/* ── HEADER ── */
header { position:sticky; top:0; z-index:200; background:rgba(7,8,16,0.88); backdrop-filter:blur(20px); border-bottom:1px solid var(--border); padding:0 32px; height:56px; display:flex; align-items:center; justify-content:space-between; }
.logo { font-family:var(--font-display); font-size:1.1rem; font-weight:800; letter-spacing:-0.5px; color:var(--text); }
.logo .dot { color:var(--accent2); }
.logo .sub { font-family:var(--font-mono); font-size:0.65rem; font-weight:400; color:var(--text-dim); margin-left:10px; letter-spacing:2px; text-transform:uppercase; vertical-align:middle; }
.header-right { display:flex; align-items:center; gap:12px; }

/* ── PAGE NAV ── */
.page-nav { display:flex; align-items:center; gap:0; background:var(--panel); border:1px solid var(--border2); border-radius:8px; overflow:hidden; }
.page-btn { font-family:var(--font-mono); font-size:0.7rem; font-weight:500; padding:7px 16px; cursor:pointer; border:none; background:transparent; color:var(--text-dim); transition:all .15s; letter-spacing:0.5px; display:flex; align-items:center; gap:6px; }
.page-btn.active { background:var(--accent); color:white; }
.page-btn:hover:not(.active) { color:var(--text); background:var(--raised); }
.page-btn .page-icon { font-size:.85rem; }

.days-selector { display:flex; align-items:center; gap:0; background:var(--panel); border:1px solid var(--border2); border-radius:8px; overflow:hidden; }
.days-btn { font-family:var(--font-mono); font-size:0.7rem; font-weight:500; padding:6px 12px; cursor:pointer; border:none; background:transparent; color:var(--text-dim); transition:all .15s; letter-spacing:0.5px; }
.days-btn.active { background:var(--accent); color:white; }
.days-btn:hover:not(.active) { color:var(--text); background:var(--raised); }

.status-pill { display:flex; align-items:center; gap:7px; padding:5px 12px; border-radius:20px; background:var(--panel); border:1px solid var(--border2); font-family:var(--font-mono); font-size:0.68rem; color:var(--text-dim); letter-spacing:0.5px; }
.live-dot { width:6px; height:6px; border-radius:50%; background:var(--accent2); animation:livepulse 2s infinite; }
@keyframes livepulse { 0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(56,232,197,0.4)} 50%{opacity:0.7;box-shadow:0 0 0 5px rgba(56,232,197,0)} }

/* ── LAYOUT ── */
.app-body { position:relative; z-index:1; padding:28px 32px 60px; max-width:1600px; margin:0 auto; }
.page { display:none; }
.page.active { display:block; animation:fadeIn .25s ease; }

/* ── CONFIG BANNER ── */
.config-banner { display:none; align-items:center; gap:14px; background:rgba(245,91,91,0.07); border:1px solid rgba(245,91,91,0.2); border-radius:10px; padding:14px 18px; margin-bottom:24px; }
.config-banner.show { display:flex; }
.config-banner h4 { color:var(--red); font-size:.82rem; margin-bottom:3px; }
.config-banner p { font-size:.75rem; color:var(--text-dim); }
.config-banner code { background:rgba(255,255,255,.06); padding:1px 5px; border-radius:3px; color:var(--amber); font-family:var(--font-mono); }

/* ── SECTION ── */
.section { margin-bottom:36px; }
.section-label { font-family:var(--font-mono); font-size:0.62rem; font-weight:500; text-transform:uppercase; letter-spacing:3px; color:var(--text-dim); margin-bottom:14px; display:flex; align-items:center; gap:10px; }
.section-label::after { content:''; flex:1; height:1px; background:var(--border); }

/* ── KPI CARDS ── */
.kpi-row { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:14px; }
.kpi { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:20px 22px; position:relative; overflow:hidden; cursor:default; transition:border-color .2s, transform .2s; }
.kpi:hover { border-color:var(--border2); transform:translateY(-1px); }
.kpi::before { content:''; position:absolute; top:0; left:0; right:0; height:2px; background:var(--kpi-color, var(--accent)); }
.kpi-icon { font-size:1.4rem; margin-bottom:10px; opacity:0.8; }
.kpi-num { font-family:var(--font-display); font-size:2.4rem; font-weight:800; line-height:1; color:var(--kpi-color, var(--text)); transition:opacity .3s; }
.kpi-label-text { font-size:.7rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:1.5px; margin-top:6px; }
.kpi-sub-text { font-family:var(--font-mono); font-size:.65rem; color:var(--text-dim); margin-top:3px; }
.kpi.loading .kpi-num { opacity:0.2; }

/* ── GRID LAYOUTS ── */
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.three-col { display:grid; grid-template-columns:2fr 1fr 1fr; gap:14px; }
@media (max-width:1100px) { .three-col { grid-template-columns:1fr; } .two-col { grid-template-columns:1fr; } }

/* ── CHART PANEL ── */
.chart-panel { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:22px 24px; }
.chart-panel-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:18px; }
.chart-panel-title { font-family:var(--font-display); font-size:.88rem; font-weight:700; }
.chart-panel-badge { font-family:var(--font-mono); font-size:.62rem; padding:3px 9px; border-radius:20px; background:var(--raised); color:var(--text-dim); border:1px solid var(--border); }
.chart-wrap canvas { max-height:240px; }
.chart-wrap.tall canvas { max-height:300px; }

/* ── LEADERBOARD ── */
.leaderboard { background:var(--panel); border:1px solid var(--border); border-radius:12px; overflow:hidden; }
.lb-header { padding:16px 20px; border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; }
.lb-title { font-family:var(--font-display); font-size:.88rem; font-weight:700; }
.lb-tabs { display:flex; gap:0; }
.lb-tab { font-family:var(--font-mono); font-size:.65rem; padding:4px 10px; border-radius:6px; cursor:pointer; color:var(--text-dim); transition:all .15s; border:none; background:transparent; }
.lb-tab.active { background:var(--accent); color:white; }
.lb-tab:hover:not(.active) { color:var(--text); }
.lb-row { display:grid; grid-template-columns:28px 1fr 70px 70px 70px; align-items:center; gap:12px; padding:11px 20px; border-bottom:1px solid var(--border); transition:background .15s; }
.lb-row:last-child { border-bottom:none; }
.lb-row:hover { background:var(--raised); }
.lb-rank { font-family:var(--font-mono); font-size:.72rem; color:var(--text-dim); text-align:center; }
.lb-rank.gold { color:var(--amber); }
.lb-rank.silver { color:#a0aec0; }
.lb-rank.bronze { color:#cd7f32; }
.lb-name { font-size:.82rem; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.lb-sub { font-size:.68rem; color:var(--text-dim); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.lb-bar-wrap { position:relative; height:4px; background:var(--raised); border-radius:2px; margin-top:3px; }
.lb-bar { height:4px; border-radius:2px; background:var(--accent); transition:width .6s ease; }
.lb-val { font-family:var(--font-mono); font-size:.75rem; text-align:right; }
.lb-val.created { color:var(--blue); }
.lb-val.closed { color:var(--green); }
.lb-val.net.pos { color:var(--red); }
.lb-val.net.neg { color:var(--green); }
.lb-val.net.zero { color:var(--text-dim); }

/* ── DATA TABLE ── */
.data-table { width:100%; border-collapse:collapse; }
.data-table th { font-family:var(--font-mono); font-size:.62rem; text-transform:uppercase; letter-spacing:1.5px; color:var(--text-dim); padding:10px 16px; border-bottom:1px solid var(--border); text-align:left; font-weight:500; }
.data-table th.r { text-align:right; }
.data-table td { padding:10px 16px; border-bottom:1px solid var(--border); font-size:.8rem; }
.data-table tr:last-child td { border-bottom:none; }
.data-table tr:hover td { background:var(--raised); }
.data-table td.r { text-align:right; font-family:var(--font-mono); }
.data-table td.clickable { cursor:pointer; }
.data-table td.clickable:hover { color:var(--accent2); }

.badge-c { display:inline-block; background:rgba(91,110,245,0.15); color:var(--blue); border-radius:4px; padding:1px 7px; font-family:var(--font-mono); font-size:.7rem; }
.badge-x { display:inline-block; background:rgba(56,232,197,0.15); color:var(--green); border-radius:4px; padding:1px 7px; font-family:var(--font-mono); font-size:.7rem; }
.badge-n-pos { display:inline-block; background:rgba(245,91,91,0.12); color:var(--red); border-radius:4px; padding:1px 7px; font-family:var(--font-mono); font-size:.7rem; }
.badge-n-neg { display:inline-block; background:rgba(56,232,197,0.12); color:var(--green); border-radius:4px; padding:1px 7px; font-family:var(--font-mono); font-size:.7rem; }
.badge-n-zero { display:inline-block; background:rgba(255,255,255,0.05); color:var(--text-dim); border-radius:4px; padding:1px 7px; font-family:var(--font-mono); font-size:.7rem; }

/* ── SEARCH BAR ── */
.search-bar { display:flex; align-items:center; gap:10px; background:var(--panel); border:1px solid var(--border2); border-radius:8px; padding:8px 14px; margin-bottom:16px; }
.search-bar input { background:none; border:none; outline:none; color:var(--text); font-family:var(--font-body); font-size:.82rem; flex:1; }
.search-bar input::placeholder { color:var(--text-dim); }
.search-icon { color:var(--text-dim); font-size:.9rem; }

/* ── COMPANY CARD GRID ── */
.company-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); gap:14px; }
.company-card { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:18px 20px; cursor:pointer; transition:border-color .2s, transform .2s; }
.company-card:hover { border-color:var(--border2); transform:translateY(-1px); }
.company-card-header { display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:14px; }
.company-name { font-family:var(--font-display); font-size:.95rem; font-weight:700; }
.company-type { font-family:var(--font-mono); font-size:.6rem; padding:2px 8px; border-radius:20px; background:var(--raised); color:var(--text-dim); border:1px solid var(--border); text-transform:uppercase; letter-spacing:1px; }
.company-stats { display:grid; grid-template-columns:repeat(3, 1fr); gap:8px; margin-bottom:12px; }
.cs-box { background:var(--raised); border-radius:8px; padding:10px; text-align:center; }
.cs-val { font-family:var(--font-display); font-size:1.4rem; font-weight:800; line-height:1; }
.cs-lbl { font-size:.6rem; text-transform:uppercase; letter-spacing:1px; color:var(--text-dim); margin-top:3px; }
.company-bar { height:4px; background:var(--raised); border-radius:2px; overflow:hidden; }
.company-bar-fill { height:100%; border-radius:2px; background:linear-gradient(90deg, var(--blue), var(--accent2)); transition:width .6s ease; }

/* ── MODAL ── */
.modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.75); backdrop-filter:blur(8px); z-index:500; align-items:center; justify-content:center; }
.modal-overlay.open { display:flex; }
.modal { background:var(--surface); border:1px solid var(--border2); border-radius:16px; width:min(720px, 95vw); max-height:87vh; overflow-y:auto; animation:modalIn .2s ease; }
@keyframes modalIn { from{opacity:0;transform:scale(.95)} to{opacity:1;transform:scale(1)} }
.modal-header { padding:22px 26px; border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; background:var(--surface); z-index:1; }
.modal-title { font-family:var(--font-display); font-size:1.1rem; font-weight:800; }
.modal-subtitle { font-family:var(--font-mono); font-size:.65rem; color:var(--text-dim); margin-top:3px; }
.modal-close { background:none; border:none; color:var(--text-dim); cursor:pointer; font-size:1.2rem; padding:4px; border-radius:6px; transition:color .15s, background .15s; }
.modal-close:hover { color:var(--text); background:var(--raised); }
.modal-body { padding:24px 26px; }
.modal-kpis { display:grid; grid-template-columns:repeat(4, 1fr); gap:10px; margin-bottom:20px; }
.modal-kpi { background:var(--panel); border-radius:10px; padding:14px; text-align:center; }
.modal-kpi-val { font-family:var(--font-display); font-size:1.6rem; font-weight:800; line-height:1; }
.modal-kpi-lbl { font-size:.6rem; text-transform:uppercase; letter-spacing:1.5px; color:var(--text-dim); margin-top:3px; }
.modal-section-title { font-family:var(--font-mono); font-size:.62rem; text-transform:uppercase; letter-spacing:2px; color:var(--text-dim); margin-bottom:10px; margin-top:18px; }
.modal-chart-wrap { height:160px; margin-bottom:4px; }

/* ── PROGRESS BAR ── */
.progress-row { margin-bottom:9px; }
.progress-label { display:flex; justify-content:space-between; font-size:.75rem; margin-bottom:4px; }
.progress-track { height:5px; background:var(--raised); border-radius:3px; overflow:hidden; }
.progress-fill { height:100%; border-radius:3px; transition:width .6s ease; }

/* ── LOADING ── */
.loading-state { display:flex; align-items:center; justify-content:center; gap:10px; padding:50px; color:var(--text-dim); font-size:.8rem; font-family:var(--font-mono); }
.spin { width:16px; height:16px; border:2px solid var(--border); border-top-color:var(--accent2); border-radius:50%; animation:spin .7s linear infinite; flex-shrink:0; }
@keyframes spin { to { transform:rotate(360deg); } }
.err-state { padding:20px; color:var(--red); font-family:var(--font-mono); font-size:.78rem; }

/* ── ANIMATIONS ── */
.fade-in { animation:fadeIn .3s ease forwards; }
@keyframes fadeIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }

@media (max-width:768px) { .app-body { padding:16px; } header { padding:0 16px; } .kpi-row { grid-template-columns:1fr 1fr; } .modal-kpis { grid-template-columns:1fr 1fr; } }
</style>
</head>
<body>

<header>
  <div class="logo">CW<span class="dot">·</span>Pulse <span class="sub">Analytics</span></div>
  <div class="header-right">
    <nav class="page-nav">
      <button class="page-btn active" data-page="technicians"><span class="page-icon">👤</span> Technicians</button>
      <button class="page-btn" data-page="customers"><span class="page-icon">🏢</span> Customers</button>
    </nav>
    <div class="days-selector" id="days-selector">
      <button class="days-btn" data-days="1">1D</button>
      <button class="days-btn" data-days="7">7D</button>
      <button class="days-btn" data-days="14">14D</button>
      <button class="days-btn" data-days="30">30D</button>
      <button class="days-btn" data-days="90">90D</button>
    </div>
    <div class="status-pill">
      <div class="live-dot"></div>
      <span id="status-text">Loading…</span>
    </div>
  </div>
</header>

<div class="app-body">
  <div class="config-banner" id="config-banner">
    <div style="font-size:1.2rem">⚠</div>
    <div>
      <h4>ConnectWise API not configured</h4>
      <p>Set <code>CW_COMPANY</code>, <code>CW_PUBLIC_KEY</code>, <code>CW_PRIVATE_KEY</code>, <code>CW_CLIENT_ID</code> in your environment.</p>
    </div>
  </div>

  <!-- ══════════════ PAGE 1: TECHNICIANS ══════════════ -->
  <div class="page active" id="page-technicians">

    <div class="section">
      <div class="section-label">Overview</div>
      <div class="kpi-row">
        <div class="kpi loading" style="--kpi-color:var(--blue)"><div class="kpi-icon">📥</div><div class="kpi-num" id="kpi-created">—</div><div class="kpi-label-text">Tickets Created</div><div class="kpi-sub-text" id="kpi-created-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--green)"><div class="kpi-icon">✅</div><div class="kpi-num" id="kpi-closed">—</div><div class="kpi-label-text">Tickets Closed</div><div class="kpi-sub-text" id="kpi-closed-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--amber)"><div class="kpi-icon">📊</div><div class="kpi-num" id="kpi-net">—</div><div class="kpi-label-text">Net Change</div><div class="kpi-sub-text" id="kpi-net-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--accent2)"><div class="kpi-icon">📈</div><div class="kpi-num" id="kpi-rate">—</div><div class="kpi-label-text">Close Rate</div><div class="kpi-sub-text" id="kpi-rate-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--purple)"><div class="kpi-icon">👥</div><div class="kpi-num" id="kpi-users">—</div><div class="kpi-label-text">Active Techs</div><div class="kpi-sub-text" id="kpi-users-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--amber)"><div class="kpi-icon">🗂</div><div class="kpi-num" id="kpi-boards">—</div><div class="kpi-label-text">Active Boards</div><div class="kpi-sub-text" id="kpi-boards-sub">…</div></div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Trends</div>
      <div class="three-col">
        <div class="chart-panel">
          <div class="chart-panel-header"><div class="chart-panel-title">Daily Volume</div><span class="chart-panel-badge" id="trend-badge">—</span></div>
          <div class="chart-wrap tall"><canvas id="trendChart"></canvas></div>
        </div>
        <div class="chart-panel">
          <div class="chart-panel-header"><div class="chart-panel-title">By Board</div><span class="chart-panel-badge">Distribution</span></div>
          <div style="display:flex;align-items:center;justify-content:center;height:220px"><canvas id="boardDonut" style="max-height:220px;max-width:220px"></canvas></div>
        </div>
        <div class="chart-panel">
          <div class="chart-panel-header"><div class="chart-panel-title">Created vs Closed</div><span class="chart-panel-badge">Ratio</span></div>
          <div style="display:flex;align-items:center;justify-content:center;height:220px"><canvas id="ratioChart" style="max-height:220px;max-width:220px"></canvas></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Performance</div>
      <div class="two-col">
        <div class="leaderboard">
          <div class="lb-header">
            <div class="lb-title">Technician Leaderboard</div>
            <div class="lb-tabs">
              <button class="lb-tab active" data-sort="total">Total</button>
              <button class="lb-tab" data-sort="closed">Closed</button>
              <button class="lb-tab" data-sort="created">Created</button>
            </div>
          </div>
          <div id="lb-body"><div class="loading-state"><div class="spin"></div>Loading…</div></div>
        </div>
        <div class="chart-panel">
          <div class="chart-panel-header"><div class="chart-panel-title">Board Breakdown</div><span class="chart-panel-badge" id="board-count-badge">—</span></div>
          <div style="overflow-x:auto">
            <table class="data-table">
              <thead><tr><th>Board</th><th class="r">Created</th><th class="r">Closed</th><th class="r">Net</th></tr></thead>
              <tbody id="board-tbody"><tr><td colspan="4"><div class="loading-state"><div class="spin"></div>Loading…</div></td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Technician Activity</div>
      <div class="chart-panel">
        <div class="chart-panel-header"><div class="chart-panel-title">Per-Technician Volume</div><span class="chart-panel-badge">Created vs Closed</span></div>
        <div class="chart-wrap tall"><canvas id="userBarChart"></canvas></div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Cumulative View</div>
      <div class="chart-panel">
        <div class="chart-panel-header"><div class="chart-panel-title">Running Totals Over Period</div><span class="chart-panel-badge" id="cumul-badge">—</span></div>
        <div class="chart-wrap tall"><canvas id="cumulChart"></canvas></div>
      </div>
    </div>
  </div>
  <!-- end page-technicians -->

  <!-- ══════════════ PAGE 2: CUSTOMERS ══════════════ -->
  <div class="page" id="page-customers">

    <div class="section">
      <div class="section-label">Customer Overview</div>
      <div class="kpi-row">
        <div class="kpi loading" style="--kpi-color:var(--orange)"><div class="kpi-icon">🏢</div><div class="kpi-num" id="ckpi-companies">—</div><div class="kpi-label-text">Companies</div><div class="kpi-sub-text" id="ckpi-companies-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--blue)"><div class="kpi-icon">📥</div><div class="kpi-num" id="ckpi-created">—</div><div class="kpi-label-text">Tickets Created</div><div class="kpi-sub-text" id="ckpi-created-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--green)"><div class="kpi-icon">✅</div><div class="kpi-num" id="ckpi-closed">—</div><div class="kpi-label-text">Tickets Closed</div><div class="kpi-sub-text" id="ckpi-closed-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--accent2)"><div class="kpi-icon">📈</div><div class="kpi-num" id="ckpi-rate">—</div><div class="kpi-label-text">Avg Close Rate</div><div class="kpi-sub-text" id="ckpi-rate-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--red)"><div class="kpi-icon">🔥</div><div class="kpi-num" id="ckpi-busiest">—</div><div class="kpi-label-text">Busiest Company</div><div class="kpi-sub-text" id="ckpi-busiest-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--amber)"><div class="kpi-icon">⚠️</div><div class="kpi-num" id="ckpi-unresolved">—</div><div class="kpi-label-text">Net Change</div><div class="kpi-sub-text" id="ckpi-unresolved-sub">…</div></div>
        <div class="kpi loading" style="--kpi-color:var(--red)"><div class="kpi-icon">🚨</div><div class="kpi-num" id="ckpi-open">—</div><div class="kpi-label-text">Total Open Now</div><div class="kpi-sub-text" id="ckpi-open-sub">…</div></div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Company Volume</div>
      <div class="two-col">
        <div class="chart-panel">
          <div class="chart-panel-header"><div class="chart-panel-title">Top Companies by Tickets</div><span class="chart-panel-badge">Created vs Closed</span></div>
          <div class="chart-wrap tall"><canvas id="companyBarChart"></canvas></div>
        </div>
        <div class="chart-panel">
          <div class="chart-panel-header"><div class="chart-panel-title">Share of Total Volume</div><span class="chart-panel-badge">Distribution</span></div>
          <div style="display:flex;align-items:center;justify-content:center;height:280px"><canvas id="companyDonut" style="max-height:280px;max-width:280px"></canvas></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Company Rankings</div>
      <div class="two-col">
        <div class="leaderboard" id="company-leaderboard">
          <div class="lb-header">
            <div class="lb-title">Company Leaderboard</div>
            <div class="lb-tabs">
              <button class="lb-tab clb-tab active" data-sort="total">Total</button>
              <button class="lb-tab clb-tab" data-sort="open">Open Now</button>
              <button class="lb-tab clb-tab" data-sort="created">Created</button>
              <button class="lb-tab clb-tab" data-sort="closed">Closed</button>
              <button class="lb-tab clb-tab" data-sort="net">Net</button>
            </div>
          </div>
          <div id="clb-body"><div class="loading-state"><div class="spin"></div>Loading…</div></div>
        </div>
        <div class="chart-panel">
          <div class="chart-panel-header"><div class="chart-panel-title">Close Rate by Company</div><span class="chart-panel-badge">Top 10</span></div>
          <div class="chart-wrap tall"><canvas id="closeRateChart"></canvas></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">All Companies</div>
      <div class="chart-panel">
        <div class="chart-panel-header">
          <div class="chart-panel-title">Company Directory</div>
          <span class="chart-panel-badge" id="company-dir-badge">—</span>
        </div>
        <div class="search-bar"><span class="search-icon">🔍</span><input type="text" id="company-search" placeholder="Search companies…"></div>
        <div style="overflow-x:auto">
          <table class="data-table">
            <thead><tr><th>Company</th><th class="r">Open Now</th><th class="r">Created</th><th class="r">Closed</th><th class="r">Net</th><th class="r">Close Rate</th><th class="r">Contacts</th></tr></thead>
            <tbody id="company-tbody"><tr><td colspan="6"><div class="loading-state"><div class="spin"></div>Loading…</div></td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Live Queue</div>
      <div class="two-col">
        <div class="chart-panel">
          <div class="chart-panel-header"><div class="chart-panel-title">Open Tickets by Company</div><span class="chart-panel-badge" id="open-count-badge">—</span></div>
          <div class="chart-wrap tall"><canvas id="openTicketsChart"></canvas></div>
        </div>
        <div class="chart-panel">
          <div class="chart-panel-header"><div class="chart-panel-title">Open vs Closed (Period) — Top 10</div><span class="chart-panel-badge">Comparison</span></div>
          <div class="chart-wrap tall"><canvas id="openVsClosedChart"></canvas></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Daily Trend by Top Companies</div>
      <div class="chart-panel">
        <div class="chart-panel-header"><div class="chart-panel-title">Top 5 Companies — Daily Created</div><span class="chart-panel-badge" id="company-trend-badge">—</span></div>
        <div class="chart-wrap tall"><canvas id="companyTrendChart"></canvas></div>
      </div>
    </div>

  </div>
  <!-- end page-customers -->

</div>

<!-- ── TECH MODAL ── -->
<div class="modal-overlay" id="tech-modal">
  <div class="modal">
    <div class="modal-header">
      <div><div class="modal-title" id="tech-modal-name">—</div><div class="modal-subtitle" id="tech-modal-sub">—</div></div>
      <button class="modal-close" onclick="document.getElementById('tech-modal').classList.remove('open')">✕</button>
    </div>
    <div class="modal-body" id="tech-modal-body"></div>
  </div>
</div>

<!-- ── COMPANY MODAL ── -->
<div class="modal-overlay" id="company-modal">
  <div class="modal">
    <div class="modal-header">
      <div><div class="modal-title" id="company-modal-name">—</div><div class="modal-subtitle" id="company-modal-sub">—</div></div>
      <button class="modal-close" onclick="document.getElementById('company-modal').classList.remove('open')">✕</button>
    </div>
    <div class="modal-body" id="company-modal-body"></div>
  </div>
</div>

<script>
const DEFAULT_DAYS = parseInt('{{ days_back }}') || 7;
const REFRESH_INTERVAL = parseInt('{{ refresh_interval }}') || 300;

let currentDays = DEFAULT_DAYS;
let techData = null;
let customerData = null;
let techCharts = {};
let customerCharts = {};
let currentPage = 'technicians';
let allCompanies = [];
let sortedTechs = [];
let sortedCompanies = [];
let refreshTimer = null;

const BLUE='#5b6ef5', GREEN='#38e8c5', AMBER='#f5c542', RED='#f55b5b', PURPLE='#b06ef5', ORANGE='#f5934b';
const CHART_COLORS = [BLUE, GREEN, AMBER, RED, PURPLE, ORANGE, '#38b6e8', '#c5f542', '#f542a7', '#42f5e0'];
const GRID = 'rgba(255,255,255,0.05)', TICK = '#6b7280';
function baseScales() {
  return {
    x: { ticks:{color:TICK, font:{family:'DM Mono',size:10}}, grid:{color:GRID} },
    y: { ticks:{color:TICK, font:{family:'DM Mono',size:10}}, grid:{color:GRID}, beginAtZero:true }
  };
}
function destroyCharts(obj) { Object.values(obj).forEach(c=>{try{c.destroy()}catch(e){}}); }

// ── PAGE NAV ──
document.querySelectorAll('.page-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.page-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    currentPage = btn.dataset.page;
    document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
    document.getElementById('page-' + currentPage).classList.add('active');
    if (currentPage === 'customers' && !customerData) loadCustomers();
  });
});

// ── DAYS ──
document.querySelectorAll('.days-btn').forEach(btn => {
  if (parseInt(btn.dataset.days) === DEFAULT_DAYS) btn.classList.add('active');
  btn.addEventListener('click', () => {
    document.querySelectorAll('.days-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    currentDays = parseInt(btn.dataset.days);
    techData = null; customerData = null;
    loadTechs();
    if (currentPage === 'customers') loadCustomers();
  });
});

// ── LEADERBOARD SORT (TECH) ──
document.querySelectorAll('.lb-tab:not(.clb-tab)').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.lb-tab:not(.clb-tab)').forEach(t=>t.classList.remove('active'));
    tab.classList.add('active');
    if (techData) renderTechLeaderboard(techData.users, tab.dataset.sort);
  });
});

// ── LEADERBOARD SORT (COMPANY) ──
document.querySelectorAll('.clb-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.clb-tab').forEach(t=>t.classList.remove('active'));
    tab.classList.add('active');
    if (customerData) renderCompanyLeaderboard(customerData.companies, tab.dataset.sort);
  });
});

// ── COMPANY SEARCH ──
document.getElementById('company-search').addEventListener('input', e => {
  const q = e.target.value.toLowerCase();
  const filtered = allCompanies.filter(c => c.name.toLowerCase().includes(q));
  renderCompanyTable(filtered);
});

// ── MODAL CLOSE ON OVERLAY ──
['tech-modal','company-modal'].forEach(id => {
  document.getElementById(id).addEventListener('click', e => {
    if (e.target === document.getElementById(id)) document.getElementById(id).classList.remove('open');
  });
});

// ────────────────────────────────────
//  TECHNICIAN PAGE
// ────────────────────────────────────
async function loadTechs() {
  document.getElementById('status-text').textContent = 'Loading…';
  try {
    const res = await fetch(`/api/ticket-stats?days=${currentDays}`);
    const data = await res.json();
    if (data.error) { document.getElementById('status-text').textContent = 'Error'; return; }
    techData = data;
    renderTechs(data);
    const now = new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    document.getElementById('status-text').textContent = `Updated ${now}`;
  } catch(e) { document.getElementById('status-text').textContent = 'Failed'; }
}

function renderTechs(data) {
  destroyCharts(techCharts); techCharts = {};
  const { totals, users, daily, boards } = data;
  const net = totals.created - totals.closed;
  const rate = totals.created > 0 ? ((totals.closed/totals.created)*100).toFixed(1) : 0;

  // KPIs
  const setKpi = (id, val, color) => { const el = document.getElementById(id); el.textContent = val; if(color) el.style.color = color; };
  setKpi('kpi-created', totals.created);
  setKpi('kpi-closed', totals.closed);
  setKpi('kpi-net', net >= 0 ? `+${net}` : `${net}`, net > 0 ? RED : net < 0 ? GREEN : '#6b7280');
  setKpi('kpi-rate', `${rate}%`, parseFloat(rate) >= 100 ? GREEN : parseFloat(rate) >= 70 ? AMBER : RED);
  setKpi('kpi-users', users.length);
  setKpi('kpi-boards', (boards||[]).length);
  const pd = v => currentDays > 0 ? (v/currentDays).toFixed(1) : 0;
  document.getElementById('kpi-created-sub').textContent = `${pd(totals.created)}/day avg`;
  document.getElementById('kpi-closed-sub').textContent = `${pd(totals.closed)}/day avg`;
  document.getElementById('kpi-net-sub').textContent = net > 0 ? 'Queue growing' : net < 0 ? 'Queue shrinking' : 'In balance';
  document.getElementById('kpi-rate-sub').textContent = parseFloat(rate) >= 100 ? 'Keeping up' : 'Backlog growing';
  document.getElementById('kpi-users-sub').textContent = `In last ${currentDays} days`;
  document.getElementById('kpi-boards-sub').textContent = 'With activity';
  document.querySelectorAll('#page-technicians .kpi').forEach(k=>k.classList.remove('loading'));

  // Trend badge
  const busiest = daily.reduce((a,b)=>(a.created+a.closed>b.created+b.closed?a:b), daily[0]||{});
  document.getElementById('trend-badge').textContent = busiest.date ? `Busiest: ${busiest.date}` : `Last ${currentDays} days`;

  techCharts.trend = new Chart(document.getElementById('trendChart'), { type:'bar', data:{ labels:daily.map(d=>d.date), datasets:[ {label:'Created',data:daily.map(d=>d.created),backgroundColor:'rgba(91,110,245,0.5)',borderColor:BLUE,borderWidth:1,borderRadius:3}, {label:'Closed',data:daily.map(d=>d.closed),backgroundColor:'rgba(56,232,197,0.5)',borderColor:GREEN,borderWidth:1,borderRadius:3} ] }, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{labels:{color:TICK,font:{family:'DM Mono',size:10}}}}, scales:baseScales() } });

  const topBs = (boards||[]).slice(0,8);
  techCharts.donut = new Chart(document.getElementById('boardDonut'), { type:'doughnut', data:{ labels:topBs.map(b=>b.name), datasets:[{data:topBs.map(b=>b.created+b.closed), backgroundColor:CHART_COLORS, borderColor:'#0d0f1c', borderWidth:2, hoverOffset:6}] }, options:{ responsive:true, maintainAspectRatio:false, cutout:'68%', plugins:{legend:{position:'bottom',labels:{color:TICK,font:{family:'DM Mono',size:9},boxWidth:10,padding:8}}} } });

  techCharts.ratio = new Chart(document.getElementById('ratioChart'), { type:'doughnut', data:{ labels:['Closed','Still Open'], datasets:[{data:[totals.closed, Math.max(0,totals.created-totals.closed)], backgroundColor:[GREEN,RED], borderColor:'#0d0f1c', borderWidth:2, hoverOffset:6}] }, options:{ responsive:true, maintainAspectRatio:false, cutout:'68%', plugins:{ legend:{position:'bottom',labels:{color:TICK,font:{family:'DM Mono',size:10},boxWidth:10,padding:8}}, tooltip:{callbacks:{label:ctx=>` ${ctx.raw} (${totals.created>0?((ctx.raw/totals.created)*100).toFixed(1):0}%)`}} } } });

  renderTechLeaderboard(users, 'total');

  // Board table
  document.getElementById('board-count-badge').textContent = `${(boards||[]).length} boards`;
  const bHtml = [...(boards||[])].sort((a,b)=>(b.created+b.closed)-(a.created+a.closed)).map(b=>{
    const n=b.created-b.closed;
    const nb = n>0?`<span class="badge-n-pos">+${n}</span>`:n<0?`<span class="badge-n-neg">${n}</span>`:`<span class="badge-n-zero">0</span>`;
    return `<tr><td>${b.name}</td><td class="r"><span class="badge-c">${b.created}</span></td><td class="r"><span class="badge-x">${b.closed}</span></td><td class="r">${nb}</td></tr>`;
  }).join('');
  document.getElementById('board-tbody').innerHTML = bHtml || '<tr><td colspan="4" style="color:var(--text-dim);text-align:center;padding:20px">No board data</td></tr>';

  // User bar chart
  const top10 = users.slice(0,10);
  techCharts.userBar = new Chart(document.getElementById('userBarChart'), { type:'bar', data:{ labels:top10.map(u=>u.name.split(' ')[0]), datasets:[ {label:'Created',data:top10.map(u=>u.created),backgroundColor:'rgba(91,110,245,0.6)',borderColor:BLUE,borderWidth:1,borderRadius:4}, {label:'Closed',data:top10.map(u=>u.closed),backgroundColor:'rgba(56,232,197,0.6)',borderColor:GREEN,borderWidth:1,borderRadius:4} ] }, options:{ responsive:true, maintainAspectRatio:false, indexAxis:top10.length>6?'y':'x', plugins:{legend:{labels:{color:TICK,font:{family:'DM Mono',size:10}}}}, scales:baseScales() } });

  // Cumulative
  let cc=0, cx=0;
  const cumData = daily.map(d=>{ cc+=d.created; cx+=d.closed; return{date:d.date,created:cc,closed:cx}; });
  document.getElementById('cumul-badge').textContent = `Final: ${cc} created / ${cx} closed`;
  techCharts.cumul = new Chart(document.getElementById('cumulChart'), { type:'line', data:{ labels:cumData.map(d=>d.date), datasets:[ {label:'Cumulative Created',data:cumData.map(d=>d.created),borderColor:BLUE,backgroundColor:'rgba(91,110,245,0.08)',fill:true,tension:0.35,pointRadius:3,pointBackgroundColor:BLUE}, {label:'Cumulative Closed',data:cumData.map(d=>d.closed),borderColor:GREEN,backgroundColor:'rgba(56,232,197,0.08)',fill:true,tension:0.35,pointRadius:3,pointBackgroundColor:GREEN} ] }, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{labels:{color:TICK,font:{family:'DM Mono',size:10}}}}, scales:baseScales() } });
}

function renderTechLeaderboard(users, sortBy) {
  const sorted = [...users].sort((a,b) => {
    if(sortBy==='closed') return b.closed-a.closed;
    if(sortBy==='created') return b.created-a.created;
    return (b.created+b.closed)-(a.created+a.closed);
  });
  sortedTechs = sorted;
  const maxVal = sorted.length ? (sortBy==='closed'?sorted[0].closed:sortBy==='created'?sorted[0].created:sorted[0].created+sorted[0].closed) : 1;
  const header = `<div class="lb-row" style="border-bottom:1px solid var(--border2);cursor:default;pointer-events:none"><div></div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Technician</div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--blue);text-align:right;text-transform:uppercase;letter-spacing:1px">Created</div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--green);text-align:right;text-transform:uppercase;letter-spacing:1px">Closed</div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--text-dim);text-align:right;text-transform:uppercase;letter-spacing:1px">Net</div></div>`;
  const rows = sorted.map((u,i)=>{
    const net=u.created-u.closed, nc=net>0?'pos':net<0?'neg':'zero', ns=net>0?`+${net}`:`${net}`;
    const val=sortBy==='closed'?u.closed:sortBy==='created'?u.created:u.created+u.closed;
    const pct=maxVal>0?(val/maxVal*100):0;
    const ri=i===0?'🥇':i===1?'🥈':i===2?'🥉':`${i+1}`;
    const rc=i===0?'gold':i===1?'silver':i===2?'bronze':'';
    return `<div class="lb-row" style="cursor:pointer" onclick="openTechModal(${i})">
      <div class="lb-rank ${rc}">${ri}</div>
      <div><div class="lb-name">${u.name}</div><div class="lb-bar-wrap"><div class="lb-bar" style="width:${pct}%"></div></div></div>
      <div class="lb-val created">${u.created}</div>
      <div class="lb-val closed">${u.closed}</div>
      <div class="lb-val net ${nc}">${ns}</div>
    </div>`;
  }).join('');
  document.getElementById('lb-body').innerHTML = header + (rows || '<div class="loading-state" style="padding:20px">No data</div>');
}

function openTechModal(idx) {
  const u = sortedTechs[idx];
  if (!u) return;
  const net = u.created-u.closed, rate = u.created>0?Math.round((u.closed/u.created)*100):0;
  const nc = net>0?RED:net<0?GREEN:'#6b7280', ns = net>0?`+${net}`:`${net}`;
  document.getElementById('tech-modal-name').textContent = u.name;
  document.getElementById('tech-modal-sub').textContent = `${u.created+u.closed} total actions · ${u.boards.length} board${u.boards.length!==1?'s':''}`;
  const bRows = u.boards.map(b=>{
    const br=b.created>0?Math.round((b.closed/b.created)*100):0;
    return `<div class="progress-row"><div class="progress-label"><span>${b.name}</span><span style="font-family:var(--font-mono);font-size:.7rem;color:var(--text-dim)">${b.created}↑ ${b.closed}↓</span></div><div class="progress-track"><div class="progress-fill" style="width:${Math.max(4,br)}%;background:var(--accent2)"></div></div></div>`;
  }).join('');
  document.getElementById('tech-modal-body').innerHTML = `
    <div class="modal-kpis">
      <div class="modal-kpi"><div class="modal-kpi-val" style="color:var(--blue)">${u.created}</div><div class="modal-kpi-lbl">Created</div></div>
      <div class="modal-kpi"><div class="modal-kpi-val" style="color:var(--green)">${u.closed}</div><div class="modal-kpi-lbl">Closed</div></div>
      <div class="modal-kpi"><div class="modal-kpi-val" style="color:${nc}">${ns}</div><div class="modal-kpi-lbl">Net</div></div>
      <div class="modal-kpi"><div class="modal-kpi-val" style="color:var(--accent2)">${rate}%</div><div class="modal-kpi-lbl">Close Rate</div></div>
    </div>
    ${u.boards.length?`<div class="modal-section-title">Board Breakdown — Close Rate</div>${bRows}`:'<p style="color:var(--text-dim);font-size:.8rem">No board breakdown available.</p>'}`;
  document.getElementById('tech-modal').classList.add('open');
}

// ────────────────────────────────────
//  CUSTOMER PAGE
// ────────────────────────────────────
async function loadCustomers() {
  document.getElementById('status-text').textContent = 'Loading…';
  try {
    const res = await fetch(`/api/customer-stats?days=${currentDays}`);
    const data = await res.json();
    if (data.error) { document.getElementById('status-text').textContent = 'Error'; return; }
    customerData = data;
    renderCustomers(data);
    const now = new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    document.getElementById('status-text').textContent = `Updated ${now}`;
  } catch(e) { document.getElementById('status-text').textContent = 'Failed'; }
}

function renderCustomers(data) {
  destroyCharts(customerCharts); customerCharts = {};
  const { companies, totals, daily } = data;
  allCompanies = companies;

  const totalNet = totals.created - totals.closed;
  const avgRate = totals.created > 0 ? ((totals.closed/totals.created)*100).toFixed(1) : 0;
  const busiest = [...companies].sort((a,b)=>(b.created+b.closed)-(a.created+a.closed))[0];

  // KPIs
  document.getElementById('ckpi-companies').textContent = companies.length;
  document.getElementById('ckpi-companies-sub').textContent = `In last ${currentDays} days`;
  document.getElementById('ckpi-created').textContent = totals.created;
  document.getElementById('ckpi-created-sub').textContent = `${currentDays>0?(totals.created/currentDays).toFixed(1):0}/day avg`;
  document.getElementById('ckpi-closed').textContent = totals.closed;
  document.getElementById('ckpi-closed-sub').textContent = `${currentDays>0?(totals.closed/currentDays).toFixed(1):0}/day avg`;
  document.getElementById('ckpi-rate').textContent = `${avgRate}%`;
  document.getElementById('ckpi-rate').style.color = parseFloat(avgRate)>=100?GREEN:parseFloat(avgRate)>=70?AMBER:RED;
  document.getElementById('ckpi-rate-sub').textContent = 'Across all companies';
  document.getElementById('ckpi-busiest').textContent = busiest ? busiest.name.split(' ')[0] : '—';
  document.getElementById('ckpi-busiest-sub').textContent = busiest ? `${busiest.created+busiest.closed} tickets` : '';
  document.getElementById('ckpi-unresolved').textContent = totalNet >= 0 ? `+${totalNet}` : `${totalNet}`;
  document.getElementById('ckpi-unresolved').style.color = totalNet > 0 ? RED : totalNet < 0 ? GREEN : '#6b7280';
  document.getElementById('ckpi-unresolved-sub').textContent = totalNet > 0 ? 'More opened than closed' : 'On top of queue';
  const totalOpen = totals.open || 0;
  document.getElementById('ckpi-open').textContent = totalOpen;
  document.getElementById('ckpi-open').style.color = totalOpen > 50 ? RED : totalOpen > 20 ? AMBER : GREEN;
  document.getElementById('ckpi-open-sub').textContent = 'Live unresolved tickets';
  document.querySelectorAll('#page-customers .kpi').forEach(k=>k.classList.remove('loading'));

  // Top companies bar chart
  const top12 = [...companies].sort((a,b)=>(b.created+b.closed)-(a.created+a.closed)).slice(0,12);
  customerCharts.companyBar = new Chart(document.getElementById('companyBarChart'), {
    type:'bar',
    data:{ labels:top12.map(c=>c.name.length>18?c.name.slice(0,16)+'…':c.name), datasets:[
      {label:'Created',data:top12.map(c=>c.created),backgroundColor:'rgba(91,110,245,0.6)',borderColor:BLUE,borderWidth:1,borderRadius:3},
      {label:'Closed',data:top12.map(c=>c.closed),backgroundColor:'rgba(56,232,197,0.6)',borderColor:GREEN,borderWidth:1,borderRadius:3}
    ]},
    options:{ responsive:true, maintainAspectRatio:false, indexAxis:top12.length>6?'y':'x', plugins:{legend:{labels:{color:TICK,font:{family:'DM Mono',size:10}}}}, scales:baseScales() }
  });

  // Company donut
  const top8 = top12.slice(0,8);
  const others = companies.slice(8).reduce((s,c)=>s+c.created+c.closed,0);
  const donutLabels = top8.map(c=>c.name.length>20?c.name.slice(0,18)+'…':c.name);
  const donutData = top8.map(c=>c.created+c.closed);
  if (others > 0) { donutLabels.push('Others'); donutData.push(others); }
  customerCharts.companyDonut = new Chart(document.getElementById('companyDonut'), {
    type:'doughnut',
    data:{ labels:donutLabels, datasets:[{data:donutData, backgroundColor:[...CHART_COLORS,'#555'], borderColor:'#0d0f1c', borderWidth:2, hoverOffset:6}] },
    options:{ responsive:true, maintainAspectRatio:false, cutout:'60%', plugins:{legend:{position:'right',labels:{color:TICK,font:{family:'DM Mono',size:9},boxWidth:10,padding:6}}} }
  });

  // Close rate chart
  const top10cr = [...companies].filter(c=>c.created>0).sort((a,b)=>(b.closed/b.created)-(a.closed/a.created)).slice(0,10);
  const crData = top10cr.map(c=>Math.round((c.closed/c.created)*100));
  customerCharts.closeRate = new Chart(document.getElementById('closeRateChart'), {
    type:'bar',
    data:{ labels:top10cr.map(c=>c.name.length>15?c.name.slice(0,13)+'…':c.name), datasets:[{
      label:'Close Rate %', data:crData,
      backgroundColor: crData.map(v=>v>=100?'rgba(56,232,197,0.6)':v>=70?'rgba(245,197,66,0.6)':'rgba(245,91,91,0.6)'),
      borderColor: crData.map(v=>v>=100?GREEN:v>=70?AMBER:RED),
      borderWidth:1, borderRadius:4
    }]},
    options:{ responsive:true, maintainAspectRatio:false, indexAxis:'y',
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label:ctx=>` ${ctx.raw}%`}} },
      scales:{ x:{...baseScales().x, max:Math.max(100,...crData)+5, ticks:{...baseScales().x.ticks,callback:v=>`${v}%`}}, y:baseScales().y }
    }
  });

  // Open tickets charts
  const topByOpen = [...companies].filter(c=>(c.open||0)>0).sort((a,b)=>(b.open||0)-(a.open||0)).slice(0,15);
  document.getElementById('open-count-badge').textContent = `${totals.open||0} total open`;
  if (topByOpen.length) {
    customerCharts.openTickets = new Chart(document.getElementById('openTicketsChart'), {
      type: 'bar',
      data: {
        labels: topByOpen.map(c=>c.name.length>18?c.name.slice(0,16)+'…':c.name),
        datasets: [{
          label: 'Open Tickets',
          data: topByOpen.map(c=>c.open||0),
          backgroundColor: topByOpen.map(c=>(c.open||0)>10?'rgba(245,91,91,0.65)':(c.open||0)>3?'rgba(245,197,66,0.65)':'rgba(56,232,197,0.65)'),
          borderColor: topByOpen.map(c=>(c.open||0)>10?RED:(c.open||0)>3?AMBER:GREEN),
          borderWidth: 1, borderRadius: 4
        }]
      },
      options: { responsive:true, maintainAspectRatio:false, indexAxis:'y',
        plugins:{ legend:{display:false}, tooltip:{callbacks:{label:ctx=>` ${ctx.raw} open`}} },
        scales: baseScales()
      }
    });

    const top10ov = [...companies].sort((a,b)=>(b.created+b.closed)-(a.created+a.closed)).slice(0,10);
    customerCharts.openVsClosed = new Chart(document.getElementById('openVsClosedChart'), {
      type: 'bar',
      data: {
        labels: top10ov.map(c=>c.name.length>14?c.name.slice(0,12)+'…':c.name),
        datasets: [
          { label: 'Open Now', data: top10ov.map(c=>c.open||0), backgroundColor: 'rgba(245,91,91,0.6)', borderColor: RED, borderWidth:1, borderRadius:3 },
          { label: 'Closed (period)', data: top10ov.map(c=>c.closed), backgroundColor: 'rgba(56,232,197,0.6)', borderColor: GREEN, borderWidth:1, borderRadius:3 }
        ]
      },
      options: { responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{labels:{color:TICK,font:{family:'DM Mono',size:10}}} },
        scales: baseScales()
      }
    });
  }

  // Company leaderboard
  renderCompanyLeaderboard(companies, 'total');

  // Company table
  renderCompanyTable(companies);

  // Company directory badge
  document.getElementById('company-dir-badge').textContent = `${companies.length} companies`;

  // Trend by top 5 companies
  const top5 = [...companies].sort((a,b)=>(b.created+b.closed)-(a.created+a.closed)).slice(0,5);
  document.getElementById('company-trend-badge').textContent = `Top ${top5.length} companies`;
  customerCharts.companyTrend = new Chart(document.getElementById('companyTrendChart'), {
    type:'line',
    data:{
      labels: daily.map(d=>d.date),
      datasets: top5.map((c,i)=>({
        label: c.name.length>20?c.name.slice(0,18)+'…':c.name,
        data: daily.map(d=>(d.byCompany&&d.byCompany[c.name])||0),
        borderColor: CHART_COLORS[i],
        backgroundColor: CHART_COLORS[i]+'22',
        fill: false, tension:0.35, pointRadius:3, pointBackgroundColor:CHART_COLORS[i]
      }))
    },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{labels:{color:TICK,font:{family:'DM Mono',size:10}}}}, scales:baseScales() }
  });
}

function renderCompanyLeaderboard(companies, sortBy) {
  const sorted = [...companies].sort((a,b)=>{
    if(sortBy==='created') return b.created-a.created;
    if(sortBy==='closed') return b.closed-a.closed;
    if(sortBy==='net') return (b.created-b.closed)-(a.created-a.closed);
    if(sortBy==='open') return (b.open||0)-(a.open||0);
    return (b.created+b.closed)-(a.created+a.closed);
  });
  sortedCompanies = sorted;
  const maxVal = sorted.length?(sortBy==='created'?sorted[0].created:sortBy==='closed'?sorted[0].closed:sorted[0].created+sorted[0].closed):1;
  const header = `<div class="lb-row" style="border-bottom:1px solid var(--border2);cursor:default;pointer-events:none;grid-template-columns:28px 1fr 60px 60px 60px 60px"><div></div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Company</div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--red);text-align:right;text-transform:uppercase;letter-spacing:1px">Open</div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--blue);text-align:right;text-transform:uppercase;letter-spacing:1px">Created</div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--green);text-align:right;text-transform:uppercase;letter-spacing:1px">Closed</div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--text-dim);text-align:right;text-transform:uppercase;letter-spacing:1px">Net</div></div>`;
  const rows = sorted.slice(0,20).map((c,i)=>{
    const net=c.created-c.closed, nc=net>0?'pos':net<0?'neg':'zero', ns=net>0?`+${net}`:`${net}`;
    const val=sortBy==='created'?c.created:sortBy==='closed'?c.closed:c.created+c.closed;
    const pct=maxVal>0?(val/maxVal*100):0;
    const ri=i===0?'🥇':i===1?'🥈':i===2?'🥉':`${i+1}`;
    const rc=i===0?'gold':i===1?'silver':i===2?'bronze':'';
    const oc=c.open||0, ocColor=oc>10?RED:oc>3?AMBER:GREEN;
    return `<div class="lb-row" style="cursor:pointer;grid-template-columns:28px 1fr 60px 60px 60px 60px" onclick="openCompanyModal(${i})">
      <div class="lb-rank ${rc}">${ri}</div>
      <div><div class="lb-name">${c.name}</div><div class="lb-bar-wrap"><div class="lb-bar" style="width:${pct}%"></div></div></div>
      <div class="lb-val" style="color:${ocColor};text-align:right;font-family:var(--font-mono);font-size:.75rem">${oc}</div>
      <div class="lb-val created">${c.created}</div>
      <div class="lb-val closed">${c.closed}</div>
      <div class="lb-val net ${nc}">${ns}</div>
    </div>`;
  }).join('');
  document.getElementById('clb-body').innerHTML = header + (rows || '<div class="loading-state" style="padding:20px">No data</div>');
}

function renderCompanyTable(companies) {
  const sorted = [...companies].sort((a,b)=>(b.open||0)-(a.open||0)||(b.created+b.closed)-(a.created+a.closed));
  const rows = sorted.map((c,i)=>{
    const net=c.created-c.closed;
    const nb=net>0?`<span class="badge-n-pos">+${net}</span>`:net<0?`<span class="badge-n-neg">${net}</span>`:`<span class="badge-n-zero">0</span>`;
    const rate=c.created>0?Math.round((c.closed/c.created)*100):0;
    const rateColor=rate>=100?GREEN:rate>=70?AMBER:RED;
    const openCount=c.open||0;
    const openColor=openCount>10?RED:openCount>3?AMBER:GREEN;
    return `<tr style="cursor:pointer" onclick="openCompanyModalByName('${c.name.replace(/'/g,"\'")}')">
      <td><span style="font-weight:500">${c.name}</span></td>
      <td class="r"><span style="font-family:var(--font-mono);font-size:.78rem;font-weight:700;color:${openColor}">${openCount}</span></td>
      <td class="r"><span class="badge-c">${c.created}</span></td>
      <td class="r"><span class="badge-x">${c.closed}</span></td>
      <td class="r">${nb}</td>
      <td class="r"><span style="font-family:var(--font-mono);font-size:.72rem;color:${rateColor}">${rate}%</span></td>
      <td class="r"><span style="font-family:var(--font-mono);font-size:.72rem;color:var(--text-dim)">${c.contacts||0}</span></td>
    </tr>`;
  }).join('');
  document.getElementById('company-tbody').innerHTML = rows || '<tr><td colspan="7" style="color:var(--text-dim);text-align:center;padding:20px">No companies found</td></tr>';
}

function openCompanyModal(idx) {
  const c = sortedCompanies[idx];
  if (!c) return;
  showCompanyModal(c);
}
function openCompanyModalByName(name) {
  const c = allCompanies.find(x=>x.name===name);
  if (c) showCompanyModal(c);
}

function showCompanyModal(c) {
  const net=c.created-c.closed, rate=c.created>0?Math.round((c.closed/c.created)*100):0;
  const nc=net>0?RED:net<0?GREEN:'#6b7280', ns=net>0?`+${net}`:`${net}`;
  const openCount=c.open||0;
  const openColor=openCount>10?RED:openCount>3?AMBER:GREEN;
  document.getElementById('company-modal-name').textContent = c.name;
  document.getElementById('company-modal-sub').textContent = `${openCount} open now · ${c.created+c.closed} activity in period · ${c.contacts||0} contact${(c.contacts||0)!==1?'s':''} active`;

  const techRows = (c.technicians||[]).map(t=>{
    const tr=t.created>0?Math.round((t.closed/t.created)*100):0;
    return `<div class="progress-row"><div class="progress-label"><span>${t.name}</span><span style="font-family:var(--font-mono);font-size:.7rem;color:var(--text-dim)">${t.created}↑ ${t.closed}↓</span></div><div class="progress-track"><div class="progress-fill" style="width:${Math.max(4,tr)}%;background:var(--purple)"></div></div></div>`;
  }).join('');

  const boardRows = (c.boards||[]).map(b=>{
    const br=b.created>0?Math.round((b.closed/b.created)*100):0;
    return `<div class="progress-row"><div class="progress-label"><span>${b.name}</span><span style="font-family:var(--font-mono);font-size:.7rem;color:var(--text-dim)">${b.created}↑ ${b.closed}↓</span></div><div class="progress-track"><div class="progress-fill" style="width:${Math.max(4,br)}%;background:var(--accent2)"></div></div></div>`;
  }).join('');

  document.getElementById('company-modal-body').innerHTML = `
    <div class="modal-kpis" style="grid-template-columns:repeat(5,1fr)">
      <div class="modal-kpi" style="border-top:2px solid ${openColor}"><div class="modal-kpi-val" style="color:${openColor}">${openCount}</div><div class="modal-kpi-lbl">Open Now</div></div>
      <div class="modal-kpi"><div class="modal-kpi-val" style="color:var(--blue)">${c.created}</div><div class="modal-kpi-lbl">Created</div></div>
      <div class="modal-kpi"><div class="modal-kpi-val" style="color:var(--green)">${c.closed}</div><div class="modal-kpi-lbl">Closed</div></div>
      <div class="modal-kpi"><div class="modal-kpi-val" style="color:${nc}">${ns}</div><div class="modal-kpi-lbl">Net</div></div>
      <div class="modal-kpi"><div class="modal-kpi-val" style="color:var(--accent2)">${rate}%</div><div class="modal-kpi-lbl">Close Rate</div></div>
    </div>
    ${openCount>0?`<div style="background:rgba(245,91,91,0.06);border:1px solid rgba(245,91,91,0.15);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-family:var(--font-mono);font-size:.72rem;color:var(--red)">🚨 ${openCount} ticket${openCount!==1?'s':''} currently open and unresolved</div>`:''}
    ${(c.technicians||[]).length?`<div class="modal-section-title">Assigned Technicians</div>${techRows}`:''}
    ${(c.boards||[]).length?`<div class="modal-section-title">Boards Active</div>${boardRows}`:''}
  `;
  document.getElementById('company-modal').classList.add('open');
}

// ── CONFIG CHECK ──
async function checkConfig() {
  try {
    const data = await fetch('/api/config-check').then(r=>r.json());
    if (!data.configured) document.getElementById('config-banner').classList.add('show');
  } catch(e) {}
}

// ── AUTO REFRESH ──
function startAutoRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(()=>{ loadTechs(); if(currentPage==='customers') loadCustomers(); }, REFRESH_INTERVAL*1000);
}

checkConfig();
loadTechs();
startAutoRefresh();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML, refresh_interval=REFRESH_INTERVAL, days_back=DAYS_BACK)


# ─────────────────────────────────────────────────────────────
#  /api/ticket-stats  (technician page)
# ─────────────────────────────────────────────────────────────
@app.route("/api/ticket-stats")
def ticket_stats():
    try:
        days = int(request.args.get("days", DAYS_BACK))
        now  = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        created_tickets = cw_get("/service/tickets", {
            "conditions": f"dateEntered >= [{since_str}] and parentTicketId = null",
            "fields": "id,summary,owner,board,dateEntered",
            "orderBy": "dateEntered asc"
        })

        closed_tickets = cw_get("/service/tickets", {
            "conditions": f"closedFlag = true and lastUpdated >= [{since_str}] and parentTicketId = null",
            "fields": "id,summary,owner,board,lastUpdated,closedDate",
            "orderBy": "lastUpdated asc"
        })

        # Daily buckets
        daily_buckets = {}
        for i in range(days):
            day = (since + timedelta(days=i)).strftime("%d %b")
            daily_buckets[day] = {"date": day, "created": 0, "closed": 0}

        def day_key(iso):
            try:
                return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b")
            except:
                return None

        for t in created_tickets:
            k = day_key(t.get("dateEntered", ""))
            if k and k in daily_buckets:
                daily_buckets[k]["created"] += 1

        for t in closed_tickets:
            ts = t.get("closedDate") or t.get("lastUpdated", "")
            k = day_key(ts)
            if k and k in daily_buckets:
                daily_buckets[k]["closed"] += 1

        def get_owner(t):
            o = t.get("owner")
            if isinstance(o, dict):
                return o.get("name", "Unassigned")
            return o or "Unassigned"

        def get_board(t):
            b = t.get("board")
            if isinstance(b, dict):
                return b.get("name", "")
            return b or ""

        user_created = defaultdict(list)
        user_closed  = defaultdict(list)
        for t in created_tickets:
            user_created[get_owner(t)].append(get_board(t))
        for t in closed_tickets:
            user_closed[get_owner(t)].append(get_board(t))

        all_users = set(user_created.keys()) | set(user_closed.keys())
        users_result = []
        for name in sorted(all_users):
            cb = user_created[name]; xb = user_closed[name]
            bn = set(cb) | set(xb)
            boards = [{"name": b, "created": cb.count(b), "closed": xb.count(b)} for b in sorted(bn) if b]
            boards.sort(key=lambda x: x["created"]+x["closed"], reverse=True)
            users_result.append({"name": name, "created": len(cb), "closed": len(xb), "boards": boards})
        users_result.sort(key=lambda u: u["created"]+u["closed"], reverse=True)

        board_created = defaultdict(int)
        board_closed  = defaultdict(int)
        for t in created_tickets:
            bn = get_board(t)
            if bn: board_created[bn] += 1
        for t in closed_tickets:
            bn = get_board(t)
            if bn: board_closed[bn] += 1

        all_board_names = set(board_created.keys()) | set(board_closed.keys())
        boards_result = [{"name": bn, "created": board_created[bn], "closed": board_closed[bn]} for bn in all_board_names]
        boards_result.sort(key=lambda b: b["created"]+b["closed"], reverse=True)

        return jsonify({
            "totals": {"created": len(created_tickets), "closed": len(closed_tickets)},
            "users": users_result,
            "daily": list(daily_buckets.values()),
            "boards": boards_result,
            "asOf": now.isoformat(),
            "daysBack": days
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
#  /api/customer-stats  (company/customer page)
# ─────────────────────────────────────────────────────────────
@app.route("/api/customer-stats")
def customer_stats():
    try:
        days = int(request.args.get("days", DAYS_BACK))
        now  = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Fetch created — include company and contact
        created_tickets = cw_get("/service/tickets", {
            "conditions": f"dateEntered >= [{since_str}] and parentTicketId = null",
            "fields": "id,company,contact,owner,board,dateEntered",
            "orderBy": "dateEntered asc"
        })

        # Fetch closed — include company and contact
        closed_tickets = cw_get("/service/tickets", {
            "conditions": f"closedFlag = true and lastUpdated >= [{since_str}] and parentTicketId = null",
            "fields": "id,company,contact,owner,board,lastUpdated,closedDate",
            "orderBy": "lastUpdated asc"
        })

        # Fetch ALL currently open tickets — total live queue, no date filter
        open_tickets = cw_get("/service/tickets", {
            "conditions": "closedFlag = false and parentTicketId = null",
            "fields": "id,company,owner,board,priority,dateEntered",
        })

        def get_company(t):
            c = t.get("company")
            if isinstance(c, dict):
                return c.get("name", "Unknown")
            return c or "Unknown"

        def get_owner(t):
            o = t.get("owner")
            if isinstance(o, dict):
                return o.get("name", "Unassigned")
            return o or "Unassigned"

        def get_board(t):
            b = t.get("board")
            if isinstance(b, dict):
                return b.get("name", "")
            return b or ""

        def get_contact(t):
            c = t.get("contact")
            if isinstance(c, dict):
                return c.get("name", "")
            return c or ""

        def day_key(iso):
            try:
                return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b")
            except:
                return None

        # Daily buckets with per-company breakdown
        daily_buckets = {}
        for i in range(days):
            day = (since + timedelta(days=i)).strftime("%d %b")
            daily_buckets[day] = {"date": day, "created": 0, "closed": 0, "byCompany": {}}

        for t in created_tickets:
            k = day_key(t.get("dateEntered", ""))
            co = get_company(t)
            if k and k in daily_buckets:
                daily_buckets[k]["created"] += 1
                daily_buckets[k]["byCompany"][co] = daily_buckets[k]["byCompany"].get(co, 0) + 1

        for t in closed_tickets:
            ts = t.get("closedDate") or t.get("lastUpdated", "")
            k = day_key(ts)
            if k and k in daily_buckets:
                daily_buckets[k]["closed"] += 1

        # Per-company aggregation
        co_created   = defaultdict(int)
        co_closed    = defaultdict(int)
        co_contacts  = defaultdict(set)
        co_techs_c   = defaultdict(lambda: defaultdict(int))  # company -> tech -> count
        co_techs_x   = defaultdict(lambda: defaultdict(int))
        co_boards_c  = defaultdict(lambda: defaultdict(int))
        co_boards_x  = defaultdict(lambda: defaultdict(int))

        for t in created_tickets:
            co = get_company(t)
            co_created[co] += 1
            ct = get_contact(t)
            if ct: co_contacts[co].add(ct)
            co_techs_c[co][get_owner(t)] += 1
            bn = get_board(t)
            if bn: co_boards_c[co][bn] += 1

        for t in closed_tickets:
            co = get_company(t)
            co_closed[co] += 1
            ct = get_contact(t)
            if ct: co_contacts[co].add(ct)
            co_techs_x[co][get_owner(t)] += 1
            bn = get_board(t)
            if bn: co_boards_x[co][bn] += 1

        # Per-company open ticket counts (live queue)
        co_open = defaultdict(int)
        co_open_boards = defaultdict(lambda: defaultdict(int))
        for t in open_tickets:
            co = get_company(t)
            co_open[co] += 1
            bn = get_board(t)
            if bn: co_open_boards[co][bn] += 1

        all_cos = set(co_created.keys()) | set(co_closed.keys()) | set(co_open.keys())
        companies_result = []
        for co in all_cos:
            # Technician breakdown for this company
            all_techs = set(co_techs_c[co].keys()) | set(co_techs_x[co].keys())
            techs = [{"name": t, "created": co_techs_c[co].get(t,0), "closed": co_techs_x[co].get(t,0)} for t in all_techs]
            techs.sort(key=lambda x: x["created"]+x["closed"], reverse=True)

            # Board breakdown for this company
            all_boards = set(co_boards_c[co].keys()) | set(co_boards_x[co].keys())
            boards = [{"name": b, "created": co_boards_c[co].get(b,0), "closed": co_boards_x[co].get(b,0)} for b in all_boards]
            boards.sort(key=lambda x: x["created"]+x["closed"], reverse=True)

            companies_result.append({
                "name": co,
                "created": co_created[co],
                "closed": co_closed[co],
                "open": co_open.get(co, 0),
                "contacts": len(co_contacts[co]),
                "technicians": techs,
                "boards": boards
            })

        companies_result.sort(key=lambda c: c["created"]+c["closed"], reverse=True)

        total_open = len(open_tickets)

        return jsonify({
            "totals": {
                "created": len(created_tickets),
                "closed": len(closed_tickets),
                "open": total_open
            },
            "companies": companies_result,
            "daily": list(daily_buckets.values()),
            "asOf": now.isoformat(),
            "daysBack": days
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config-check")
def config_check():
    configured = all([CW_COMPANY, CW_PUBLIC_KEY, CW_PRIVATE_KEY, CW_CLIENT_ID])
    return jsonify({
        "configured": configured,
        "site": CW_SITE,
        "company": CW_COMPANY if CW_COMPANY else "(not set)",
        "hasPublicKey": bool(CW_PUBLIC_KEY),
        "hasPrivateKey": bool(CW_PRIVATE_KEY),
        "hasClientId": bool(CW_CLIENT_ID),
        "proxy": HTTPS_PROXY if HTTPS_PROXY else "none",
        "sslVerify": VERIFY_SSL
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
