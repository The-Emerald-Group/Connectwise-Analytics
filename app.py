import os
import requests
import base64
import urllib3
import traceback
import sqlite3
import json
from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from apscheduler.schedulers.background import BackgroundScheduler

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__, template_folder=".")

CW_SITE        = os.environ.get("CW_SITE", "api-eu.myconnectwise.net")
CW_COMPANY     = os.environ.get("CW_COMPANY", "")
CW_PUBLIC_KEY  = os.environ.get("CW_PUBLIC_KEY", "")
CW_PRIVATE_KEY = os.environ.get("CW_PRIVATE_KEY", "")
CW_CLIENT_ID   = os.environ.get("CW_CLIENT_ID", "")
HTTPS_PROXY    = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
REFRESH_INTERVAL = int(os.environ.get("CW_REFRESH_INTERVAL", "300"))
VERIFY_SSL     = os.environ.get("CW_VERIFY_SSL", "true").lower() != "false"
DAYS_BACK      = int(os.environ.get("CW_DAYS_BACK", "7"))

IGNORE_USERS_RAW = os.environ.get("CW_IGNORE_USERS", "")
CW_IGNORE_USERS = [u.strip().lower() for u in IGNORE_USERS_RAW.split(",") if u.strip()]

# Closed status names — add any extra names your CW instance uses via CW_CLOSED_STATUSES env var
DEFAULT_CLOSED_STATUSES = {"completed", "resolved", "closed", "done", "fixed", "complete", "closed - resolved", "closed - complete"}
EXTRA_CLOSED_STATUSES_RAW = os.environ.get("CW_CLOSED_STATUSES", "")
EXTRA_CLOSED_STATUSES = {s.strip().lower() for s in EXTRA_CLOSED_STATUSES_RAW.split(",") if s.strip()}
CLOSED_STATUSES = DEFAULT_CLOSED_STATUSES | EXTRA_CLOSED_STATUSES

# ── DATABASE & BACKGROUND SYNC SETUP ──
DB_PATH = "data/cw_pulse.db"
MEMBER_MAP_CACHE = {}
MEMBER_MAP_LAST_FETCH = None

os.makedirs("data", exist_ok=True)

def init_db():
    """Initialize the SQLite database schema."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY,
            lastUpdated TEXT,
            dateEntered TEXT,
            raw_data TEXT
        )
    ''')
    conn.commit()
    conn.close()

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

def sync_tickets():
    """Background task to sync modified tickets from ConnectWise to SQLite."""
    print("🔄 Starting background ticket sync...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT MAX(lastUpdated) FROM tickets")
        last_updated = cursor.fetchone()[0]

        if not last_updated:
            since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
            conditions = f"lastUpdated >= [{since}] and parentTicketId = null"
        else:
            conditions = f"lastUpdated > [{last_updated}] and parentTicketId = null"

        updated_tickets = cw_get("/service/tickets", {"conditions": conditions})

        for t in updated_tickets:
            info = t.get("_info", {})
            t_last_updated = info.get("lastUpdated") or t.get("lastUpdated")
            t_date_entered = t.get("dateEntered") or info.get("dateEntered")
            
            cursor.execute('''
                INSERT OR REPLACE INTO tickets (id, lastUpdated, dateEntered, raw_data)
                VALUES (?, ?, ?, ?)
            ''', (t.get("id"), t_last_updated, t_date_entered, json.dumps(t)))

        conn.commit()
        conn.close()
        print(f"✅ Sync complete. Inserted/Updated {len(updated_tickets)} tickets.")
    except Exception as e:
        print(f"❌ Error syncing tickets: {e}")
        traceback.print_exc()

def get_db_tickets(conditions_func):
    """Retrieve tickets from the local SQLite DB based on a python filter function."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT raw_data FROM tickets")
    
    results = []
    for row in cursor.fetchall():
        ticket = json.loads(row[0])
        if conditions_func(ticket):
            results.append(ticket)
            
    conn.close()
    return results

