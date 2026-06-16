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
if cr.status_code != 200:
    print(f"      ✗ HTTP {cr.status_code}")
    print(f"      Response text : {cr.text[:2000]}")
    try:
        print(f"      Response JSON : {json.dumps(cr.json(), indent=2)}")
    except Exception:
        print(f"      Response JSON : (not parseable)")
    print(f"      Payload sent  : {json.dumps(payload, indent=2)}")
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

# ── 7. B2C Order Processing Report (type 39) ───────────────────────────────────
# Sumber utama untuk Warehouse Operations Dashboard.
# Kolom yang tersedia: Order Number, Order Status, Order Date, Product Name, SKU,
# Total Ordered Qty, Picking Time, Picked By, Packing Time, Packed By,
# Dispatch Time, Dispatched By, Completed At, Location, Packaging Material
print("\n[7] Fetching B2C Order Processing report (type_id=39)...")
processing_rows, processing_cols = [], []
try:
    proc_payload = {"report_schedule": {
        "report_type_id": "39",
        "report_format": "csv",
        "report_occurrence_id": "5",
        "mailing_list": [""],
        "field_ids": [str(i) for i in range(1, 2000)],
        "filters": {"company_id": ["2"]},
        "from_date": TODAY, "end_date": TODAY,
        "notification_type": "email"
    }}
    pcr = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=proc_payload, timeout=30)
    if pcr.status_code != 200:
        print(f"      ⚠ HTTP {pcr.status_code}: {pcr.text[:500]}")
    pcr.raise_for_status()
    pcd = pcr.json()
    if pcd.get("status_code") != 1000:
        print(f"      ⚠ Order Processing report failed: {json.dumps(pcd, indent=2)[:500]}")
    else:
        proc_id = pcd["data"]["id"]
        print(f"      ✓ Order Processing report created (ID: {proc_id})")

        proc_url = ""
        for i in range(1, 25):
            time.sleep(15)
            try:
                pch = requests.get(f"{BASE_URL}/api/v1/report_schedules/{proc_id}", headers=H, timeout=30)
                if not pch.text.strip():
                    print(f"      [{i:02d}/24] empty response, retrying...")
                    continue
                pat = pch.json().get("data", {}).get("attributes", {})
                pstatus = pat.get("status", "")
                purl = pat.get("report_url", "")
                print(f"      [{i:02d}/24] status={pstatus}")
                if purl:
                    proc_url = purl; print("      ✓ Order Processing report ready!"); break
            except Exception as e:
                print(f"      [{i:02d}/24] poll error: {e}, retrying...")
                continue

        if proc_url:
            presp = requests.get(proc_url, timeout=120)
            presp.raise_for_status()
            proc_text = presp.content.decode("utf-8-sig")
            preader = csv.DictReader(io.StringIO(proc_text))
            processing_rows = list(preader)
            processing_cols = preader.fieldnames or []
            print(f"      ✓ {len(processing_rows):,} rows · {len(processing_cols)} columns")
            print(f"      Columns: {processing_cols}")

            with open("data/order_processing.csv", "w", encoding="utf-8", newline="") as f:
                f.write(proc_text)
            print(f"      ✓ data/order_processing.csv saved")
        else:
            print("      ⚠ Order Processing report timeout, skipped")

except Exception as e:
    print(f"      ⚠ Order Processing report skipped (non-critical): {e}")

