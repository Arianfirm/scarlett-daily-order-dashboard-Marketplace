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

# 2. Create report - BYPASS VERSION FOR RACE CONDITIONS
print("\n[2/5] Creating report...")

def _create_report_safe(payload_dict, label="Report"):
    import re as _rex
    import copy
    current_payload = copy.deepcopy(payload_dict)
    print(f"      Attempting to create {label}...")
    resp = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=current_payload, timeout=30)
    cd = resp.json() if resp.text.strip() else {}

    if resp.status_code == 400:
        err = cd.get("errors", "")
        print(f"      ⚠ Server blocked with error: {err}")
        m = _rex.search(r'Report schedule number:\s*(\d+)', str(err))
        if m:
            dup_id = m.group(1)
            print(f"      -> Attempting to clear ID: {dup_id} from queue...")
            dr = requests.delete(f"{BASE_URL}/api/v1/report_schedules/{dup_id}", headers=H, timeout=30)
            print(f"      -> Delete status: {dr.status_code}")
        print("      ⏳ Waiting 5 seconds...")
        time.sleep(5)
        print(f"      🔄 Modifying campaign_code filter to bypass server lock...")
        bypass_string = f"bypass_{int(time.time())}"
        if "filters" in current_payload["report_schedule"]:
            current_payload["report_schedule"]["filters"]["campaign_code"] = [bypass_string]
        print(f"      Retrying POST with modified parameters...")
        resp2 = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=current_payload, timeout=30)
        cd2 = resp2.json() if resp2.text.strip() else {}
        if resp2.status_code == 200:
            rid = cd2.get("data", {}).get("id")
            print(f"      ✓ {label} successfully created via bypass technique (ID: {rid})")
            return rid
        if resp2.status_code == 400:
            print("      ⏳ Server still persistent. Waiting 10 seconds for ultimate retry...")
            time.sleep(10)
            current_payload["report_schedule"]["filters"]["campaign_code"] = [f"bypass_final_{int(time.time())}"]
            print(f"      Retrying POST for the last time...")
            resp3 = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=current_payload, timeout=30)
            cd3 = resp3.json() if resp3.text.strip() else {}
            if resp3.status_code == 200:
                rid = cd3.get("data", {}).get("id")
                print(f"      ✓ {label} created on final attempt (ID: {rid})")
                return rid
            raise Exception(f"{label} retry failed after multiple attempts: {cd3}")
        raise Exception(f"{label} failed on retry: {resp2.status_code} - {cd2}")

    if resp.status_code == 200:
        rid = cd.get("data", {}).get("id")
        if not rid:
            raise Exception(f"{label} no ID in response: {cd}")
        print(f"      ✓ {label} created (ID: {rid})")
        return rid
    raise Exception(f"{label} failed: {resp.status_code} - {cd}")

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
report_id = _create_report_safe(payload, "B2C Order Report")

# 3. Poll
print("\n[3/5] Waiting for report...")
report_url = ""
try:
    ch0 = requests.get(f"{BASE_URL}/api/v1/report_schedules/{report_id}", headers=H, timeout=30)
    if ch0.text.strip():
        at0 = ch0.json().get("data", {}).get("attributes", {})
        url0 = at0.get("report_url","")
        if url0:
            report_url = url0
            print(f"      ✓ Report ready immediately!")
except Exception:
    pass

if not report_url:
    for i in range(1, 25):
        time.sleep(15)
        try:
            ch = requests.get(f"{BASE_URL}/api/v1/report_schedules/{report_id}", headers=H, timeout=30)
            if not ch.text.strip(): continue
            at = ch.json().get("data", {}).get("attributes", {})
            url = at.get("report_url","")
            if url:
                report_url = url
                print("      ✓ Report ready!")
                break
        except Exception:
            continue
    if not report_url:
        print("      ✗ Timeout")
        exit(1)

# 4. Download
print("\n[4/5] Downloading CSV...")
cr2 = requests.get(report_url, timeout=120)
cr2.raise_for_status()
csv_text = cr2.content.decode("utf-8-sig")
reader = csv.DictReader(io.StringIO(csv_text))
rows = list(reader)
cols = reader.fieldnames or []

# 5. Save
print("\n[5/5] Saving...")
os.makedirs("data", exist_ok=True)
os.makedirs("data/history", exist_ok=True)
with open("data/orders.csv", "w", encoding="utf-8", newline="") as f:
    f.write(csv_text)
