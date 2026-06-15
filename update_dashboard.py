import os, requests, json, time, csv, io
from datetime import datetime, timezone

EMAIL    = os.getenv("ACHANTO_EMAIL")
PASSWORD = os.getenv("ACHANTO_PASSWORD")
BASE_URL = "https://wms-api.anchanto.com"
TODAY    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

print(f"=== Scarlett Dashboard Updater ===")
print(f"Run time : {NOW}")
print(f"Fetching : {TODAY} 00:00 → 23:59")

# 1. Login
print("\n[1/5] Login...")
r = requests.post(f"{BASE_URL}/api/login",
    json={"api_user": {"email": EMAIL, "password": PASSWORD}}, timeout=30)
r.raise_for_status()
jwt = r.json()["jwt"]
print("      ✓ Login success")
H = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}

# 2. Create report
# CONFIRMED WORKING COLUMNS (21 cols):
# Marketplace, Order Date, Order Number, Item Name, Kit Name,
# Ordered Quantity, Total Ordered Qty, Paid Amount, Payment Method,
# Order Status, Customer Name, Shipping Provider, Shipment Type Name,
# Tracking Number, Order Picking Time, Order Packing Time,
# Shipping Fee, Billing Name, Billing Address Line,
# Delivery Date (DD/MM/YYYY), Dispatch Scheduled Date
print("\n[2/5] Creating report...")
payload = {"report_schedule": {
    "report_type_id": "3", "report_format": "csv",
    "report_occurrence_id": "5", "mailing_list": [""],
    "field_ids": [
        "12","14","16","22","623","28","1220",
        "29","30","31","32","33","34","35","36",
        "50","51","52","53","54","55","56","57","58","59","60",
        "61","62","63","64","65","66","67","68","69","70",
        "71","72","73","74","75","76","77","78","79","80",
        "1300","1301","1302","1303","1304","1305",
    ],
    "filters": {"company_id": ["2"], "campaign_code": []},
    "from_date": TODAY, "end_date": TODAY,
    "notification_type": "email", "carrier_code": []
}}
cr = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=payload, timeout=30)
cr.raise_for_status()
cd = cr.json()
if cd.get("status_code") != 1000:
    print(f"      ✗ {json.dumps(cd, indent=2)}"); exit(1)
report_id = cd["data"]["id"]
print(f"      ✓ Report created (ID: {report_id})")

# 3. Poll
print("\n[3/5] Waiting for report...")
report_url = ""
for i in range(1, 25):
    time.sleep(15)
    try:
        ch = requests.get(f"{BASE_URL}/api/v1/report_schedules/{report_id}", headers=H, timeout=30)
        if not ch.text.strip():
            print(f"      [{i:02d}/24] empty response, retrying...")
            continue
        at = ch.json().get("data", {}).get("attributes", {})
        status = at.get("status","")
        url    = at.get("report_url","")
        print(f"      [{i:02d}/24] status={status}")
        if url:
            report_url = url; print("      ✓ Report ready!"); break
    except Exception as e:
        print(f"      [{i:02d}/24] poll error: {e}, retrying...")
        continue
if not report_url:
    print("      ✗ Timeout"); exit(1)

# 4. Download
print("\n[4/5] Downloading CSV...")
cr2 = requests.get(report_url, timeout=120)
cr2.raise_for_status()
csv_text = cr2.content.decode("utf-8-sig")
reader = csv.DictReader(io.StringIO(csv_text))
rows = list(reader)
cols = reader.fieldnames or []
print(f"      ✓ {len(rows):,} rows · {len(cols)} columns")
print(f"      Columns: {cols}")

# 5. Save
print("\n[5/5] Saving...")
os.makedirs("data", exist_ok=True)
os.makedirs("data/history", exist_ok=True)

with open("data/orders.csv", "w", encoding="utf-8", newline="") as f:
    f.write(csv_text)
meta = {"date": TODAY, "last_updated": NOW,
        "run_at_hour": datetime.now(timezone.utc).hour,
        "total_rows": len(rows), "columns": cols}
with open("data/last_updated.json", "w") as f:
    json.dump(meta, f, indent=2)
print(f"      ✓ orders.csv & last_updated.json saved")