# ── 8. Generate Warehouse KPIs from Order Processing report → daily_summary.json
print("\n[8] Computing warehouse KPIs...")
try:
    def _col(cols_, *candidates):
        for cand in candidates:
            for c in cols_:
                if cand.lower() in c.lower():
                    return c
        return None

    c_order  = _col(processing_cols, "order number")
    c_status = _col(processing_cols, "order status")
    c_pick_t = _col(processing_cols, "picking time")
    c_pick_by= _col(processing_cols, "picked by")
    c_pack_t = _col(processing_cols, "packing time")
    c_pack_by= _col(processing_cols, "packed by")
    c_disp_t = _col(processing_cols, "dispatch time")
    c_disp_by= _col(processing_cols, "dispatched by")
    c_order_date = _col(processing_cols, "order date")
    c_qty = _col(processing_cols, "total ordered qty", "ordered quantity", "qty")
    c_coll = _col(processing_cols, "collection date")

    print(f"      Detected columns: order={c_order!r}, status={c_status!r}, order_date={c_order_date!r}, qty={c_qty!r}")
    print(f"      pick_time={c_pick_t!r}, picked_by={c_pick_by!r}")
    print(f"      pack_time={c_pack_t!r}, packed_by={c_pack_by!r}")
    print(f"      disp_time={c_disp_t!r}, dispatched_by={c_disp_by!r}")
    print(f"      collection_date={c_coll!r}")

    # Filter per-activity di dalam loop (bukan pre-filter baris)
    # karena 1 baris bisa punya Picking lama tapi Dispatch hari ini
    today_prefix = datetime.strptime(TODAY, "%Y-%m-%d").strftime("%d/%m/%Y")
    def _is_today(val):
        v = (val or "").strip()
        return v.startswith(today_prefix) or v.startswith(TODAY)

    print(f"      Filter per-activity: only counting times starting with {today_prefix}")

    import re as _re2
    def _parse_dt(s):
        """Coba parse beberapa format umum dd/mm/yyyy HH:MM:SS atau dengan koma"""
        if not s or not s.strip():
            return None
        s = s.strip()
        for fmt in ("%d/%m/%Y, %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y, %H:%M", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    orders_proc = {}
    picker_count, packer_count, dispatcher_count = {}, {}, {}
    pick_hours, pack_hours, disp_hours = [0]*24, [0]*24, [0]*24
    pick_hour_pickers = [set() for _ in range(24)]
    pack_hour_packers = [set() for _ in range(24)]
    pick_hour_orders = [set() for _ in range(24)]
    pack_hour_orders = [set() for _ in range(24)]
    pick_hour_qty = [0]*24
    pack_hour_qty = [0]*24
    pick_deltas, pack_deltas, disp_deltas = [], [], []

    for r in processing_rows:
        on = (r.get(c_order) or "").strip() if c_order else ""
        if not on:
            continue
        if on not in orders_proc:
            orders_proc[on] = {"picked": False, "packed": False, "dispatched": False}

        order_dt = _parse_dt(r.get(c_order_date) or "") if c_order_date else None

        if c_pick_t and _is_today(r.get(c_pick_t, '')):
            pt = _parse_dt(r.get(c_pick_t) or "")
            if pt:
                orders_proc[on]["picked"] = True
                pick_hours[pt.hour] += 1
                pick_hour_orders[pt.hour].add(on)
                if c_qty:
                    try: pick_hour_qty[pt.hour] += int(float(r.get(c_qty) or 0))
                    except: pass
                if c_pick_by:
                    pb_h = (r.get(c_pick_by) or "").strip()
                    if pb_h:
                        pick_hour_pickers[pt.hour].add(pb_h)
                if order_dt:
                    pick_deltas.append((pt - order_dt).total_seconds() / 60)
        if c_pick_by and _is_today(r.get(c_pick_t, '')):
            pb = (r.get(c_pick_by) or "").strip()
            if pb:
                picker_count[pb] = picker_count.get(pb, 0) + 1

        if c_pack_t and _is_today(r.get(c_pack_t, '')):
            pkt = _parse_dt(r.get(c_pack_t) or "")
            if pkt:
                orders_proc[on]["packed"] = True
                pack_hours[pkt.hour] += 1
                pack_hour_orders[pkt.hour].add(on)
                if c_qty:
                    try: pack_hour_qty[pkt.hour] += int(float(r.get(c_qty) or 0))
                    except: pass
                if c_pack_by:
                    pkb_h = (r.get(c_pack_by) or "").strip()
                    if pkb_h:
                        pack_hour_packers[pkt.hour].add(pkb_h)
                if c_pick_t:
                    pt2 = _parse_dt(r.get(c_pick_t) or "")
                    if pt2:
                        pack_deltas.append((pkt - pt2).total_seconds() / 60)
        if c_pack_by and _is_today(r.get(c_pack_t, '')):
            pkb = (r.get(c_pack_by) or "").strip()
            if pkb:
                packer_count[pkb] = packer_count.get(pkb, 0) + 1

        if c_disp_t and _is_today(r.get(c_disp_t, '')):
            dt_ = _parse_dt(r.get(c_disp_t) or "")
            if dt_:
                orders_proc[on]["dispatched"] = True
                disp_hours[dt_.hour] += 1
                if c_pack_t:
                    pkt2 = _parse_dt(r.get(c_pack_t) or "")
                    if pkt2:
                        disp_deltas.append((dt_ - pkt2).total_seconds() / 60)
        if c_disp_by and _is_today(r.get(c_disp_t, '')):
            db = (r.get(c_disp_by) or "").strip()
            if db:
                dispatcher_count[db] = dispatcher_count.get(db, 0) + 1

    total_proc_orders = len(orders_proc)

    # Debug: min/max timestamps — only today's data from hour arrays
    today_pick = [h for h in range(24) if pick_hour_orders[h]]
    today_pack = [h for h in range(24) if pack_hour_orders[h]]
    today_disp = [h for h in range(24) if disp_hours[h]]
    print(f"      DEBUG Picking today  : active hours={today_pick}, total orders={sum(len(s) for s in pick_hour_orders)}")
    print(f"      DEBUG Packing today  : active hours={today_pack}, total orders={sum(len(s) for s in pack_hour_orders)}")
    print(f"      DEBUG Dispatch today : active hours={today_disp}, total dispatched={sum(disp_hours)}")
    picked_orders = sum(1 for o in orders_proc.values() if o["picked"])
    packed_orders = sum(1 for o in orders_proc.values() if o["packed"])
    dispatched_orders = sum(1 for o in orders_proc.values() if o["dispatched"])
    pending_orders = total_proc_orders - dispatched_orders

    avg_pick_min = round(sum(pick_deltas)/len(pick_deltas), 1) if pick_deltas else None
    avg_pack_min = round(sum(pack_deltas)/len(pack_deltas), 1) if pack_deltas else None
    avg_disp_min = round(sum(disp_deltas)/len(disp_deltas), 1) if disp_deltas else None

    top_picker = sorted(picker_count.items(), key=lambda x: -x[1])[:5]
    top_packer = sorted(packer_count.items(), key=lambda x: -x[1])[:5]
    top_dispatcher = sorted(dispatcher_count.items(), key=lambda x: -x[1])[:5]
    low_picker = sorted(picker_count.items(), key=lambda x: x[1])[:5]
    low_packer = sorted(packer_count.items(), key=lambda x: x[1])[:5]

    pick_hour_picker_counts = [len(s) for s in pick_hour_pickers]
    pack_hour_packer_counts = [len(s) for s in pack_hour_packers]
    pick_hour_order_counts  = [len(s) for s in pick_hour_orders]
    pack_hour_order_counts  = [len(s) for s in pack_hour_orders]

    warehouse_summary = {
        "total_orders": total_proc_orders,
        "picked_orders": picked_orders,
        "packed_orders": packed_orders,
        "dispatched_orders": dispatched_orders,
        "pending_orders": pending_orders,
        "avg_pick_min": avg_pick_min,
        "avg_pack_min": avg_pack_min,
        "avg_dispatch_min": avg_disp_min,
        "pick_hours": pick_hour_order_counts,
        "pack_hours": pack_hour_order_counts,
        "dispatch_hours": disp_hours,
        "top_picker": top_picker,
        "top_packer": top_packer,
        "top_dispatcher": top_dispatcher,
        "low_picker": low_picker,
        "low_packer": low_packer,
        "pick_hour_pickers": pick_hour_picker_counts,
        "pack_hour_packers": pack_hour_packer_counts,
        "pick_hour_orders": pick_hour_order_counts,
        "pack_hour_orders": pack_hour_order_counts,
        "pick_hour_qty": pick_hour_qty,
        "pack_hour_qty": pack_hour_qty,
    }

    summary_path = "data/history/daily_summary.json"
    summary_list = []
    if os.path.exists(summary_path):
        try:
            with open(summary_path) as f:
                summary_list = json.load(f)
        except Exception:
            summary_list = []
    for s in summary_list:
        if s.get("date") == TODAY:
            s["warehouse"] = warehouse_summary
    with open(summary_path, "w") as f:
        json.dump(summary_list, f, indent=2)
    print(f"      ✓ daily_summary.json updated with warehouse KPIs "
          f"(picked={picked_orders}, packed={packed_orders}, dispatched={dispatched_orders}, pending={pending_orders})")

except Exception as e:
    print(f"      ⚠ Warehouse KPI computation skipped (non-critical): {e}")

print(f"\n=== DONE — {len(rows):,} rows · {len(cols)} columns · {TODAY} ===")
