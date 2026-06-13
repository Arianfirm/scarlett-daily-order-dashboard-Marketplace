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

# ── 5b. Save snapshot to history (7-day retention) ─────────────────────────
# Fail-safe: kalau bagian ini error, tidak mengganggu update dashboard utama
try:
    from datetime import timedelta

    # Simpan snapshot hari ini (selalu overwrite — snapshot terbaru di hari itu)
    hist_path = f"data/history/{TODAY}.csv"
    with open(hist_path, "w", encoding="utf-8", newline="") as f:
        f.write(csv_text)
    print(f"      ✓ history/{TODAY}.csv saved")

    # Hapus history lebih dari 7 hari
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=7)
    removed = []
    for fname in os.listdir("data/history"):
        if fname.endswith(".csv"):
            try:
                fdate = datetime.strptime(fname[:-4], "%Y-%m-%d").date()
                if fdate < cutoff:
                    os.remove(os.path.join("data/history", fname))
                    removed.append(fname)
            except ValueError:
                pass  # skip file dengan nama tidak sesuai format tanggal

    if removed:
        print(f"      ✓ Removed old history: {removed}")

    # Update index list untuk dashboard (tanggal yang tersedia)
    available = sorted([f[:-4] for f in os.listdir("data/history") if f.endswith(".csv")])
    with open("data/history/index.json", "w") as f:
        json.dump({"available_dates": available}, f, indent=2)
    print(f"      ✓ history/index.json saved ({len(available)} dates)")

    # ── Compute & save daily summary (lightweight, for trend charts) ───────
    GOOD_STATUS = {"dispatched","picked","packed","manifest_created","delivered",
                    "qc_done","received_at_warehouse","assigned","partial_picked"}
    BAD_STATUS = {"unassigned","problem"}

    orders_seen = {}
    for r in rows:
        on = (r.get("Order Number") or "").strip()
        if not on:
            continue
        st = (r.get("Order Status") or "").strip().lower().replace(" ", "_")
        qty = int(r.get("Ordered Quantity") or 0)
        if on not in orders_seen:
            orders_seen[on] = {"st": st, "qty": 0}
        orders_seen[on]["qty"] += qty

    total_orders = len(orders_seen)
    total_qty = sum(o["qty"] for o in orders_seen.values())
    good_count = sum(1 for o in orders_seen.values() if o["st"] in GOOD_STATUS)
    bad_count = sum(1 for o in orders_seen.values() if o["st"] in BAD_STATUS)
    fulfillment_pct = round(good_count / total_orders * 100, 1) if total_orders else 0

    summary_entry = {
        "date": TODAY,
        "total_orders": total_orders,
        "total_qty": total_qty,
        "fulfilled": good_count,
        "pending": bad_count,
        "fulfillment_pct": fulfillment_pct,
        "total_atp": None,  # filled later if inventory report succeeds
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
    summary_list = sorted(summary_list, key=lambda s: s["date"])[-7:]

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

            # Save snapshot to history (7-day retention, fail-safe)
            try:
                os.makedirs("data/history/inventory", exist_ok=True)
                inv_hist_path = f"data/history/inventory/{TODAY}.xlsx"
                with open(inv_hist_path, "wb") as f:
                    f.write(inv_resp.content)
                print(f"      ✓ history/inventory/{TODAY}.xlsx saved")

                from datetime import timedelta
                cutoff = datetime.now(timezone.utc).date() - timedelta(days=7)
                removed = []
                for fname in os.listdir("data/history/inventory"):
                    if fname.endswith(".xlsx"):
                        try:
                            fdate = datetime.strptime(fname[:-5], "%Y-%m-%d").date()
                            if fdate < cutoff:
                                os.remove(os.path.join("data/history/inventory", fname))
                                removed.append(fname)
                        except ValueError:
                            pass
                if removed:
                    print(f"      ✓ Removed old inventory history: {removed}")

                # Update daily_summary.json with total_atp for today
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

            except Exception as e:
                print(f"      ⚠ Inventory history snapshot skipped (non-critical): {e}")
        else:
            print("      ⚠ Inventory report timeout, skipped")

except Exception as e:
    print(f"      ⚠ Inventory report skipped (non-critical): {e}")

print(f"\n=== DONE — {len(rows):,} rows · {len(cols)} columns · {TODAY} ===")