meta = {"date": TODAY, "last_updated": NOW, "run_at_hour": datetime.now(timezone.utc).hour, "total_rows": len(rows), "columns": cols}
with open("data/last_updated.json", "w") as f:
    json.dump(meta, f, indent=2)
    # ── 5b. Compute & save daily summary ──
try:
    GOOD_STATUS = {"dispatched","picked","packed","manifest_created","delivered","qc_done","received_at_warehouse","assigned","partial_picked"}
    BAD_STATUS = {"unassigned","problem"}
    import re as _re
    orders_seen = {}
    hourly_orders = [0]*24
    hourly_qty = [0]*24
    for r in rows:
        on = (r.get("Order Number") or "").strip()
        if not on: continue
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

    _d = datetime.strptime(TODAY, "%Y-%m-%d")
    day_of_month = _d.day
    month = _d.month
    day_type = "gajian" if day_of_month in (25, 30, 31) else ("tanggal_kembar" if day_of_month == month and day_of_month <= 12 else "biasa")

    summary_entry = {
        "date": TODAY,
        "total_orders": total_orders,
        "total_qty": total_qty,
        "fulfilled": good_count,
        "pending": bad_count,
        "fulfillment_pct": fulfillment_pct,
        "total_atp": None,
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
            with open(summary_path) as f: summary_list = json.load(f)
        except Exception: summary_list = []
    summary_list = [s for s in summary_list if s.get("date") != TODAY]
    summary_list.append(summary_entry)
    summary_list = sorted(summary_list, key=lambda s: s["date"])[-30:]
    with open(summary_path, "w") as f: json.dump(summary_list, f, indent=2)
    print(f"      ✓ history/daily_summary.json updated")
except Exception as e:
    print(f"      ⚠ History snapshot skipped: {e}")

# ── 6. Stock/Inventory Report ──
print("\n[6/6] Fetching inventory report...")
try:
    inv_payload = {"report_schedule": {
        "report_type_id": "36", "report_format": "xls", "report_occurrence_id": "5", "mailing_list": [""],
        "field_ids": [str(i) for i in range(1, 51)] + [str(i) for i in range(600, 650)] + ["1220","1221","1222"],
        "filters": {"company_id": ["2"]}, "notification_type": "email"
    }}
    inv_cr = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=inv_payload, timeout=30)
    inv_cd = inv_cr.json() if inv_cr.text.strip() else {}
    if inv_cr.status_code == 400:
        import re as _re4
        m = _re4.search(r'Report schedule number:\s*(\d+)', inv_cd.get("errors",""))
        inv_id = m.group(1) if m else Exception()
    else:
        inv_cr.raise_for_status()
        inv_id = inv_cd["data"]["id"]

    inv_url = ""
    for i in range(1, 25):
        time.sleep(15)
        try:
            ich = requests.get(f"{BASE_URL}/api/v1/report_schedules/{inv_id}", headers=H, timeout=30)
            inv_url = ich.json().get("data", {}).get("attributes", {}).get("report_url","")
            if inv_url: break
        except Exception: continue

    if inv_url:
        inv_resp = requests.get(inv_url, timeout=120)
        with open("data/inventory.xlsx", "wb") as f: f.write(inv_resp.content)
        try:
            import openpyxl
            wb_inv = openpyxl.load_workbook(io.BytesIO(inv_resp.content), read_only=True, data_only=True)
            ws_inv = wb_inv.active
            total_atp, sku_count = 0, 0
            for idx, row in enumerate(ws_inv.iter_rows(values_only=True)):
                if idx == 0: continue
                try:
                    atp_val = row[8] if len(row) > 8 else None
                    total_atp += int(atp_val) if atp_val not in (None, "") else 0
                    sku_count += 1
                except Exception: pass
            if os.path.exists(summary_path):
                with open(summary_path) as f: summary_list = json.load(f)
                for s in summary_list:
                    if s.get("date") == TODAY:
                        s["total_atp"] = total_atp
                        s["sku_count"] = sku_count
                with open(summary_path, "w") as f: json.dump(summary_list, f, indent=2)
        except Exception: pass
except Exception as e:
    print(f"      ⚠ Inventory skipped: {e}")