def get_members_map():
    global MEMBER_MAP_CACHE, MEMBER_MAP_LAST_FETCH
    now = datetime.now(timezone.utc)
    
    if MEMBER_MAP_LAST_FETCH and (now - MEMBER_MAP_LAST_FETCH).total_seconds() < 3600:
        return MEMBER_MAP_CACHE
        
    try:
        members = cw_get("/system/members", {"fields": "identifier,firstName,lastName"})
        m_map = {}
        for m in members:
            ident = m.get("identifier", "")
            if ident:
                fname = m.get("firstName", "")
                lname = m.get("lastName", "")
                full = f"{fname} {lname}".strip()
                if full:
                    m_map[ident.lower()] = full
        MEMBER_MAP_CACHE = m_map
        MEMBER_MAP_LAST_FETCH = now
    except Exception as e:
        print(f"Failed to fetch members dictionary: {e}")
        
    return MEMBER_MAP_CACHE

def get_real_name(identifier, fallback_owner, m_map):
    if identifier:
        ident_lower = identifier.lower()
        if ident_lower in m_map:
            return m_map[ident_lower]
        return identifier.title()
    
    if fallback_owner and isinstance(fallback_owner, dict):
        ident = fallback_owner.get("identifier", "")
        if ident and ident.lower() in m_map:
            return m_map[ident.lower()]
        return fallback_owner.get("name", "Unassigned")
    
    return "Unassigned"

def is_closed_ticket(t):
    """Check if a ticket is closed/completed using closedFlag or status name matching."""
    if t.get("closedFlag") is True:
        return True
    st = t.get("status", {})
    st_name = st.get("name", "").lower().strip() if isinstance(st, dict) else str(st).lower().strip()
    return st_name in CLOSED_STATUSES

# Boot Sequence: Setup DB and Start Scheduler
init_db()
scheduler = BackgroundScheduler()
scheduler.add_job(func=sync_tickets, trigger="interval", seconds=REFRESH_INTERVAL)
scheduler.start()
sync_tickets()

# ── ROUTES ──

@app.route("/")
def index():
    ui_site = CW_SITE.replace("api-", "", 1) if CW_SITE.startswith("api-") else CW_SITE
    cw_base_url = f"https://{ui_site}/v4_6_release/services/system_io/Service/fv_sr100_request.rails?companyName={CW_COMPANY}&service_recid="
    return render_template("index.html", refresh_interval=REFRESH_INTERVAL, days_back=DAYS_BACK, cw_base_url=cw_base_url)