# ── 5b. Compute & save daily summary (lightweight, 30-day trend) ───────────
# Fail-safe: kalau bagian ini error, tidak mengganggu update dashboard utama
try:
    # ── Compute & save daily summary (lightweight, for 30-day trend charts) ──
    GOOD_STATUS = {"dispatched","picked","packed","manifest_created","delivered",
                    "qc_done","received_at_warehouse","assigned","partial_picked"}
    BAD_STATUS = {"unassigned","problem"}

    import re as _re
    orders_seen = {}
    hourly_orders = [0]*24
    hourly_qty = [0]*24
    for r in rows:
        on = (r.get("Order Number") or "").strip()
        if not on:
            continue
        st = (r.get("Order Status") or "").strip().lower().replace(" ", "_")
        qty = int(r.get("Ordered Quantity") or 0)
        if on not in orders_seen:
            order_date_str = r.get("Order Date") or ""
            hm = _re.search(r",\s*(\d{2}):", order_date_str)
            hr = int(hm.group(1)) if hm else 0
            orders_seen[on] = {"st": st, "qty": 0, "hr": hr}
            hourly_orders[hr] += 1
        orders_seen[on]["qty"] += qty
        hourly_qty[orders_seen[on]["hr"]] += qty

    total_orders = len(orders_seen)
    total_qty = sum(o["qty"] for o in orders_seen.values())
    good_count = sum(1 for o in orders_seen.values() if o["st"] in GOOD_STATUS)
    bad_count = sum(1 for o in orders_seen.values() if o["st"] in BAD_STATUS)
    fulfillment_pct = round(good_count / total_orders * 100, 1) if total_orders else 0

    peak_hour = hourly_orders.index(max(hourly_orders)) if total_orders else None
    peak_hour_orders = hourly_orders[peak_hour] if peak_hour is not None else 0
    peak_hour_qty = hourly_qty[peak_hour] if peak_hour is not None else 0

    # Day type label: gajian (25/30/31 or twin date like 6/6, 7/7)
    _d = datetime.strptime(TODAY, "%Y-%m-%d")
    day_of_month = _d.day
    month = _d.month
    if day_of_month in (25, 30, 31):
        day_type = "gajian"
    elif day_of_month == month and day_of_month <= 12:
        day_type = "tanggal_kembar"
    else:
        day_type = "biasa"

    summary_entry = {
        "date": TODAY,
        "total_orders": total_orders,
        "total_qty": total_qty,
        "fulfilled": good_count,
        "pending": bad_count,
        "fulfillment_pct": fulfillment_pct,
        "total_atp": None,  # filled later if inventory report succeeds
        "peak_hour": peak_hour,
        "peak_hour_orders": peak_hour_orders,
        "peak_hour_qty": peak_hour_qty,
        "hourly_orders": hourly_orders,
        "hourly_qty": hourly_qty,
        "day_type": day_type,
        "last_updated": NOW
    }

    summary_path = "data/history/daily_summary.json"
    summary_list = []
    if os.path.exists(summary_path):
        try:
            with open(summary_path) as f:
                summary_list = json.load(f)
        except Exception:
            summary_list = []

    # Replace today's entry if exists, else append
    summary_list = [s for s in summary_list if s.get("date") != TODAY]
    summary_list.append(summary_entry)
    # Keep only last 7 days (by date string, sorted)
    summary_list = sorted(summary_list, key=lambda s: s["date"])[-30:]

    with open(summary_path, "w") as f:
        json.dump(summary_list, f, indent=2)
    print(f"      ✓ history/daily_summary.json updated ({len(summary_list)} days)")

except Exception as e:
    print(f"      ⚠ History snapshot skipped (non-critical): {e}")