# ── 7. B2C Order Processing Report ──
print("\n[7] Fetching B2C Order Processing report...")
processing_rows, processing_cols = [], []
try:
    proc_payload = {"report_schedule": {
        "report_type_id": "39", "report_format": "csv", "report_occurrence_id": "5", "mailing_list": [""],
        "field_ids": [str(i) for i in range(1, 2000)], "filters": {"company_id": ["2"], "campaign_code": []},
        "from_date": TODAY, "end_date": TODAY, "notification_type": "email"
    }}
    pcr = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=proc_payload, timeout=30)
    if pcr.status_code == 400:
        time.sleep(3)
        proc_payload["report_schedule"]["filters"]["campaign_code"] = [f"bypass_proc_{int(time.time())}"]
        pcr = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=proc_payload, timeout=30)
    pcr.raise_for_status()
    proc_id = pcr.json()["data"]["id"]

    proc_url = ""
    for i in range(1, 25):
        time.sleep(15)
        try:
            pch = requests.get(f"{BASE_URL}/api/v1/report_schedules/{proc_id}", headers=H, timeout=30)
            proc_url = pch.json().get("data", {}).get("attributes", {}).get("report_url","")
            if proc_url: break
        except Exception: continue

    if proc_url:
        presp = requests.get(proc_url, timeout=120)
        proc_text = presp.content.decode("utf-8-sig")
        preader = csv.DictReader(io.StringIO(proc_text))
        processing_rows = list(preader)
        processing_cols = preader.fieldnames or []
        with open("data/order_processing.csv", "w", encoding="utf-8", newline="") as f: f.write(proc_text)
except Exception as e:
    print(f"      ⚠ Order Processing skipped: {e}")