@app.route("/api/ticket-stats")
def ticket_stats():
    try:
        days = int(request.args.get("days", DAYS_BACK))
        now  = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        m_map = get_members_map()

        # Database Filters
        def is_created_recently(t):
            dt = t.get("dateEntered") or t.get("_info", {}).get("dateEntered")
            return dt and dt >= since_str

        def is_updated_recently(t):
            dt = t.get("lastUpdated") or t.get("_info", {}).get("lastUpdated")
            return dt and dt >= since_str

        created_tickets = get_db_tickets(is_created_recently)
        recently_updated = get_db_tickets(is_updated_recently)

        completed_tickets = [t for t in recently_updated if is_closed_ticket(t)]

        daily_buckets = {}
        for i in range(days):
            day = (since + timedelta(days=i)).strftime("%d %b")
            daily_buckets[day] = {"date": day, "created": 0, "completed": 0}

        def day_key(iso):
            try:
                if not iso: return None
                return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b")
            except Exception:
                return None

        for t in created_tickets:
            info = t.get("_info", {})
            dt = t.get("dateEntered") or info.get("dateEntered")
            k = day_key(dt)
            if k and k in daily_buckets:
                daily_buckets[k]["created"] += 1

        for t in completed_tickets:
            info = t.get("_info", {})
            dt = t.get("dateResolved") or t.get("closedDate") or info.get("lastUpdated") or t.get("lastUpdated")
            k = day_key(dt)
            if k and k in daily_buckets:
                daily_buckets[k]["completed"] += 1

        def get_creator(t):
            info = t.get("_info", {})
            eb = t.get("enteredBy") or info.get("enteredBy")
            return get_real_name(eb, t.get("owner"), m_map), eb

        def get_completer(t):
            info = t.get("_info", {})
            cb = t.get("closedBy") or info.get("closedBy") or info.get("updatedBy")
            return get_real_name(cb, t.get("owner"), m_map), cb

        def get_board(t):
            b = t.get("board")
            if isinstance(b, dict): return b.get("name", "")
            return b or ""

        user_created = defaultdict(list)
        user_completed  = defaultdict(list)
        user_created_tickets = defaultdict(list)
        user_completed_tickets = defaultdict(list)
        
        for t in created_tickets:
            user_real, user_raw = get_creator(t)
            user_raw = user_raw or ""
            if user_real.lower() not in CW_IGNORE_USERS and user_raw.lower() not in CW_IGNORE_USERS:
                board_name = get_board(t)
                user_created[user_real].append(board_name)
                user_created_tickets[user_real].append({
                    "id": t.get("id"),
                    "summary": t.get("summary", "No Summary"),
                })
                
        for t in completed_tickets:
            user_real, user_raw = get_completer(t)
            user_raw = user_raw or ""
            if user_real.lower() not in CW_IGNORE_USERS and user_raw.lower() not in CW_IGNORE_USERS:
                board_name = get_board(t)
                user_completed[user_real].append(board_name)
                user_completed_tickets[user_real].append({
                    "id": t.get("id"),
                    "summary": t.get("summary", "No Summary"),
                })

        all_users = set(user_created.keys()) | set(user_completed.keys())
        users_result = []
        for name in sorted(all_users):
            if name.lower() in ["unassigned", ""]: continue
            cb = user_created[name]; xb = user_completed[name]
            bn = set(cb) | set(xb)
            boards = [{"name": b, "created": cb.count(b), "completed": xb.count(b)} for b in sorted(bn) if b]
            boards.sort(key=lambda x: x["created"]+x["completed"], reverse=True)
            
            users_result.append({
                "name": name, 
                "created": len(cb), 
                "completed": len(xb), 
                "boards": boards,
                "createdTickets": user_created_tickets[name],
                "completedTickets": user_completed_tickets[name]
            })
            
        users_result.sort(key=lambda u: u["created"]+u["completed"], reverse=True)

        board_created = defaultdict(int)
        board_completed  = defaultdict(int)
        for t in created_tickets:
            bn = get_board(t)
            if bn: board_created[bn] += 1
        for t in completed_tickets:
            bn = get_board(t)
            if bn: board_completed[bn] += 1

        all_board_names = set(board_created.keys()) | set(board_completed.keys())
        boards_result = [{"name": bn, "created": board_created[bn], "completed": board_completed[bn]} for bn in all_board_names]
        boards_result.sort(key=lambda b: b["created"]+b["completed"], reverse=True)

        return jsonify({
            "totals": {"created": len(created_tickets), "completed": len(completed_tickets)},
            "users": users_result,
            "daily": list(daily_buckets.values()),
            "boards": boards_result,
            "asOf": now.isoformat(),
            "daysBack": days
        })

    except Exception as e:
        print(f"--- API ERROR IN TICKET STATS ---")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/api/customer-stats")
