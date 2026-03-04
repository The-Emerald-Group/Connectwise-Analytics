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


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CW Pulse — Ticket Analytics</title>
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
  --text:     #e8eaf6;
  --text-dim: #6b7280;
  --text-mid: #9ca3af;
  --font-display: 'Syne', sans-serif;
  --font-body: 'DM Sans', sans-serif;
  --font-mono: 'DM Mono', monospace;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  font-size: 14px;
  min-height: 100vh;
  overflow-x: hidden;
}

/* Noise texture overlay */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.03'/%3E%3C/svg%3E");
  pointer-events: none;
  z-index: 0;
  opacity: 0.4;
}

/* ─── HEADER ─── */
header {
  position: sticky; top: 0; z-index: 200;
  background: rgba(7,8,16,0.85);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
  height: 56px;
  display: flex; align-items: center; justify-content: space-between;
}
.logo {
  font-family: var(--font-display);
  font-size: 1.1rem; font-weight: 800;
  letter-spacing: -0.5px;
  color: var(--text);
}
.logo .dot { color: var(--accent2); }
.logo .sub { font-family: var(--font-mono); font-size: 0.65rem; font-weight: 400; color: var(--text-dim); margin-left: 10px; letter-spacing: 2px; text-transform: uppercase; vertical-align: middle; }

.header-controls { display: flex; align-items: center; gap: 12px; }

.days-selector { display: flex; align-items: center; gap: 0; background: var(--panel); border: 1px solid var(--border2); border-radius: 8px; overflow: hidden; }
.days-btn {
  font-family: var(--font-mono); font-size: 0.7rem; font-weight: 500;
  padding: 6px 12px; cursor: pointer; border: none; background: transparent;
  color: var(--text-dim); transition: all .15s; letter-spacing: 0.5px;
}
.days-btn.active { background: var(--accent); color: white; }
.days-btn:hover:not(.active) { color: var(--text); background: var(--raised); }

.status-pill {
  display: flex; align-items: center; gap: 7px;
  padding: 5px 12px; border-radius: 20px;
  background: var(--panel); border: 1px solid var(--border2);
  font-family: var(--font-mono); font-size: 0.68rem; color: var(--text-dim);
  letter-spacing: 0.5px;
}
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent2); animation: livepulse 2s infinite; }
@keyframes livepulse { 0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(56,232,197,0.4)} 50%{opacity:0.7;box-shadow:0 0 0 5px rgba(56,232,197,0)} }

/* ─── LAYOUT ─── */
.app-body { position: relative; z-index: 1; padding: 28px 32px 60px; max-width: 1600px; margin: 0 auto; }

/* ─── CONFIG WARNING ─── */
.config-banner {
  display: none; align-items: center; gap: 14px;
  background: rgba(245,91,91,0.07); border: 1px solid rgba(245,91,91,0.2);
  border-radius: 10px; padding: 14px 18px; margin-bottom: 24px;
}
.config-banner.show { display: flex; }
.config-banner-icon { font-size: 1.2rem; }
.config-banner h4 { color: var(--red); font-size: .82rem; margin-bottom: 3px; }
.config-banner p { font-size: .75rem; color: var(--text-dim); }
.config-banner code { background: rgba(255,255,255,.06); padding: 1px 5px; border-radius: 3px; color: var(--amber); font-family: var(--font-mono); }

/* ─── SECTION ─── */
.section { margin-bottom: 36px; }
.section-label {
  font-family: var(--font-mono); font-size: 0.62rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: 3px; color: var(--text-dim);
  margin-bottom: 14px; display: flex; align-items: center; gap: 10px;
}
.section-label::after { content: ''; flex: 1; height: 1px; background: var(--border); }

/* ─── KPI CARDS ─── */
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
.kpi {
  background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px 22px; position: relative; overflow: hidden; cursor: default;
  transition: border-color .2s, transform .2s;
}
.kpi:hover { border-color: var(--border2); transform: translateY(-1px); }
.kpi::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: var(--kpi-color, var(--accent));
}
.kpi-icon { font-size: 1.4rem; margin-bottom: 10px; opacity: 0.8; }
.kpi-num {
  font-family: var(--font-display); font-size: 2.4rem; font-weight: 800;
  line-height: 1; color: var(--kpi-color, var(--text));
  transition: opacity .3s;
}
.kpi-label-text { font-size: .7rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1.5px; margin-top: 6px; }
.kpi-sub-text { font-family: var(--font-mono); font-size: .65rem; color: var(--text-dim); margin-top: 3px; }
.kpi-sparkline { margin-top: 10px; height: 28px; }
.kpi.loading .kpi-num { opacity: 0.2; }

