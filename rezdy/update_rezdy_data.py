#!/usr/bin/env python3
"""
Fetch Rezdy bookings and regenerate dashboard data files.

Outputs:
  - rezdy/analise-rezdy-periodos.html  (CONFIRMED only, periods 2025/2026)
  - data/periodos.json                 (same data as JSON)
  - data/rezdy_kpis.json               (ALL statuses, last 120 days, with coupons)

Env:  REZDY_API_KEY  (set as GitHub Actions secret)
Run:  python rezdy/update_rezdy_data.py
"""
import os, re, sys, time, requests
from datetime import date, timedelta
import json as _json

API_KEY  = os.environ.get("REZDY_API_KEY", "")
BASE_URL = "https://api.rezdy.com/v1"
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
HTML_FILE   = os.path.normpath(os.path.join(SCRIPT_DIR, "analise-rezdy-periodos.html"))
JSON_FILE   = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "periodos.json"))
KPI_JSON    = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "rezdy_kpis.json"))

if not API_KEY:
    sys.exit("ERROR: REZDY_API_KEY environment variable is not set.")

# Period comparison (analise-rezdy-periodos.html)
STOP_DATE   = "2025-05-25"
PERIOD_2025 = ("2025-05-26", "2025-06-27")
PERIOD_2026 = ("2026-05-26", "2026-06-27")

# KPI JSON: last 120 days (covers the 90-day max filter in the dashboard)
CUTOFF_KPI  = (date.today() - timedelta(days=120)).isoformat()


# ── CATEGORISATION ──────────────────────────────────────────────────────────────

def get_prod(name: str) -> str:
    n = (name or "").strip()
    if "GYG" in n:
        return "GYG"
    if n == "Doors off | 30min":
        return "30min"
    if n == "Doors off | 45min":
        return "45min"
    return "Other"

def get_src(raw_source: str, prod: str) -> str:
    if prod == "GYG":
        return "GYG"
    s = (raw_source or "").upper()
    if s == "ONLINE":
        return "Online"
    return "Interno"


# ── API FETCHING ────────────────────────────────────────────────────────────────