def customer_stats():
    try:
        days = int(request.args.get("days", DAYS_BACK))
        now  = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        m_map = get_members_map()

        # Database Filters
        def is_created_recently(t):
            dt = t.get("dateEntered") or t.get("_info", {}).get("dateEntered")
            return dt and dt >= since_str

        def is_updated_recently(t):
            dt = t.get("lastUpdated") or t.get("_info", {}).get("lastUpdated")
            return dt and dt >= since_str
            
        def is_open(t):
            return not is_closed_ticket(t)

        created_tickets = get_db_tickets(is_created_recently)
        recently_updated = get_db_tickets(is_updated_recently)
        
        all_db_tickets = get_db_tickets(lambda t: True)
        open_tickets = [t for t in all_db_tickets if is_open(t)]

        completed_tickets = [t for t in recently_updated if is_closed_ticket(t)]

        def get_company(t):
            c = t.get("company")
            if isinstance(c, dict): return c.get("name", "Unknown")
            return c or "Unknown"

        def get_creator(t):
            info = t.get("_info", {})
            eb = t.get("enteredBy") or info.get("enteredBy")
            return get_real_name(eb, t.get("owner"), m_map), eb

        def get_completer(t):
            info = t.get("_info", {})
            cb = t.get("closedBy") or info.get("closedBy") or info.get("updatedBy")
            return get_real_name(cb, t.get("owner"), m_map), cb

        def get_board(t):
            b = t.get("board")
            if isinstance(b, dict): return b.get("name", "")
            return b or ""

        def get_contact(t):
            c = t.get("contact")
            if isinstance(c, dict): return c.get("name", "")
            return c or ""

        def day_key(iso):
            try:
                if not iso: return None
                return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b")
            except Exception:
                return None

        daily_buckets = {}
        for i in range(days):
            day = (since + timedelta(days=i)).strftime("%d %b")
            daily_buckets[day] = {"date": day, "created": 0, "completed": 0, "byCompany": {}}

        for t in created_tickets:
            info = t.get("_info", {})
            dt = t.get("dateEntered") or info.get("dateEntered")
            k = day_key(dt)
            co = get_company(t)
            if k and k in daily_buckets:
                daily_buckets[k]["created"] += 1
                daily_buckets[k]["byCompany"][co] = daily_buckets[k]["byCompany"].get(co, 0) + 1

        for t in completed_tickets:
            info = t.get("_info", {})
            dt = t.get("dateResolved") or t.get("closedDate") or info.get("lastUpdated") or t.get("lastUpdated")
            k = day_key(dt)
            if k and k in daily_buckets:
                daily_buckets[k]["completed"] += 1

        co_created   = defaultdict(int)
        co_completed = defaultdict(int)
        co_contacts  = defaultdict(set)
        
        co_techs_c   = defaultdict(lambda: defaultdict(int)) 
        co_techs_comp= defaultdict(lambda: defaultdict(int))
        co_boards_c  = defaultdict(lambda: defaultdict(int))
        co_boards_comp= defaultdict(lambda: defaultdict(int))

        co_created_tickets = defaultdict(list)
        co_completed_tickets = defaultdict(list)
        co_open_tickets = defaultdict(list)

        for t in created_tickets:
            co = get_company(t)
            co_created[co] += 1
            
            co_created_tickets[co].append({
                "id": t.get("id"),
                "summary": t.get("summary", "No Summary")
            })
            
            ct = get_contact(t)
            if ct: co_contacts[co].add(ct)
            user_real, user_raw = get_creator(t)
            user_raw = user_raw or ""
            if user_real.lower() not in CW_IGNORE_USERS and user_raw.lower() not in CW_IGNORE_USERS:
                co_techs_c[co][user_real] += 1
            bn = get_board(t)
            if bn: co_boards_c[co][bn] += 1

        for t in completed_tickets:
            co = get_company(t)
            co_completed[co] += 1
            
            co_completed_tickets[co].append({
                "id": t.get("id"),
                "summary": t.get("summary", "No Summary")
            })
            
            ct = get_contact(t)
            if ct: co_contacts[co].add(ct)
            user_real, user_raw = get_completer(t)
            user_raw = user_raw or ""
            if user_real.lower() not in CW_IGNORE_USERS and user_raw.lower() not in CW_IGNORE_USERS:
                co_techs_comp[co][user_real] += 1
            bn = get_board(t)
            if bn: co_boards_comp[co][bn] += 1

        co_open = defaultdict(int)
        co_open_boards = defaultdict(lambda: defaultdict(int))
        for t in open_tickets:
            co = get_company(t)
            co_open[co] += 1
            
            co_open_tickets[co].append({
                "id": t.get("id"),
                "summary": t.get("summary", "No Summary")
            })
            
            bn = get_board(t)
            if bn: co_open_boards[co][bn] += 1

        all_cos = set(co_created.keys()) | set(co_completed.keys()) | set(co_open.keys())
        companies_result = []
        for co in all_cos:
            all_techs = set(co_techs_c[co].keys()) | set(co_techs_comp[co].keys())
            techs = [{"name": t, "created": co_techs_c[co].get(t,0), "completed": co_techs_comp[co].get(t,0)} for t in all_techs if t.lower() not in ["unassigned", ""]]
            techs.sort(key=lambda x: x["created"]+x["completed"], reverse=True)

            all_boards = set(co_boards_c[co].keys()) | set(co_boards_comp[co].keys())
            boards = [{"name": b, "created": co_boards_c[co].get(b,0), "completed": co_boards_comp[co].get(b,0)} for b in all_boards]
            boards.sort(key=lambda x: x["created"]+x["completed"], reverse=True)

            companies_result.append({
                "name": co,
                "created": co_created[co],
                "completed": co_completed[co],
                "open": co_open.get(co, 0),
                "contacts": len(co_contacts[co]),
                "technicians": techs,
                "boards": boards,
                "createdTickets": co_created_tickets[co],
                "completedTickets": co_completed_tickets[co],
                "openTickets": co_open_tickets[co]
            })

        companies_result.sort(key=lambda c: c["created"]+c["completed"], reverse=True)
        total_open = len(open_tickets)

        return jsonify({
            "totals": {
                "created": len(created_tickets),
                "completed": len(completed_tickets),
                "open": total_open
            },
            "companies": companies_result,
            "daily": list(daily_buckets.values()),
            "asOf": now.isoformat(),
            "daysBack": days
        })

    except Exception as e:
        print(f"--- API ERROR IN CUSTOMER STATS ---")
        print(traceback.format_exc())
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