/* ─── TWO-COL ─── */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.three-col { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 14px; }
@media (max-width: 1100px) { .three-col { grid-template-columns: 1fr; } .two-col { grid-template-columns: 1fr; } }

/* ─── CHART PANEL ─── */
.chart-panel {
  background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
  padding: 22px 24px;
}
.chart-panel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.chart-panel-title { font-family: var(--font-display); font-size: .88rem; font-weight: 700; }
.chart-panel-badge {
  font-family: var(--font-mono); font-size: .62rem; padding: 3px 9px;
  border-radius: 20px; background: var(--raised); color: var(--text-dim);
  border: 1px solid var(--border);
}
.chart-wrap { position: relative; }
.chart-wrap canvas { max-height: 240px; }
.chart-wrap.tall canvas { max-height: 300px; }

/* ─── LEADERBOARD ─── */
.leaderboard { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.lb-header {
  padding: 16px 20px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.lb-title { font-family: var(--font-display); font-size: .88rem; font-weight: 700; }
.lb-tabs { display: flex; gap: 0; }
.lb-tab {
  font-family: var(--font-mono); font-size: .65rem; padding: 4px 10px;
  border-radius: 6px; cursor: pointer; color: var(--text-dim);
  transition: all .15s; border: none; background: transparent;
}
.lb-tab.active { background: var(--accent); color: white; }
.lb-tab:hover:not(.active) { color: var(--text); }
.lb-row {
  display: grid; grid-template-columns: 28px 1fr 70px 70px 70px;
  align-items: center; gap: 12px;
  padding: 11px 20px; border-bottom: 1px solid var(--border);
  transition: background .15s;
}
.lb-row:last-child { border-bottom: none; }
.lb-row:hover { background: var(--raised); }
.lb-rank { font-family: var(--font-mono); font-size: .72rem; color: var(--text-dim); text-align: center; }
.lb-rank.gold { color: var(--amber); }
.lb-rank.silver { color: #a0aec0; }
.lb-rank.bronze { color: #cd7f32; }
.lb-name { font-size: .82rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lb-bar-wrap { position: relative; height: 4px; background: var(--raised); border-radius: 2px; margin-top: 3px; }
.lb-bar { height: 4px; border-radius: 2px; background: var(--accent); transition: width .6s ease; }
.lb-val { font-family: var(--font-mono); font-size: .75rem; text-align: right; }
.lb-val.created { color: var(--blue); }
.lb-val.closed { color: var(--green); }
.lb-val.net.pos { color: var(--red); }
.lb-val.net.neg { color: var(--green); }
.lb-val.net.zero { color: var(--text-dim); }

/* ─── BOARD TABLE ─── */
.data-table { width: 100%; border-collapse: collapse; }
.data-table th {
  font-family: var(--font-mono); font-size: .62rem; text-transform: uppercase;
  letter-spacing: 1.5px; color: var(--text-dim); padding: 10px 16px;
  border-bottom: 1px solid var(--border); text-align: left; font-weight: 500;
}
.data-table th.r { text-align: right; }
.data-table td { padding: 10px 16px; border-bottom: 1px solid var(--border); font-size: .8rem; }
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: var(--raised); }
.data-table td.r { text-align: right; font-family: var(--font-mono); }
.badge-c { display: inline-block; background: rgba(91,110,245,0.15); color: var(--blue); border-radius: 4px; padding: 1px 7px; font-family: var(--font-mono); font-size: .7rem; }
.badge-x { display: inline-block; background: rgba(56,232,197,0.15); color: var(--green); border-radius: 4px; padding: 1px 7px; font-family: var(--font-mono); font-size: .7rem; }
.badge-n-pos { display: inline-block; background: rgba(245,91,91,0.12); color: var(--red); border-radius: 4px; padding: 1px 7px; font-family: var(--font-mono); font-size: .7rem; }
.badge-n-neg { display: inline-block; background: rgba(56,232,197,0.12); color: var(--green); border-radius: 4px; padding: 1px 7px; font-family: var(--font-mono); font-size: .7rem; }
.badge-n-zero { display: inline-block; background: rgba(255,255,255,0.05); color: var(--text-dim); border-radius: 4px; padding: 1px 7px; font-family: var(--font-mono); font-size: .7rem; }

/* ─── ACTIVITY HEATMAP ─── */
.heatmap-grid { display: flex; flex-direction: column; gap: 4px; }
.heatmap-days { display: grid; gap: 4px; }
.heatmap-cell {
  width: 28px; height: 28px; border-radius: 4px;
  background: var(--raised); transition: transform .1s;
  cursor: pointer; position: relative;
}
.heatmap-cell:hover { transform: scale(1.2); z-index: 10; }
.heatmap-cell .tip {
  display: none; position: absolute; bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%);
  background: var(--surface); border: 1px solid var(--border2); border-radius: 6px;
  padding: 5px 9px; white-space: nowrap; font-size: .68rem; font-family: var(--font-mono);
  color: var(--text); z-index: 100; pointer-events: none;
}
.heatmap-cell:hover .tip { display: block; }

/* ─── LOADING / SPINNER ─── */
.loading-state { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 50px; color: var(--text-dim); font-size: .8rem; font-family: var(--font-mono); }
.spin { width: 16px; height: 16px; border: 2px solid var(--border); border-top-color: var(--accent2); border-radius: 50%; animation: spin .7s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
.err-state { padding: 20px; color: var(--red); font-family: var(--font-mono); font-size: .78rem; }

/* ─── USER DETAIL MODAL ─── */
.modal-overlay {
  display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7);
  backdrop-filter: blur(8px); z-index: 500; align-items: center; justify-content: center;
}
.modal-overlay.open { display: flex; }
.modal {
  background: var(--surface); border: 1px solid var(--border2); border-radius: 16px;
  width: min(700px, 95vw); max-height: 85vh; overflow-y: auto;
  animation: modalIn .2s ease;
}
@keyframes modalIn { from{opacity:0;transform:scale(.95)} to{opacity:1;transform:scale(1)} }
.modal-header {
  padding: 22px 26px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0;
  background: var(--surface); z-index: 1;
}
.modal-title { font-family: var(--font-display); font-size: 1.1rem; font-weight: 800; }
.modal-close { background: none; border: none; color: var(--text-dim); cursor: pointer; font-size: 1.2rem; padding: 4px; border-radius: 6px; transition: color .15s, background .15s; }
.modal-close:hover { color: var(--text); background: var(--raised); }
.modal-body { padding: 24px 26px; }
.modal-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 22px; }
.modal-stat { background: var(--panel); border-radius: 10px; padding: 16px; text-align: center; }
.modal-stat-val { font-family: var(--font-display); font-size: 1.8rem; font-weight: 800; line-height: 1; }
.modal-stat-lbl { font-size: .65rem; text-transform: uppercase; letter-spacing: 1.5px; color: var(--text-dim); margin-top: 4px; }
.modal-chart-wrap { height: 180px; margin-bottom: 22px; }
.modal-boards-title { font-family: var(--font-mono); font-size: .62rem; text-transform: uppercase; letter-spacing: 2px; color: var(--text-dim); margin-bottom: 10px; }

/* ─── PROGRESS BARS ─── */
.progress-row { margin-bottom: 10px; }
.progress-label { display: flex; justify-content: space-between; font-size: .75rem; margin-bottom: 4px; }
.progress-track { height: 6px; background: var(--raised); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 3px; transition: width .6s ease; }

/* ─── SPARKLINE ─── */
.sparkline-canvas { width: 100%; height: 28px; }

/* TABS */
.view-tabs { display: flex; gap: 0; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; padding: 3px; margin-bottom: 20px; width: fit-content; }
.view-tab { font-family: var(--font-mono); font-size: .68rem; padding: 6px 14px; border-radius: 6px; cursor: pointer; color: var(--text-dim); transition: all .15s; border: none; background: transparent; letter-spacing: 0.5px; }
.view-tab.active { background: var(--accent); color: white; }
.view-tab:hover:not(.active) { color: var(--text); }

/* ─── RESPONSIVE ─── */
@media (max-width: 768px) {
  .app-body { padding: 16px; }
  header { padding: 0 16px; }
  .kpi-row { grid-template-columns: 1fr 1fr; }
}

/* Animations */
.fade-in { animation: fadeIn .3s ease forwards; }
@keyframes fadeIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
</style>
</head>
<body>

<header>
  <div class="logo">CW<span class="dot">·</span>Pulse <span class="sub">Analytics</span></div>
  <div class="header-controls">
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
    <div class="config-banner-icon">⚠</div>
    <div>
      <h4>ConnectWise API not configured</h4>
      <p>Set <code>CW_COMPANY</code>, <code>CW_PUBLIC_KEY</code>, <code>CW_PRIVATE_KEY</code>, <code>CW_CLIENT_ID</code> in your environment.</p>
    </div>
  </div>

  <!-- KPIs -->
  <div class="section">
    <div class="section-label">Overview</div>
    <div class="kpi-row" id="kpi-row">
      <div class="kpi loading" style="--kpi-color: var(--blue)">
        <div class="kpi-icon">📥</div>
        <div class="kpi-num" id="kpi-created">—</div>
        <div class="kpi-label-text">Tickets Created</div>
        <div class="kpi-sub-text" id="kpi-created-sub">…</div>
      </div>
      <div class="kpi loading" style="--kpi-color: var(--green)">
        <div class="kpi-icon">✅</div>
        <div class="kpi-num" id="kpi-closed">—</div>
        <div class="kpi-label-text">Tickets Closed</div>
        <div class="kpi-sub-text" id="kpi-closed-sub">…</div>
      </div>
      <div class="kpi loading" style="--kpi-color: var(--amber)">
        <div class="kpi-icon">📊</div>
        <div class="kpi-num" id="kpi-net">—</div>
        <div class="kpi-label-text">Net Change</div>
        <div class="kpi-sub-text" id="kpi-net-sub">…</div>
      </div>
      <div class="kpi loading" style="--kpi-color: var(--accent2)">
        <div class="kpi-icon">📈</div>
        <div class="kpi-num" id="kpi-rate">—</div>
        <div class="kpi-label-text">Close Rate</div>
        <div class="kpi-sub-text" id="kpi-rate-sub">…</div>
      </div>
      <div class="kpi loading" style="--kpi-color: var(--purple)">
        <div class="kpi-icon">👥</div>
        <div class="kpi-num" id="kpi-users">—</div>
        <div class="kpi-label-text">Active Techs</div>
        <div class="kpi-sub-text" id="kpi-users-sub">…</div>
      </div>
      <div class="kpi loading" style="--kpi-color: var(--amber)">
        <div class="kpi-icon">🗂</div>
        <div class="kpi-num" id="kpi-boards">—</div>
        <div class="kpi-label-text">Active Boards</div>
        <div class="kpi-sub-text" id="kpi-boards-sub">…</div>
      </div>
    </div>
  </div>

  <!-- Trend + Donut -->
  <div class="section">
    <div class="section-label">Trends</div>
    <div class="three-col">
      <div class="chart-panel">
        <div class="chart-panel-header">
          <div class="chart-panel-title">Daily Volume</div>
          <span class="chart-panel-badge" id="trend-badge">—</span>
        </div>
        <div class="chart-wrap tall"><canvas id="trendChart"></canvas></div>
      </div>
      <div class="chart-panel">
        <div class="chart-panel-header">
          <div class="chart-panel-title">By Board</div>
          <span class="chart-panel-badge">Distribution</span>
        </div>
        <div class="chart-wrap" style="display:flex;align-items:center;justify-content:center;height:220px">
          <canvas id="boardDonut" style="max-height:220px;max-width:220px"></canvas>
        </div>
      </div>
      <div class="chart-panel">
        <div class="chart-panel-header">
          <div class="chart-panel-title">Created vs Closed</div>
          <span class="chart-panel-badge">Ratio</span>
        </div>
        <div class="chart-wrap" style="display:flex;align-items:center;justify-content:center;height:220px">
          <canvas id="ratioChart" style="max-height:220px;max-width:220px"></canvas>
        </div>
      </div>
    </div>
  </div>

  <!-- Leaderboard + Board Table -->
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
        <div class="chart-panel-header">
          <div class="chart-panel-title">Board Breakdown</div>
          <span class="chart-panel-badge" id="board-count-badge">—</span>
        </div>
        <div style="overflow-x:auto">
          <table class="data-table" id="board-table">
            <thead><tr>
              <th>Board</th>
              <th class="r">Created</th>
              <th class="r">Closed</th>
              <th class="r">Net</th>
            </tr></thead>
            <tbody id="board-tbody"><tr><td colspan="4"><div class="loading-state"><div class="spin"></div>Loading…</div></td></tr></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- Tech Bar Chart -->
  <div class="section">
    <div class="section-label">Technician Activity</div>
    <div class="chart-panel">
      <div class="chart-panel-header">
        <div class="chart-panel-title">Per-Technician Volume</div>
        <span class="chart-panel-badge">Created vs Closed</span>
      </div>
      <div class="chart-wrap tall"><canvas id="userBarChart"></canvas></div>
    </div>
  </div>

  <!-- Cumulative trend -->
  <div class="section">
    <div class="section-label">Cumulative View</div>
    <div class="chart-panel">
      <div class="chart-panel-header">
        <div class="chart-panel-title">Running Totals Over Period</div>
        <span class="chart-panel-badge" id="cumul-badge">—</span>
      </div>
      <div class="chart-wrap tall"><canvas id="cumulChart"></canvas></div>
    </div>
  </div>

</div>

<!-- User Detail Modal -->
<div class="modal-overlay" id="modal-overlay">
  <div class="modal">
    <div class="modal-header">
      <div class="modal-title" id="modal-user-name">User</div>
      <button class="modal-close" id="modal-close">✕</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<script>
const DEFAULT_DAYS = parseInt('{{ days_back }}') || 7;
const REFRESH_INTERVAL = parseInt('{{ refresh_interval }}') || 300;

let currentDays = DEFAULT_DAYS;
let statsData = null;
let refreshTimer = null;
let charts = {};

// ─── DAYS SELECTOR ───
document.querySelectorAll('.days-btn').forEach(btn => {
  if (parseInt(btn.dataset.days) === DEFAULT_DAYS) btn.classList.add('active');
  btn.addEventListener('click', () => {
    document.querySelectorAll('.days-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentDays = parseInt(btn.dataset.days);
    loadStats();
  });
});

// ─── LEADERBOARD SORT TABS ───
document.querySelectorAll('.lb-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.lb-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    if (statsData) renderLeaderboard(statsData.users, tab.dataset.sort);
  });
});