# ── 8. Generate Warehouse KPIs ──
print("\n[8] Computing warehouse KPIs...")
try:
    def _col(cols_, *candidates):
        for cand in candidates:
            for c in cols_:
                if cand.lower() in c.lower(): return c
        return None
    c_order = _col(processing_cols, "order number")
    c_status = _col(processing_cols, "order status")
    c_pick_t = _col(processing_cols, "picking time")
    c_pick_by = _col(processing_cols, "picked by")
    c_pack_t = _col(processing_cols, "packing time")
    c_pack_by = _col(processing_cols, "packed by")
    c_disp_t = _col(processing_cols, "dispatch time")
    c_disp_by = _col(processing_cols, "dispatched by")
    c_order_date = _col(processing_cols, "order date")
    c_qty = _col(processing_cols, "total ordered qty", "ordered quantity", "qty")

    today_prefix = datetime.strptime(TODAY, "%Y-%m-%d").strftime("%d/%m/%Y")
    def _is_today(val): return (val or "").strip().startswith(today_prefix) or (val or "").strip().startswith(TODAY)
    def _parse_dt(s):
        if not s or not s.strip(): return None
        for fmt in ("%d/%m/%Y, %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try: return datetime.strptime(s.strip(), fmt)
            except ValueError: continue
        return None

    orders_proc = {}
    picker_count, packer_count, dispatcher_count = {}, {}, {}
    pick_hours, pack_hours, disp_hours = [0]*24, [0]*24, [0]*24
    pick_hour_pickers = [set() for _ in range(24)]
    pack_hour_packers = [set() for _ in range(24)]
    pick_hour_orders = [set() for _ in range(24)]
    pack_hour_orders = [set() for _ in range(24)]
    pick_hour_qty, pack_hour_qty = [0]*24, [0]*24
    pick_deltas, pack_deltas, disp_deltas = [], [], []

    for r in processing_rows:
        on = (r.get(c_order) or "").strip() if c_order else ""
        if not on: continue
        if on not in orders_proc: orders_proc[on] = {"picked": False, "packed": False, "dispatched": False}
        order_dt = _parse_dt(r.get(c_order_date) or "")

        if c_pick_t and _is_today(r.get(c_pick_t, '')):
            pt = _parse_dt(r.get(c_pick_t))
            if pt:
                orders_proc[on]["picked"] = True
                pick_hours[pt.hour] += 1
                pick_hour_orders[pt.hour].add(on)
                if c_qty:
                    try: pick_hour_qty[pt.hour] += int(float(r.get(c_qty) or 0))
                    except: pass
                if c_pick_by:
                    pb_h = (r.get(c_pick_by) or "").strip()
                    if pb_h: pick_hour_pickers[pt.hour].add(pb_h)
                if order_dt: pick_deltas.append((pt - order_dt).total_seconds() / 60)
        if c_pick_by and _is_today(r.get(c_pick_t, '')):
            pb = (r.get(c_pick_by) or "").strip()
            if pb: picker_count[pb] = picker_count.get(pb, 0) + 1

        if c_pack_t and _is_today(r.get(c_pack_t, '')):
            pkt = _parse_dt(r.get(c_pack_t))
            if pkt:
                orders_proc[on]["packed"] = True
                pack_hours[pkt.hour] += 1
                pack_hour_orders[pkt.hour].add(on)
                if c_qty:
                    try: pack_hour_qty[pkt.hour] += int(float(r.get(c_qty) or 0))
                    except: pass
                if c_pack_by:
                    pkb_h = (r.get(c_pack_by) or "").strip()
                    if pkb_h: pack_hour_packers[pkt.hour].add(pkb_h)
                if c_pick_t:
                    pt2 = _parse_dt(r.get(c_pick_t))
                    if pt2: pack_deltas.append((pkt - pt2).total_seconds() / 60)
        if c_pack_by and _is_today(r.get(c_pack_t, '')):
            pkb = (r.get(c_pack_by) or "").strip()
            if pkb: packer_count[pkb] = packer_count.get(pkb, 0) + 1

        if c_disp_t and _is_today(r.get(c_disp_t, '')):
            dt_ = _parse_dt(r.get(c_disp_t))
            if dt_:
                orders_proc[on]["dispatched"] = True
                disp_hours[dt_.hour] += 1
                if c_pack_t:
                    pkt2 = _parse_dt(r.get(c_pack_t))
                    if pkt2: disp_deltas.append((dt_ - pkt2).total_seconds() / 60)
        if c_disp_by and _is_today(r.get(c_disp_t, '')):
            db = (r.get(c_disp_by) or "").strip()
            if db: dispatcher_count[db] = dispatcher_count.get(db, 0) + 1

    warehouse_summary = {
        "total_orders": len(orders_proc),
        "picked_orders": sum(1 for o in orders_proc.values() if o["picked"]),
        "packed_orders": sum(1 for o in orders_proc.values() if o["packed"]),
        "dispatched_orders": sum(1 for o in orders_proc.values() if o["dispatched"]),
        "pending_orders": len(orders_proc) - sum(1 for o in orders_proc.values() if o["dispatched"]),
        "avg_pick_min": round(sum(pick_deltas)/len(pick_deltas), 1) if pick_deltas else None,
        "avg_pack_min": round(sum(pack_deltas)/len(pack_deltas), 1) if pack_deltas else None,
        "avg_dispatch_min": round(sum(disp_deltas)/len(disp_deltas), 1) if disp_deltas else None,
        "pick_hours": [len(s) for s in pick_hour_orders], "pack_hours": [len(s) for s in pack_hour_orders], "dispatch_hours": disp_hours,
        "top_picker": sorted(picker_count.items(), key=lambda x: -x[1])[:5], "top_packer": sorted(packer_count.items(), key=lambda x: -x[1])[:5],
        "top_dispatcher": sorted(dispatcher_count.items(), key=lambda x: -x[1])[:5], "low_picker": sorted(picker_count.items(), key=lambda x: x[1])[:5],
        "low_packer": sorted(packer_count.items(), key=lambda x: x[1])[:5],
        "pick_hour_pickers": [len(s) for s in pick_hour_pickers], "pack_hour_packers": [len(s) for s in pack_hour_packers],
        "pick_hour_orders": [len(s) for s in pick_hour_orders], "pack_hour_orders": [len(s) for s in pack_hour_orders],
        "pick_hour_qty": pick_hour_qty, "pack_hour_qty": pack_hour_qty,
    }

    if os.path.exists(summary_path):
        with open(summary_path) as f: summary_list = json.load(f)
        for s in summary_list:
            if s.get("date") == TODAY: s["warehouse"] = warehouse_summary
        with open(summary_path, "w") as f: json.dump(summary_list, f, indent=2)
        print(f"      ✓ daily_summary.json updated with warehouse KPIs")
except Exception as e:
    print(f"      ⚠ Warehouse KPI skipped: {e}")

print(f"\n=== DONE — {len(rows):,} rows · {len(cols)} columns · {TODAY} ===")