@app.route("/api/debug-statuses")
def debug_statuses():
    """Debug endpoint — shows all status names and closedFlag values in the local DB.
    Use this to find out what status names your ConnectWise instance uses so you can
    add them to CW_CLOSED_STATUSES if needed."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tickets")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT raw_data FROM tickets")

    statuses = {}
    close_flags = {"true": 0, "false": 0, "missing": 0}
    matched_closed = 0
    sample_closed = []
    sample_open = []

    for row in cursor.fetchall():
        t = json.loads(row[0])
        st = t.get("status", {})
        st_name = st.get("name", "UNKNOWN").strip() if isinstance(st, dict) else str(st).strip()
        statuses[st_name] = statuses.get(st_name, 0) + 1

        cf = t.get("closedFlag")
        if cf is True:
            close_flags["true"] += 1
        elif cf is False:
            close_flags["false"] += 1
        else:
            close_flags["missing"] += 1

        if is_closed_ticket(t):
            matched_closed += 1
            if len(sample_closed) < 3:
                sample_closed.append({
                    "id": t.get("id"),
                    "status": st_name,
                    "closedFlag": cf,
                    "summary": t.get("summary", "")[:60]
                })
        else:
            if len(sample_open) < 3:
                sample_open.append({
                    "id": t.get("id"),
                    "status": st_name,
                    "closedFlag": cf,
                    "summary": t.get("summary", "")[:60]
                })

    conn.close()

    return jsonify({
        "total_tickets_in_db": total,
        "matched_as_closed": matched_closed,
        "matched_as_open": total - matched_closed,
        "close_flags": close_flags,
        "status_names_and_counts": dict(sorted(statuses.items(), key=lambda x: -x[1])),
        "closed_statuses_being_matched": sorted(list(CLOSED_STATUSES)),
        "sample_closed_tickets": sample_closed,
        "sample_open_tickets": sample_open,
        "tip": "If your closed tickets are showing as open, add the status name(s) to CW_CLOSED_STATUSES env var (comma-separated)"
    })

@app.route("/api/sync-now", methods=["POST"])
def sync_now():
    """Manually trigger a sync. POST to /api/sync-now"""
    try:
        sync_tickets()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tickets")
        total = cursor.fetchone()[0]
        conn.close()
        return jsonify({"status": "ok", "total_tickets_in_db": total})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