def fetch_all_bookings() -> list:
    """Paginate /v1/bookings (newest first) until past STOP_DATE."""
    all_b, offset, limit = [], 0, 100
    print(f"Fetching bookings (stopping when dateCreated < {STOP_DATE})...")

    while True:
        resp = requests.get(
            f"{BASE_URL}/bookings",
            params={"apiKey": API_KEY, "limit": limit, "offset": offset},
            timeout=30,
        )
        if not resp.ok:
            print(f"  API error {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()

        batch = resp.json().get("bookings", [])
        if not batch:
            break

        all_b.extend(batch)
        oldest = batch[-1].get("dateCreated", "")[:10]
        print(f"  offset={offset:4d}  got={len(batch):3d}  total={len(all_b):4d}  oldest={oldest}")

        if oldest < STOP_DATE or len(batch) < limit:
            break

        offset += limit
        time.sleep(0.1)

    return all_b


# ── PARSERS ─────────────────────────────────────────────────────────────────────

def in_period(date_str: str, period: tuple) -> bool:
    return period[0] <= date_str <= period[1]

def parse_booking(b: dict) -> dict | None:
    """CONFIRMED-only parser for the period comparison page."""
    if (b.get("status") or "").upper() != "CONFIRMED":
        return None

    d = (b.get("dateCreated") or "")[:10]
    if not d:
        return None

    year = int(d[:4])
    if year not in (2025, 2026):
        return None

    period = PERIOD_2025 if year == 2025 else PERIOD_2026
    if not in_period(d, period):
        return None

    items  = b.get("items") or []
    item0  = items[0] if items else {}
    df_raw = (item0.get("startTimeLocal") or item0.get("startTime") or "")
    df     = df_raw[:10] if df_raw else d

    prod_name = item0.get("productName", "")
    prod      = get_prod(prod_name)
    src       = get_src(b.get("source", ""), prod)

    gross = float(b.get("totalAmount") or 0)
    paid  = float(b.get("totalPaid")   or 0)
    due   = float(b.get("totalDue")    or 0)
    free  = round(max(0.0, gross - paid - due), 2)
    net   = round(gross - free, 2)
    gross = round(gross, 2)

    pax = int(item0.get("totalQuantity") or 0)
    if pax == 0:
        pax = 1

    return {
        "y": year, "d": d, "df": df,
        "net": net, "free": free, "gross": gross,
        "pax": pax, "prod": prod, "src": src,
    }

def parse_booking_kpi(b: dict) -> dict | None:
    """All-status parser for rezdy_kpis.json (last 120 days, includes coupons)."""
    d = (b.get("dateCreated") or "")[:10]
    if not d or d < CUTOFF_KPI:
        return None

    status = (b.get("status") or "UNKNOWN").upper()

    items  = b.get("items") or []
    item0  = items[0] if items else {}
    df_raw = (item0.get("startTimeLocal") or item0.get("startTime") or "")
    df     = df_raw[:10] if df_raw else d

    prod_name = item0.get("productName", "")
    prod      = get_prod(prod_name)
    src       = get_src(b.get("source", ""), prod)

    gross = float(b.get("totalAmount") or 0)
    paid  = float(b.get("totalPaid")   or 0)
    due   = float(b.get("totalDue")    or 0)
    free  = round(max(0.0, gross - paid - due), 2)
    net   = round(gross - free, 2)
    gross = round(gross, 2)

    pax = int(item0.get("totalQuantity") or 0)
    if pax == 0:
        pax = 1

    coupon = b.get("coupon") or None

    return {
        "id":     b.get("orderNumber", ""),
        "status": status,
        "d":      d,
        "df":     df,
        "gross":  gross,
        "net":    net,
        "free":   free,
        "pax":    pax,
        "prod":   prod,
        "src":    src,
        "coupon": coupon,
    }


# ── MAIN ─────────────────────────────────────────────────────────────────────────

def main():
    raw = fetch_all_bookings()
    print(f"\nTotal raw bookings fetched: {len(raw)}")

    # ── Period comparison (CONFIRMED only) ─────────────────────────────────────
    orders = []
    for b in raw:
        o = parse_booking(b)
        if o:
            orders.append(o)

    if not orders and raw:
        print("\nDEBUG: no confirmed period orders — first raw booking:")
        first = raw[0]
        for k, v in first.items():
            if k != "items":
                print(f"  {k}: {v!r}")
        if first.get("items"):
            print(f"  items[0]: {first['items'][0]!r}")

    by_yr = {2025: sum(1 for o in orders if o["y"] == 2025),
             2026: sum(1 for o in orders if o["y"] == 2026)}
    print(f"Period orders (CONFIRMED) → 2025: {by_yr[2025]}  2026: {by_yr[2026]}")

    orders.sort(key=lambda o: (o["y"], o["d"]), reverse=True)

    entries = [
        (f'{{"y":{o["y"]},"d":"{o["d"]}","df":"{o["df"]}",'
         f'"net":{o["net"]},"free":{o["free"]},"gross":{o["gross"]},'
         f'"pax":{o["pax"]},"prod":"{o["prod"]}","src":"{o["src"]}"}}')
        for o in orders
    ]

    today_str = date.today().strftime("%d/%m/%Y")

    # Patch analise-rezdy-periodos.html
    js_arr = "var ORDERS = [" + ",".join(entries) + "];"
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()
    start = html.index("var ORDERS = [")
    end   = html.index("];", start) + 2
    html  = html[:start] + js_arr + html[end:]
    html  = re.sub(r"\d{2}/\d{2}/\d{4} &middot; Vertical Rio",
                   f"{today_str} &middot; Vertical Rio", html)
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Updated analise-rezdy-periodos.html  ({len(orders)} orders)")

    # Write data/periodos.json
    os.makedirs(os.path.dirname(JSON_FILE), exist_ok=True)
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        _json.dump(orders, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Updated data/periodos.json            ({len(orders)} orders)")

    # ── KPI JSON (all statuses, last 120 days) ─────────────────────────────────
    kpi_orders = []
    for b in raw:
        o = parse_booking_kpi(b)
        if o:
            kpi_orders.append(o)

    kpi_orders.sort(key=lambda o: o["d"], reverse=True)

    status_counts = {}
    for o in kpi_orders:
        status_counts[o["status"]] = status_counts.get(o["status"], 0) + 1
    coupons_used = sum(1 for o in kpi_orders if o["coupon"])
    print(f"KPI orders (last 120 days) → total: {len(kpi_orders)}  coupons used: {coupons_used}")
    for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")

    os.makedirs(os.path.dirname(KPI_JSON), exist_ok=True)
    with open(KPI_JSON, "w", encoding="utf-8") as f:
        _json.dump(kpi_orders, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Updated data/rezdy_kpis.json           ({len(kpi_orders)} orders)")
    print(f"Footer date: {today_str}")


if __name__ == "__main__":
    main()
