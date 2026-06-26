#!/usr/bin/env python3
"""
Gera data/rezdy_kpis.json com reservas dos últimos 120 dias (todos os status).
Usa filtros de data na API para ser rápido — não pagina o histórico todo.

Uso:
  python gerar_rezdy_kpis.py
  python gerar_rezdy_kpis.py --dias 60
"""
import json, sys, time, argparse, os, requests
from datetime import date, timedelta

API_KEY  = os.environ.get("REZDY_API_KEY", "dc7f8d97256e484b8763a983ded2ba22")
BASE_URL = "https://api.rezdy.com/v1"
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "rezdy_kpis.json")


def get_prod(name: str) -> str:
    n = (name or "").strip()
    if "GYG" in n: return "GYG"
    if n == "Doors off | 30min": return "30min"
    if n == "Doors off | 45min": return "45min"
    return "Other"

def get_src(raw: str, prod: str) -> str:
    if prod == "GYG": return "GYG"
    return "Online" if (raw or "").upper() == "ONLINE" else "Interno"

def fetch_range(date_from: str, date_to: str) -> list:
    all_b, offset = [], 0
    print(f"Buscando {date_from} a {date_to}...")
    while True:
        resp = requests.get(
            f"{BASE_URL}/bookings",
            params={"apiKey": API_KEY, "limit": 100, "offset": offset,
                    "orderDateStart": date_from, "orderDateEnd": date_to},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json().get("bookings", [])
        if not batch:
            break
        all_b.extend(batch)
        print(f"  offset={offset:4d}  lote={len(batch):3d}  total={len(all_b)}")
        if len(batch) < 100:
            break
        offset += 100
        time.sleep(0.15)
    return all_b

def parse(b: dict) -> dict | None:
    d = (b.get("dateCreated") or "")[:10]
    if not d:
        return None
    status = (b.get("status") or "UNKNOWN").upper()
    items  = b.get("items") or []
    item0  = items[0] if items else {}
    df_raw = (item0.get("startTimeLocal") or item0.get("startTime") or "")
    df     = df_raw[:10] if df_raw else d
    prod   = get_prod(item0.get("productName", ""))
    src    = get_src(b.get("source", ""), prod)
    gross  = round(float(b.get("totalAmount") or 0), 2)
    paid   = round(float(b.get("totalPaid")   or 0), 2)
    due    = round(float(b.get("totalDue")    or 0), 2)
    free   = round(max(0.0, gross - paid - due), 2)
    net    = round(gross - free, 2)
    pax    = int(item0.get("totalQuantity") or 0) or 1
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
        "coupon": b.get("coupon") or None,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=120)
    args = parser.parse_args()

    hoje   = date.today()
    inicio = (hoje - timedelta(days=args.dias)).isoformat()
    fim    = hoje.isoformat()

    raw    = fetch_range(inicio, fim)
    orders = [o for b in raw if (o := parse(b))]
    orders.sort(key=lambda x: x["d"], reverse=True)

    # Resumo
    status_counts = {}
    for o in orders:
        status_counts[o["status"]] = status_counts.get(o["status"], 0) + 1
    print(f"\nTotal: {len(orders)} reservas | {sum(1 for o in orders if o['coupon'])} com cupom")
    for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nSalvo: {OUT_FILE}  ({len(orders)} registros)")

if __name__ == "__main__":
    main()
