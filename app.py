import os
import requests
import base64
import urllib3
from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta, timezone
from collections import defaultdict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- THIS IS THE FIX ---
# Tell Flask to look in the current directory ('.') instead of a templates folder
app = Flask(__name__, template_folder=".")
# -----------------------

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

@app.route("/")
def index():
    # Because of our fix above, this now looks for index.html right next to app.py
    return render_template("index.html", refresh_interval=REFRESH_INTERVAL, days_back=DAYS_BACK)

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

@app.route("/api/customer-stats")
def customer_stats():
    try:
        days = int(request.args.get("days", DAYS_BACK))
        now  = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        created_tickets = cw_get("/service/tickets", {
            "conditions": f"dateEntered >= [{since_str}] and parentTicketId = null",
            "fields": "id,company,contact,owner,board,dateEntered",
            "orderBy": "dateEntered asc"
        })

        closed_tickets = cw_get("/service/tickets", {
            "conditions": f"closedFlag = true and lastUpdated >= [{since_str}] and parentTicketId = null",
            "fields": "id,company,contact,owner,board,lastUpdated,closedDate",
            "orderBy": "lastUpdated asc"
        })

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

        co_created   = defaultdict(int)
        co_closed    = defaultdict(int)
        co_contacts  = defaultdict(set)
        co_techs_c   = defaultdict(lambda: defaultdict(int)) 
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
            all_techs = set(co_techs_c[co].keys()) | set(co_techs_x[co].keys())
            techs = [{"name": t, "created": co_techs_c[co].get(t,0), "closed": co_techs_x[co].get(t,0)} for t in all_techs]
            techs.sort(key=lambda x: x["created"]+x["closed"], reverse=True)

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