// ─── MODAL ───
document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('modal-overlay').addEventListener('click', e => {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
});
function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}
function openModal(user) {
  const net = user.created - user.closed;
  const netCls = net > 0 ? 'var(--red)' : net < 0 ? 'var(--green)' : 'var(--text-dim)';
  const netStr = net > 0 ? `+${net}` : `${net}`;
  const rate = user.created > 0 ? Math.round((user.closed / user.created) * 100) : 0;

  const boardRows = user.boards.map(b => {
    const bn = b.created + b.closed;
    const brate = b.created > 0 ? Math.round((b.closed / b.created) * 100) : 0;
    return `
      <div class="progress-row">
        <div class="progress-label">
          <span>${b.name}</span>
          <span style="font-family:var(--font-mono);font-size:.7rem;color:var(--text-dim)">${b.created}↑ ${b.closed}↓</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" style="width:${Math.max(4,brate)}%;background:var(--accent2)"></div>
        </div>
      </div>`;
  }).join('');

  document.getElementById('modal-user-name').textContent = user.name;
  document.getElementById('modal-body').innerHTML = `
    <div class="modal-stats">
      <div class="modal-stat">
        <div class="modal-stat-val" style="color:var(--blue)">${user.created}</div>
        <div class="modal-stat-lbl">Created</div>
      </div>
      <div class="modal-stat">
        <div class="modal-stat-val" style="color:var(--green)">${user.closed}</div>
        <div class="modal-stat-lbl">Closed</div>
      </div>
      <div class="modal-stat">
        <div class="modal-stat-val" style="color:${netCls}">${netStr}</div>
        <div class="modal-stat-lbl">Net</div>
      </div>
    </div>
    <div style="display:flex;gap:16px;margin-bottom:20px">
      <div style="flex:1;background:var(--panel);border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:var(--font-display);font-size:1.4rem;font-weight:800;color:var(--accent2)">${rate}%</div>
        <div style="font-size:.65rem;text-transform:uppercase;letter-spacing:1.5px;color:var(--text-dim);margin-top:3px">Close Rate</div>
      </div>
      <div style="flex:1;background:var(--panel);border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:var(--font-display);font-size:1.4rem;font-weight:800;color:var(--purple)">${user.boards.length}</div>
        <div style="font-size:.65rem;text-transform:uppercase;letter-spacing:1.5px;color:var(--text-dim);margin-top:3px">Boards Active</div>
      </div>
      <div style="flex:1;background:var(--panel);border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:var(--font-display);font-size:1.4rem;font-weight:800;color:var(--amber)">${user.created + user.closed}</div>
        <div style="font-size:.65rem;text-transform:uppercase;letter-spacing:1.5px;color:var(--text-dim);margin-top:3px">Total Activity</div>
      </div>
    </div>
    ${user.boards.length ? `<div class="modal-boards-title">Board Breakdown — Close Rate</div>${boardRows}` : ''}
  `;
  document.getElementById('modal-overlay').classList.add('open');
}