# ── 6. Stock/Inventory Report (fail-safe, separate from order data) ───────────
print("\n[6/6] Fetching inventory report...")
try:
    inv_payload = {"report_schedule": {
        "report_type_id": "36",
        "report_format": "xls",
        "report_occurrence_id": "5",
        "mailing_list": [""],
        "field_ids": [str(i) for i in range(1, 51)] + [str(i) for i in range(600, 650)] + ["1220","1221","1222"],
        "filters": {"company_id": ["2"]},
        "notification_type": "email"
    }}
    inv_cr = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=inv_payload, timeout=30)
    if inv_cr.status_code != 200:
        print(f"      ⚠ HTTP {inv_cr.status_code}: {inv_cr.text[:500]}")
    inv_cr.raise_for_status()
    inv_cd = inv_cr.json()
    if inv_cd.get("status_code") != 1000:
        print(f"      ⚠ Inventory report failed: {json.dumps(inv_cd, indent=2)}")
    else:
        inv_id = inv_cd["data"]["id"]
        print(f"      ✓ Inventory report created (ID: {inv_id})")

        # Poll
        inv_url = ""
        for i in range(1, 25):
            time.sleep(15)
            try:
                ich = requests.get(f"{BASE_URL}/api/v1/report_schedules/{inv_id}", headers=H, timeout=30)
                if not ich.text.strip():
                    print(f"      [{i:02d}/24] empty response, retrying...")
                    continue
                iat = ich.json().get("data", {}).get("attributes", {})
                istatus = iat.get("status", "")
                iurl = iat.get("report_url", "")
                print(f"      [{i:02d}/24] status={istatus}")
                if iurl:
                    inv_url = iurl; print("      ✓ Inventory report ready!"); break
            except Exception as e:
                print(f"      [{i:02d}/24] poll error: {e}, retrying...")
                continue

        if inv_url:
            inv_resp = requests.get(inv_url, timeout=120)
            inv_resp.raise_for_status()
            with open("data/inventory.xlsx", "wb") as f:
                f.write(inv_resp.content)
            print(f"      ✓ data/inventory.xlsx saved ({len(inv_resp.content):,} bytes)")

            # Update daily_summary.json with total_atp for today (fail-safe)
            try:
                import openpyxl
                wb_inv = openpyxl.load_workbook(io.BytesIO(inv_resp.content), read_only=True, data_only=True)
                ws_inv = wb_inv.active
                total_atp = 0
                sku_count = 0
                for idx, row in enumerate(ws_inv.iter_rows(values_only=True)):
                    if idx == 0:
                        continue  # header
                    try:
                        atp_val = row[8]  # ATP column (0-indexed: col 9)
                        total_atp += int(atp_val) if atp_val not in (None, "") else 0
                        sku_count += 1
                    except (ValueError, IndexError, TypeError):
                        pass

                summary_path = "data/history/daily_summary.json"
                if os.path.exists(summary_path):
                    with open(summary_path) as f:
                        summary_list = json.load(f)
                    for s in summary_list:
                        if s.get("date") == TODAY:
                            s["total_atp"] = total_atp
                            s["sku_count"] = sku_count
                    with open(summary_path, "w") as f:
                        json.dump(summary_list, f, indent=2)
                    print(f"      ✓ daily_summary.json updated with total_atp={total_atp:,}")
            except Exception as e:
                print(f"      ⚠ ATP summary update skipped: {e}")

        else:
            print("      ⚠ Inventory report timeout, skipped")

except Exception as e:
    print(f"      ⚠ Inventory report skipped (non-critical): {e}")

