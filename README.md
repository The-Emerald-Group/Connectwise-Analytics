# CW Pulse — ConnectWise Ticket Analytics

A self-hosted analytics dashboard for ConnectWise Manage, showing ticket **created** and **closed** counts with full reporting across technicians and boards.

![Dashboard](https://img.shields.io/badge/status-active-brightgreen) ![Docker](https://img.shields.io/badge/docker-ready-blue)

## Features

- **KPI Summary** — created, closed, net change, close rate %, active techs, active boards
- **Daily Trend Chart** — bar chart of created vs closed per day
- **Cumulative Trend** — running totals over the selected period
- **Board Distribution** — donut chart showing volume per board
- **Created vs Closed Ratio** — at-a-glance queue health donut
- **Technician Leaderboard** — sortable by total / closed / created with rank medals
- **Per-Technician Bar Chart** — side-by-side volume for all active techs
- **Board Breakdown Table** — created, closed, net per board with colour-coded badges
- **Technician Detail Modal** — click any tech to see their close rate and board-by-board breakdown
- **Dynamic Day Range** — switch between 1D / 7D / 14D / 30D / 90D in the UI without reloading
- **Auto-refresh** on a configurable interval (default: 5 minutes)

---

## Quick Start

### Docker Compose (recommended)

1. Edit `docker-compose.yml` with your ConnectWise credentials
2. Run:
```bash
docker compose up -d
```
3. Open http://localhost:5001

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `CW_SITE` | ConnectWise API hostname | `api-eu.myconnectwise.net` |
| `CW_COMPANY` | Company login ID | *(required)* |
| `CW_PUBLIC_KEY` | API public key | *(required)* |
| `CW_PRIVATE_KEY` | API private key | *(required)* |
| `CW_CLIENT_ID` | Developer client ID | *(required)* |
| `CW_VERIFY_SSL` | Verify SSL certificates | `true` |
| `HTTPS_PROXY` | Proxy URL if required | *(none)* |
| `CW_REFRESH_INTERVAL` | Auto-refresh in seconds | `300` |
| `CW_DAYS_BACK` | Default days to report on | `7` |

> **Note:** The day range can also be changed live in the dashboard UI (1D / 7D / 14D / 30D / 90D).

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard UI |
| `GET /api/ticket-stats?days=N` | Full analytics payload (JSON) |
| `GET /api/config-check` | Verify environment config (JSON) |

---

## Docker Hub

```bash
docker pull samuelstreets/connectwise-anaytics:latest
```