// ─── DESTROY ALL CHARTS ───
function destroyCharts() {
  Object.values(charts).forEach(c => { try { c.destroy(); } catch(e){} });
  charts = {};
}

// ─── CHART.JS DEFAULTS ───
const GRID_COLOR = 'rgba(255,255,255,0.05)';
const TICK_COLOR = '#6b7280';
const BLUE = '#5b6ef5';
const GREEN = '#38e8c5';
const AMBER = '#f5c542';
const RED = '#f55b5b';
const PURPLE = '#b06ef5';

function baseScales() {
  return {
    x: { ticks: { color: TICK_COLOR, font: { family: 'DM Mono', size: 10 } }, grid: { color: GRID_COLOR } },
    y: { ticks: { color: TICK_COLOR, font: { family: 'DM Mono', size: 10 } }, grid: { color: GRID_COLOR }, beginAtZero: true }
  };
}

// ─── RENDER ───
function render(data) {
  statsData = data;
  destroyCharts();

  const { totals, users, daily, boards } = data;
  const net = totals.created - totals.closed;
  const rate = totals.created > 0 ? ((totals.closed / totals.created) * 100).toFixed(1) : 0;

  // KPIs
  document.getElementById('kpi-created').textContent = totals.created;
  document.getElementById('kpi-closed').textContent = totals.closed;
  document.getElementById('kpi-net').textContent = net >= 0 ? `+${net}` : `${net}`;
  document.getElementById('kpi-net').style.color = net > 0 ? RED : net < 0 ? GREEN : '#6b7280';
  document.getElementById('kpi-rate').textContent = `${rate}%`;
  document.getElementById('kpi-rate').style.color = rate >= 100 ? GREEN : rate >= 70 ? AMBER : RED;
  document.getElementById('kpi-users').textContent = users.length;
  document.getElementById('kpi-boards').textContent = (boards || []).length;

  const perDay = (v) => currentDays > 0 ? (v / currentDays).toFixed(1) : 0;
  document.getElementById('kpi-created-sub').textContent = `${perDay(totals.created)}/day avg`;
  document.getElementById('kpi-closed-sub').textContent = `${perDay(totals.closed)}/day avg`;
  document.getElementById('kpi-net-sub').textContent = net > 0 ? 'Queue growing' : net < 0 ? 'Queue shrinking' : 'In balance';
  document.getElementById('kpi-rate-sub').textContent = rate >= 100 ? 'Keeping up' : 'Backlog growing';
  document.getElementById('kpi-users-sub').textContent = `In last ${currentDays} days`;
  document.getElementById('kpi-boards-sub').textContent = 'With activity';
  document.querySelectorAll('.kpi').forEach(k => k.classList.remove('loading'));

  // Trend badge
  const busiest = daily.reduce((a, b) => (a.created + a.closed > b.created + b.closed ? a : b), daily[0] || {});
  document.getElementById('trend-badge').textContent = busiest.date ? `Busiest: ${busiest.date}` : `Last ${currentDays} days`;

  // ── Trend Chart
  charts.trend = new Chart(document.getElementById('trendChart'), {
    type: 'bar',
    data: {
      labels: daily.map(d => d.date),
      datasets: [
        { label: 'Created', data: daily.map(d => d.created), backgroundColor: 'rgba(91,110,245,0.5)', borderColor: BLUE, borderWidth: 1, borderRadius: 3 },
        { label: 'Closed',  data: daily.map(d => d.closed),  backgroundColor: 'rgba(56,232,197,0.5)', borderColor: GREEN, borderWidth: 1, borderRadius: 3 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: TICK_COLOR, font: { family: 'DM Mono', size: 10 } } } },
      scales: baseScales()
    }
  });

  // ── Board Donut
  const topBoards = (boards || []).slice(0, 8);
  const DONUT_COLORS = [BLUE, GREEN, AMBER, RED, PURPLE, '#38b6e8', '#f58c42', '#c5f542'];
  charts.donut = new Chart(document.getElementById('boardDonut'), {
    type: 'doughnut',
    data: {
      labels: topBoards.map(b => b.name),
      datasets: [{ data: topBoards.map(b => b.created + b.closed), backgroundColor: DONUT_COLORS, borderColor: '#0d0f1c', borderWidth: 2, hoverOffset: 6 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '68%',
      plugins: { legend: { position: 'bottom', labels: { color: TICK_COLOR, font: { family: 'DM Mono', size: 9 }, boxWidth: 10, padding: 8 } } }
    }
  });

  // ── Ratio Chart
  charts.ratio = new Chart(document.getElementById('ratioChart'), {
    type: 'doughnut',
    data: {
      labels: ['Closed', 'Still Open'],
      datasets: [{ data: [totals.closed, Math.max(0, totals.created - totals.closed)], backgroundColor: [GREEN, RED], borderColor: '#0d0f1c', borderWidth: 2, hoverOffset: 6 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '68%',
      plugins: {
        legend: { position: 'bottom', labels: { color: TICK_COLOR, font: { family: 'DM Mono', size: 10 }, boxWidth: 10, padding: 8 } },
        tooltip: { callbacks: { label: ctx => ` ${ctx.raw} tickets (${totals.created > 0 ? ((ctx.raw/totals.created)*100).toFixed(1) : 0}%)` } }
      }
    }
  });

  // ── Leaderboard
  renderLeaderboard(users, 'total');

  // ── Board table
  renderBoardTable(boards || []);

  // ── User bar chart
  const top10 = users.slice(0, 10);
  charts.userBar = new Chart(document.getElementById('userBarChart'), {
    type: 'bar',
    data: {
      labels: top10.map(u => u.name.split(' ')[0]),
      datasets: [
        { label: 'Created', data: top10.map(u => u.created), backgroundColor: 'rgba(91,110,245,0.6)', borderColor: BLUE, borderWidth: 1, borderRadius: 4 },
        { label: 'Closed',  data: top10.map(u => u.closed),  backgroundColor: 'rgba(56,232,197,0.6)', borderColor: GREEN, borderWidth: 1, borderRadius: 4 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, indexAxis: top10.length > 6 ? 'y' : 'x',
      plugins: { legend: { labels: { color: TICK_COLOR, font: { family: 'DM Mono', size: 10 } } } },
      scales: baseScales()
    }
  });

  // ── Cumulative
  let cumCreated = 0, cumClosed = 0;
  const cumData = daily.map(d => {
    cumCreated += d.created; cumClosed += d.closed;
    return { date: d.date, created: cumCreated, closed: cumClosed };
  });
  document.getElementById('cumul-badge').textContent = `Final: ${cumCreated} created / ${cumClosed} closed`;
  charts.cumul = new Chart(document.getElementById('cumulChart'), {
    type: 'line',
    data: {
      labels: cumData.map(d => d.date),
      datasets: [
        { label: 'Cumulative Created', data: cumData.map(d => d.created), borderColor: BLUE, backgroundColor: 'rgba(91,110,245,0.08)', fill: true, tension: 0.35, pointRadius: 3, pointBackgroundColor: BLUE },
        { label: 'Cumulative Closed',  data: cumData.map(d => d.closed),  borderColor: GREEN, backgroundColor: 'rgba(56,232,197,0.08)', fill: true, tension: 0.35, pointRadius: 3, pointBackgroundColor: GREEN }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: TICK_COLOR, font: { family: 'DM Mono', size: 10 } } } },
      scales: baseScales()
    }
  });
}

function renderLeaderboard(users, sortBy) {
  const sorted = [...users].sort((a, b) => {
    if (sortBy === 'closed') return b.closed - a.closed;
    if (sortBy === 'created') return b.created - a.created;
    return (b.created + b.closed) - (a.created + a.closed);
  });
  const maxVal = sorted.length ? (sortBy === 'closed' ? sorted[0].closed : sortBy === 'created' ? sorted[0].created : sorted[0].created + sorted[0].closed) : 1;

  const html = sorted.map((u, i) => {
    const net = u.created - u.closed;
    const netCls = net > 0 ? 'pos' : net < 0 ? 'neg' : 'zero';
    const netStr = net > 0 ? `+${net}` : `${net}`;
    const val = sortBy === 'closed' ? u.closed : sortBy === 'created' ? u.created : u.created + u.closed;
    const rankCls = i === 0 ? 'gold' : i === 1 ? 'silver' : i === 2 ? 'bronze' : '';
    const rankIcon = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i+1}`;
    const pct = maxVal > 0 ? (val / maxVal * 100) : 0;
    return `<div class="lb-row" data-user="${i}" style="cursor:pointer" onclick="openUserModal(${i})">
      <div class="lb-rank ${rankCls}">${rankIcon}</div>
      <div>
        <div class="lb-name">${u.name}</div>
        <div class="lb-bar-wrap"><div class="lb-bar" style="width:${pct}%"></div></div>
      </div>
      <div class="lb-val created">${u.created}</div>
      <div class="lb-val closed">${u.closed}</div>
      <div class="lb-val net ${netCls}">${netStr}</div>
    </div>`;
  }).join('');

  const header = `<div class="lb-row" style="border-bottom:1px solid var(--border2);cursor:default;pointer-events:none">
    <div></div><div style="font-family:var(--font-mono);font-size:.6rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Technician</div>
    <div style="font-family:var(--font-mono);font-size:.6rem;color:var(--blue);text-align:right;text-transform:uppercase;letter-spacing:1px">Created</div>
    <div style="font-family:var(--font-mono);font-size:.6rem;color:var(--green);text-align:right;text-transform:uppercase;letter-spacing:1px">Closed</div>
    <div style="font-family:var(--font-mono);font-size:.6rem;color:var(--text-dim);text-align:right;text-transform:uppercase;letter-spacing:1px">Net</div>
  </div>`;
  document.getElementById('lb-body').innerHTML = header + (html || '<div class="loading-state" style="padding:20px">No data</div>');

  window._sortedUsers = sorted;
}

function openUserModal(idx) {
  const u = window._sortedUsers[idx];
  if (u) openModal(u);
}

function renderBoardTable(boards) {
  document.getElementById('board-count-badge').textContent = `${boards.length} boards`;
  const sorted = [...boards].sort((a, b) => (b.created + b.closed) - (a.created + a.closed));
  const html = sorted.map(b => {
    const net = b.created - b.closed;
    const netBadge = net > 0 ? `<span class="badge-n-pos">+${net}</span>` : net < 0 ? `<span class="badge-n-neg">${net}</span>` : `<span class="badge-n-zero">0</span>`;
    return `<tr>
      <td>${b.name}</td>
      <td class="r"><span class="badge-c">${b.created}</span></td>
      <td class="r"><span class="badge-x">${b.closed}</span></td>
      <td class="r">${netBadge}</td>
    </tr>`;
  }).join('');
  document.getElementById('board-tbody').innerHTML = html || '<tr><td colspan="4" style="color:var(--text-dim);text-align:center;padding:20px">No board data</td></tr>';
}

// ─── LOAD STATS ───
async function loadStats() {
  document.getElementById('status-text').textContent = 'Loading…';
  try {
    const res = await fetch(`/api/ticket-stats?days=${currentDays}`);
    const data = await res.json();
    if (data.error) {
      document.getElementById('status-text').textContent = 'Error';
      return;
    }
    render(data);
    const now = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    document.getElementById('status-text').textContent = `Updated ${now}`;
  } catch(e) {
    document.getElementById('status-text').textContent = 'Failed';
  }
}

// ─── CONFIG CHECK ───
async function checkConfig() {
  try {
    const data = await fetch('/api/config-check').then(r => r.json());
    if (!data.configured) document.getElementById('config-banner').classList.add('show');
  } catch(e) {}
}

// ─── AUTO-REFRESH ───
function startAutoRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(loadStats, REFRESH_INTERVAL * 1000);
}

checkConfig();
loadStats();
startAutoRefresh();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML, refresh_interval=REFRESH_INTERVAL, days_back=DAYS_BACK)


@app.route("/api/ticket-stats")
def ticket_stats():
    try:
        days = int(request.args.get("days", DAYS_BACK))
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        # --- Fetch created tickets ---
        created_params = {
            "conditions": f"dateEntered >= [{since_str}] and parentTicketId = null",
            "fields": "id,summary,owner,board,dateEntered",
            "orderBy": "dateEntered asc"
        }
        created_tickets = cw_get("/service/tickets", created_params)

        # --- Fetch closed tickets ---
        closed_params = {
            "conditions": f"closedFlag = true and lastUpdated >= [{since_str}] and parentTicketId = null",
            "fields": "id,summary,owner,board,lastUpdated,closedDate",
            "orderBy": "lastUpdated asc"
        }
        closed_tickets = cw_get("/service/tickets", closed_params)

        # --- Daily buckets ---
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

        # --- Per-user aggregation ---
        user_created = defaultdict(list)
        user_closed  = defaultdict(list)

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

        for t in created_tickets:
            user_created[get_owner(t)].append(get_board(t))

        for t in closed_tickets:
            user_closed[get_owner(t)].append(get_board(t))

        all_users = set(user_created.keys()) | set(user_closed.keys())

        users_result = []
        for name in sorted(all_users):
            created_boards = user_created[name]
            closed_boards  = user_closed[name]
            board_names = set(created_boards) | set(closed_boards)
            boards = []
            for bn in sorted(board_names):
                if not bn:
                    continue
                boards.append({
                    "name": bn,
                    "created": created_boards.count(bn),
                    "closed": closed_boards.count(bn)
                })
            boards.sort(key=lambda x: x["created"] + x["closed"], reverse=True)
            users_result.append({
                "name": name,
                "created": len(created_boards),
                "closed": len(closed_boards),
                "boards": boards
            })

        users_result.sort(key=lambda u: u["created"] + u["closed"], reverse=True)

        # --- Board-level aggregation ---
        board_created = defaultdict(int)
        board_closed  = defaultdict(int)
        for t in created_tickets:
            bn = get_board(t)
            if bn:
                board_created[bn] += 1
        for t in closed_tickets:
            bn = get_board(t)
            if bn:
                board_closed[bn] += 1

        all_board_names = set(board_created.keys()) | set(board_closed.keys())
        boards_result = []
        for bn in all_board_names:
            boards_result.append({
                "name": bn,
                "created": board_created[bn],
                "closed": board_closed[bn]
            })
        boards_result.sort(key=lambda b: b["created"] + b["closed"], reverse=True)

        return jsonify({
            "totals": {
                "created": len(created_tickets),
                "closed": len(closed_tickets)
            },
            "users": users_result,
            "daily": list(daily_buckets.values()),
            "boards": boards_result,
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