# ── 7. Generic CSV report fetcher (for Picking & Packing line reports) ────────
def fetch_csv_report(report_type_id, name, save_path):
    """
    Fetch a CSV-format report (Picking/Packing line reports), fail-safe.
    Returns (rows, columns) or (None, None) on failure.
    """
    print(f"\n[7] Fetching {name} report (type_id={report_type_id})...")
    try:
        payload = {"report_schedule": {
            "report_type_id": report_type_id,
            "report_format": "csv",
            "report_occurrence_id": "5",
            "mailing_list": [""],
            "field_ids": [str(i) for i in range(1, 101)]
                        + [str(i) for i in range(600, 700)]
                        + [str(i) for i in range(1200, 1230)],
            "filters": {"company_id": ["2"]},
            "from_date": TODAY, "end_date": TODAY,
            "notification_type": "email", "carrier_code": []
        }}
        cr_ = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=payload, timeout=30)
        if cr_.status_code != 200:
            print(f"      ⚠ HTTP {cr_.status_code}: {cr_.text[:500]}")
        cr_.raise_for_status()
        cd_ = cr_.json()
        if cd_.get("status_code") != 1000:
            print(f"      ⚠ {name} report failed: {json.dumps(cd_, indent=2)[:500]}")
            return None, None
        rid = cd_["data"]["id"]
        print(f"      ✓ {name} report created (ID: {rid})")

        url_ = ""
        for i in range(1, 25):
            time.sleep(15)
            try:
                ch_ = requests.get(f"{BASE_URL}/api/v1/report_schedules/{rid}", headers=H, timeout=30)
                if not ch_.text.strip():
                    print(f"      [{i:02d}/24] empty response, retrying...")
                    continue
                at_ = ch_.json().get("data", {}).get("attributes", {})
                status_ = at_.get("status", "")
                u_ = at_.get("report_url", "")
                print(f"      [{i:02d}/24] status={status_}")
                if u_:
                    url_ = u_; print(f"      ✓ {name} report ready!"); break
            except Exception as e:
                print(f"      [{i:02d}/24] poll error: {e}, retrying...")
                continue

        if not url_:
            print(f"      ⚠ {name} report timeout, skipped")
            return None, None

        resp_ = requests.get(url_, timeout=120)
        resp_.raise_for_status()
        text_ = resp_.content.decode("utf-8-sig")
        reader_ = csv.DictReader(io.StringIO(text_))
        rows_ = list(reader_)
        cols_ = reader_.fieldnames or []
        print(f"      ✓ {len(rows_):,} rows · {len(cols_)} columns")
        print(f"      Columns: {cols_}")

        with open(save_path, "w", encoding="utf-8", newline="") as f:
            f.write(text_)
        print(f"      ✓ {save_path} saved")
        return rows_, cols_

    except Exception as e:
        print(f"      ⚠ {name} report skipped (non-critical): {e}")
        return None, None

# ── 8. Picking Line Report (type 14) ───────────────────────────────────────────
picking_rows, picking_cols = fetch_csv_report("14", "Picking Line", "data/picking.csv")

# ── 9. Packing Line Report (type 16) ───────────────────────────────────────────
packing_rows, packing_cols = fetch_csv_report("16", "Packing Line", "data/packing.csv")

# ── 10. Update daily_summary.json with warehouse KPIs (fail-safe) ─────────────
try:
    def _count_unique_orders(rws, cols_):
        if not rws:
            return 0, 0
        order_col = next((c for c in cols_ if "order" in c.lower() and "number" in c.lower()), None)
        qty_col = next((c for c in cols_ if "qty" in c.lower() or "quantity" in c.lower()), None)
        if not order_col:
            return 0, 0
        uniq = set()
        total_qty = 0
        for r in rws:
            on = (r.get(order_col) or "").strip()
            if on:
                uniq.add(on)
            if qty_col:
                try:
                    total_qty += int(float(r.get(qty_col) or 0))
                except (ValueError, TypeError):
                    pass
        return len(uniq), total_qty

    picked_orders, picked_qty = _count_unique_orders(picking_rows, picking_cols)
    packed_orders, packed_qty = _count_unique_orders(packing_rows, packing_cols)

    summary_path = "data/history/daily_summary.json"
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary_list = json.load(f)
        for s in summary_list:
            if s.get("date") == TODAY:
                s["picking_lines"] = len(picking_rows) if picking_rows else 0
                s["packing_lines"] = len(packing_rows) if packing_rows else 0
                s["picked_orders"] = picked_orders
                s["packed_orders"] = packed_orders
                total_o = s.get("total_orders") or 0
                s["picking_completion_pct"] = round(picked_orders/total_o*100,1) if total_o else 0
                s["packing_completion_pct"] = round(packed_orders/total_o*100,1) if total_o else 0
        with open(summary_path, "w") as f:
            json.dump(summary_list, f, indent=2)
        print(f"\n      ✓ daily_summary.json updated with warehouse KPIs "
              f"(picked_orders={picked_orders}, packed_orders={packed_orders})")
except Exception as e:
    print(f"      ⚠ Warehouse summary update skipped (non-critical): {e}")

print(f"\n=== DONE — {len(rows):,} rows · {len(cols)} columns · {TODAY} ===")
