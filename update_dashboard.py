import os, requests, json, time, csv, io
from datetime import datetime, timezone
from collections import Counter

EMAIL    = os.getenv("ACHANTO_EMAIL")
PASSWORD = os.getenv("ACHANTO_PASSWORD")
BASE_URL = "https://wms-api.anchanto.com"
TODAY    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
TODAY_ACHANTO = datetime.now(timezone.utc).strftime("%a %b %-d %Y")  # "Wed Jun 17 2026"
NOW      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
RUN_HOUR = datetime.now(timezone.utc).hour

print(f"=== Scarlett Dashboard Updater ===")
print(f"Run time : {NOW}")
print(f"Fetching : {TODAY} 00:00 → 23:59")

# ── 1. Login ──────────────────────────────────────────────────────────────────
print("\n[1] Login...")
r = requests.post(f"{BASE_URL}/api/login",
    json={"api_user": {"email": EMAIL, "password": PASSWORD}}, timeout=30)
r.raise_for_status()
jwt = r.json()["jwt"]
print("      ✓ Login success")
H = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}

# ── Helper: poll until report_url is ready ────────────────────────────────────
def _poll_report(report_id, label, retries=40, interval=15):
    """Poll GET /report_schedules/{id} until report_url appears."""
    for i in range(retries):
        time.sleep(interval)
        try:
            ch = requests.get(f"{BASE_URL}/api/v1/report_schedules/{report_id}",
                              headers=H, timeout=30)
            if not ch.text.strip():
                print(f"      [{i+1:02d}/{retries}] empty response, retrying...")
                continue
            attrs = ch.json().get("data", {}).get("attributes", {})
            status = attrs.get("status", "")
            url    = attrs.get("report_url", "")
            print(f"      [{i+1:02d}/{retries}] status={status}")
            if url:
                print(f"      ✓ {label} ready!")
                return url
        except Exception as e:
            print(f"      [{i+1:02d}/{retries}] poll error: {e}, retrying...")
    return None

# ── Helper: create or recover report, validate date ───────────────────────────
def _create_report_safe(payload_dict, label="Report"):
    """
    POST to create a report schedule.
    If 400 'already exists': GET list, find match by BOTH report_type_id AND from_date/end_date.
    Returns internal schedule id (integer-like string, e.g. '17693').
    Never returns a schedule from a different date.
    """
    resp = requests.post(f"{BASE_URL}/api/v1/report_schedules",
                         headers=H, json=payload_dict, timeout=30)
    cd = resp.json() if resp.text.strip() else {}

    # ── Success path ──────────────────────────────────────────────────────────
    if resp.status_code == 200:
        if cd.get("status_code") != 1000:
            raise Exception(f"{label} create failed: {cd}")
        rid = cd["data"]["id"]
        print(f"      ✓ {label} created (ID: {rid})")
        return rid

    # ── Duplicate path ────────────────────────────────────────────────────────
    err = cd.get("errors", "")
    if resp.status_code == 400 and "already exists" in err.lower():
        print(f"      ⚠ {label} duplicate: {err}")

        # Achanto returns schedule NUMBER (not internal id) in error message.
        # Use GET /report_schedules/{number} to fetch the internal id, then poll normally.
        import re as _re_dup
        m = _re_dup.search(r'schedule number[:\s]+(\d+)', err, _re_dup.IGNORECASE)
        if not m:
            raise Exception(f"{label} duplicate but could not parse schedule number from: {err}")

        sched_number = m.group(1)
        print(f"      → Fetching existing schedule number={sched_number}...")
        get_resp = requests.get(
            f"{BASE_URL}/api/v1/report_schedules/{sched_number}",
            headers=H, timeout=30)
        print(f"      GET status={get_resp.status_code} body={get_resp.text[:200]}")

        if get_resp.status_code == 200 and get_resp.text.strip():
            gd = get_resp.json()
            internal_id = gd.get("data", {}).get("id")
            if internal_id:
                attrs = gd.get("data", {}).get("attributes", {})
                print(f"      ✓ Reusing internal id={internal_id} "
                      f"status={attrs.get('status')} file={attrs.get('filename','')}")
                return internal_id

        # GET failed or no internal id — cannot proceed
        raise Exception(
            f"{label} duplicate: could not resolve internal id from schedule number={sched_number}. "
            f"GET status={get_resp.status_code} body={get_resp.text[:200]}")

    raise Exception(f"{label} POST failed {resp.status_code}: {err or cd}")


# ── 2. B2C Order Report (type_id=3) ──────────────────────────────────────────
print("\n[2] Creating B2C Order report (type_id=3)...")
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
    "from_date": TODAY_ACHANTO, "end_date": TODAY_ACHANTO,
    "notification_type": "email", "carrier_code": []
}}
report_id = _create_report_safe(payload, "B2C Order Report")

# ── 3. Poll B2C report ────────────────────────────────────────────────────────
print("\n[3] Waiting for B2C Order report...")
report_url = ""
# Check immediately first (already-completed reused reports are ready instantly)
try:
    ch0 = requests.get(f"{BASE_URL}/api/v1/report_schedules/{report_id}",
                       headers=H, timeout=30)
    if ch0.text.strip():
        url0 = ch0.json().get("data", {}).get("attributes", {}).get("report_url", "")
        if url0:
            report_url = url0
            print(f"      ✓ Report ready immediately!")
except Exception:
    pass

if not report_url:
    report_url = _poll_report(report_id, "B2C Order report")

if not report_url:
    print("      ✗ B2C Order report timeout after polling"); exit(1)

# ── 4. Download B2C CSV ───────────────────────────────────────────────────────
print("\n[4] Downloading B2C Order CSV...")
cr2 = requests.get(report_url, timeout=120)
cr2.raise_for_status()
csv_text = cr2.content.decode("utf-8-sig")
reader = csv.DictReader(io.StringIO(csv_text))
rows = list(reader)
cols = reader.fieldnames or []
print(f"      ✓ {len(rows):,} rows · {len(cols)} columns")
print(f"      Columns: {cols}")

# ── Permanent debug: Order Date range audit ───────────────────────────────────
print(f"\n      === ORDER DATE RANGE AUDIT (run hour UTC={RUN_HOUR:02d}) ===")
try:
    _order_dates = []
    _hour_counts = Counter()
    _od_col = next((c for c in cols if c.strip().lower() in
                    ("order date", "orderdate", "order_date")), None)
    if _od_col:
        for _r in rows:
            _s = (_r.get(_od_col) or "").strip()
            for _fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    _d = datetime.strptime(_s, _fmt)
                    _order_dates.append(_d)
                    _hour_counts[_d.hour] += 1
                    break
                except: pass
    if _order_dates:
        _order_dates.sort()
        _min_d = _order_dates[0]
        _max_d = _order_dates[-1]
        print(f"      FIRST ORDER DATE  = {_min_d}")
        print(f"      LAST  ORDER DATE  = {_max_d}")
        print(f"      LATEST ORDER HOUR = {_max_d.hour:02d}:xx UTC")
        print(f"      ORDERS PER HOUR:")
        for _h in range(24):
            if _hour_counts[_h]:
                print(f"        {_h:02d}:00 → {_hour_counts[_h]:,}")
        _stale = _max_d.hour < RUN_HOUR - 2
        if _stale:
            print(f"      ⚠ STALE SNAPSHOT: max_hour={_max_d.hour:02d} run_hour={RUN_HOUR:02d} → reused old file")
        else:
            print(f"      ✓ FRESH: max_hour={_max_d.hour:02d} matches run_hour={RUN_HOUR:02d}")
    else:
        print(f"      ⚠ Could not parse any Order Dates (col={_od_col!r})")
except Exception as _e:
    print(f"      ⚠ Date audit failed: {_e}")
print(f"      === END AUDIT ===\n")

# ── 5. Save B2C data ──────────────────────────────────────────────────────────
print("\n[5] Saving...")
os.makedirs("data", exist_ok=True)
os.makedirs("data/history", exist_ok=True)

with open("data/orders.csv", "w", encoding="utf-8", newline="") as f:
    f.write(csv_text)

total_b2c_orders = len(rows)   # denominator for Warehouse KPI %

meta = {"date": TODAY, "last_updated": NOW,
        "run_at_hour": RUN_HOUR,
        "total_rows": len(rows), "columns": cols}
with open("data/last_updated.json", "w") as f:
    json.dump(meta, f, indent=2)
print(f"      ✓ orders.csv & last_updated.json saved")

# ── 5b. Daily summary snapshot ────────────────────────────────────────────────
try:
    import re as _re
    GOOD_STATUS = {"dispatched","picked","packed","manifest_created","delivered",
                   "qc_done","received_at_warehouse","assigned","partial_picked"}
    BAD_STATUS  = {"unassigned","problem"}

    orders_seen  = {}
    hourly_orders = [0]*24
    hourly_qty    = [0]*24
    for r in rows:
        on  = (r.get("Order Number") or "").strip()
        if not on: continue
        st  = (r.get("Order Status") or "").strip().lower().replace(" ", "_")
        qty = int(r.get("Ordered Quantity") or 0)
        if on not in orders_seen:
            od_str = r.get("Order Date") or ""
            hm = _re.search(r",\s*(\d{2}):|(\d{2}):(\d{2})$", od_str)
            hr = int((hm.group(1) or hm.group(2)) if hm else 0)
            orders_seen[on] = {"st": st, "qty": 0, "hr": hr}
            hourly_orders[hr] += 1
        orders_seen[on]["qty"] += qty
        hourly_qty[orders_seen[on]["hr"]] += qty

    total_o  = len(orders_seen)
    total_q  = sum(o["qty"] for o in orders_seen.values())
    good_cnt = sum(1 for o in orders_seen.values() if o["st"] in GOOD_STATUS)
    bad_cnt  = sum(1 for o in orders_seen.values() if o["st"] in BAD_STATUS)
    ful_pct  = round(good_cnt / total_o * 100, 1) if total_o else 0
    peak_h   = hourly_orders.index(max(hourly_orders)) if total_o else None

    _d2         = datetime.strptime(TODAY, "%Y-%m-%d")
    dom, mon    = _d2.day, _d2.month
    day_type    = ("gajian" if dom in (25,30,31)
                   else "tanggal_kembar" if dom==mon and dom<=12
                   else "biasa")

    summary_entry = {
        "date": TODAY, "total_orders": total_o, "total_qty": total_q,
        "fulfilled": good_cnt, "pending": bad_cnt, "fulfillment_pct": ful_pct,
        "total_atp": None, "peak_hour": peak_h,
        "peak_hour_orders": hourly_orders[peak_h] if peak_h is not None else 0,
        "peak_hour_qty":    hourly_qty[peak_h]    if peak_h is not None else 0,
        "hourly_orders": hourly_orders, "hourly_qty": hourly_qty,
        "day_type": day_type, "last_updated": NOW
    }

    spath = "data/history/daily_summary.json"
    summary_list = []
    if os.path.exists(spath):
        try:
            with open(spath) as f: summary_list = json.load(f)
        except: pass
    summary_list = [s for s in summary_list if s.get("date") != TODAY]
    summary_list.append(summary_entry)
    summary_list = sorted(summary_list, key=lambda s: s["date"])[-30:]
    with open(spath, "w") as f: json.dump(summary_list, f, indent=2)
    print(f"      ✓ daily_summary.json updated ({len(summary_list)} days)")

except Exception as e:
    print(f"      ⚠ History snapshot skipped (non-critical): {e}")

# ── 6. Inventory Report (type_id=36) ─────────────────────────────────────────
print("\n[6] Fetching Inventory report (type_id=36)...")
try:
    inv_payload = {"report_schedule": {
        "report_type_id": "36", "report_format": "xls",
        "report_occurrence_id": "5", "mailing_list": [""],
        "field_ids": ([str(i) for i in range(1, 51)] +
                      [str(i) for i in range(600, 650)] +
                      ["1220","1221","1222"]),
        "filters": {"company_id": ["2"]},
        "notification_type": "email"
    }}
    inv_id  = _create_report_safe(inv_payload, "Inventory Report")
    inv_url = _poll_report(inv_id, "Inventory report")

    if inv_url:
        inv_resp = requests.get(inv_url, timeout=120)
        inv_resp.raise_for_status()
        with open("data/inventory.xlsx", "wb") as f:
            f.write(inv_resp.content)
        print(f"      ✓ data/inventory.xlsx saved ({len(inv_resp.content):,} bytes)")

        try:
            import openpyxl
            wb  = openpyxl.load_workbook(io.BytesIO(inv_resp.content),
                                         read_only=True, data_only=True)
            ws  = wb.active
            total_atp, sku_count = 0, 0
            for idx, row in enumerate(ws.iter_rows(values_only=True)):
                if idx == 0: continue
                try:
                    v = row[8]
                    total_atp += int(v) if v not in (None,"") else 0
                    sku_count += 1
                except: pass
            spath = "data/history/daily_summary.json"
            if os.path.exists(spath):
                with open(spath) as f: sl = json.load(f)
                for s in sl:
                    if s.get("date") == TODAY:
                        s["total_atp"] = total_atp
                        s["sku_count"]  = sku_count
                with open(spath, "w") as f: json.dump(sl, f, indent=2)
            print(f"      ✓ daily_summary.json updated with total_atp={total_atp:,}")
        except Exception as e:
            print(f"      ⚠ ATP update skipped: {e}")
    else:
        print("      ⚠ Inventory timeout, skipped")
except Exception as e:
    print(f"      ⚠ Inventory report skipped (non-critical): {e}")

# ── 7. Order Processing Report (type_id=39) ──────────────────────────────────
print("\n[7] Fetching Order Processing report (type_id=39)...")
processing_rows, processing_cols = [], []
try:
    proc_payload = {"report_schedule": {
        "report_type_id": "39", "report_format": "csv",
        "report_occurrence_id": "5", "mailing_list": [""],
        "field_ids": [str(i) for i in range(1, 2000)],
        "filters": {"company_id": ["2"]},
        "from_date": TODAY_ACHANTO, "end_date": TODAY_ACHANTO,
        "notification_type": "email"
    }}
    proc_id  = _create_report_safe(proc_payload, "Order Processing Report")
    proc_url = _poll_report(proc_id, "Order Processing report")

    if proc_url:
        pr = requests.get(proc_url, timeout=120)
        pr.raise_for_status()
        ptxt   = pr.content.decode("utf-8-sig")
        preader = csv.DictReader(io.StringIO(ptxt))
        processing_rows = list(preader)
        processing_cols = preader.fieldnames or []
        print(f"      ✓ {len(processing_rows):,} rows · {len(processing_cols)} cols")
        with open("data/order_processing.csv", "w", encoding="utf-8", newline="") as f:
            f.write(ptxt)
    else:
        print("      ⚠ Order Processing timeout, warehouse KPI will be empty")

except Exception as e:
    print(f"      ⚠ Order Processing skipped (non-critical): {e}")

# ── 8. Compute Warehouse KPIs ─────────────────────────────────────────────────
print("\n[8] Computing Warehouse KPIs...")
try:
    if not processing_rows:
        raise Exception("No processing rows — skipping KPI")

    def _col(headers, *candidates):
        hl = [h.strip().lower() for h in headers]
        for c in candidates:
            if c.lower() in hl:
                return headers[hl.index(c.lower())]
        return None

    c_order      = _col(processing_cols, "order number", "order no", "ordernumber")
    c_status     = _col(processing_cols, "order status", "status")
    c_order_date = _col(processing_cols, "order date")
    c_pick_t     = _col(processing_cols, "picking time", "pick time", "order picking time")
    c_pick_by    = _col(processing_cols, "picked by", "picker")
    c_pack_t     = _col(processing_cols, "packing time", "pack time", "order packing time")
    c_pack_by    = _col(processing_cols, "packed by", "packer")
    c_disp_t     = _col(processing_cols, "dispatch time", "dispatched time", "dispatched at")
    c_disp_by    = _col(processing_cols, "dispatched by", "dispatcher")
    c_qty        = _col(processing_cols, "total ordered qty", "ordered quantity", "qty")

    print(f"      Columns: order={c_order!r} pick_t={c_pick_t!r} pack_t={c_pack_t!r} disp_t={c_disp_t!r} qty={c_qty!r}")

    today_prefix = datetime.strptime(TODAY, "%Y-%m-%d").strftime("%d/%m/%Y")
    def _is_today(val):
        v = (val or "").strip()
        return v.startswith(today_prefix) or v.startswith(TODAY)

    def _parse_dt(s):
        if not s or not s.strip(): return None
        for fmt in ("%d/%m/%Y, %H:%M:%S", "%d/%m/%Y %H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%d/%m/%Y, %H:%M", "%d/%m/%Y %H:%M"):
            try: return datetime.strptime(s.strip(), fmt)
            except: pass
        return None

    orders_proc  = {}
    picker_count, packer_count, dispatcher_count = {}, {}, {}
    pick_hours, pack_hours, disp_hours = [0]*24, [0]*24, [0]*24
    pick_hour_pickers = [set() for _ in range(24)]
    pack_hour_packers = [set() for _ in range(24)]
    pick_hour_orders  = [set() for _ in range(24)]
    pack_hour_orders  = [set() for _ in range(24)]
    pick_hour_qty     = [0]*24
    pack_hour_qty     = [0]*24
    pick_deltas, pack_deltas, disp_deltas = [], [], []

    for r in processing_rows:
        on = (r.get(c_order) or "").strip() if c_order else ""
        if not on: continue
        if on not in orders_proc:
            orders_proc[on] = {"picked": False, "packed": False, "dispatched": False}
        order_dt = _parse_dt(r.get(c_order_date) or "") if c_order_date else None

        if c_pick_t and _is_today(r.get(c_pick_t, "")):
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
                    if pb_h: pick_hour_pickers[pt.hour].add(pb_h)
                if order_dt: pick_deltas.append((pt - order_dt).total_seconds() / 60)
        if c_pick_by and _is_today(r.get(c_pick_t, "")):
            pb = (r.get(c_pick_by) or "").strip()
            if pb: picker_count[pb] = picker_count.get(pb, 0) + 1

        if c_pack_t and _is_today(r.get(c_pack_t, "")):
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
                    if pkb_h: pack_hour_packers[pkt.hour].add(pkb_h)
                if c_pick_t:
                    pt2 = _parse_dt(r.get(c_pick_t) or "")
                    if pt2: pack_deltas.append((pkt - pt2).total_seconds() / 60)
        if c_pack_by and _is_today(r.get(c_pack_t, "")):
            pkb = (r.get(c_pack_by) or "").strip()
            if pkb: packer_count[pkb] = packer_count.get(pkb, 0) + 1

        if c_disp_t and _is_today(r.get(c_disp_t, "")):
            dt_ = _parse_dt(r.get(c_disp_t) or "")
            if dt_:
                orders_proc[on]["dispatched"] = True
                disp_hours[dt_.hour] += 1
                if c_pack_t:
                    pkt2 = _parse_dt(r.get(c_pack_t) or "")
                    if pkt2: disp_deltas.append((dt_ - pkt2).total_seconds() / 60)
        if c_disp_by and _is_today(r.get(c_disp_t, "")):
            db = (r.get(c_disp_by) or "").strip()
            if db: dispatcher_count[db] = dispatcher_count.get(db, 0) + 1

    total_proc_orders  = len(orders_proc)
    picked_orders      = sum(1 for o in orders_proc.values() if o["picked"])
    packed_orders      = sum(1 for o in orders_proc.values() if o["packed"])
    dispatched_orders  = sum(1 for o in orders_proc.values() if o["dispatched"])
    pending_orders     = total_proc_orders - dispatched_orders

    avg_pick_min = round(sum(pick_deltas)/len(pick_deltas), 1) if pick_deltas else None
    avg_pack_min = round(sum(pack_deltas)/len(pack_deltas), 1) if pack_deltas else None
    avg_disp_min = round(sum(disp_deltas)/len(disp_deltas), 1) if disp_deltas else None

    top_picker     = sorted(picker_count.items(),     key=lambda x: -x[1])[:5]
    top_packer     = sorted(packer_count.items(),     key=lambda x: -x[1])[:5]
    top_dispatcher = sorted(dispatcher_count.items(), key=lambda x: -x[1])[:5]
    low_picker     = sorted(picker_count.items(),     key=lambda x:  x[1])[:5]
    low_packer     = sorted(packer_count.items(),     key=lambda x:  x[1])[:5]

    ph_picker_cnt = [len(s) for s in pick_hour_pickers]
    ph_packer_cnt = [len(s) for s in pack_hour_packers]
    ph_ord_pick   = [len(s) for s in pick_hour_orders]
    ph_ord_pack   = [len(s) for s in pack_hour_orders]

    warehouse_summary = {
        "total_orders":     total_proc_orders,
        "total_orders_b2c": total_b2c_orders,   # ← denominator for KPI %
        "picked_orders":    picked_orders,
        "packed_orders":    packed_orders,
        "dispatched_orders": dispatched_orders,
        "pending_orders":   pending_orders,
        "avg_pick_min":     avg_pick_min,
        "avg_pack_min":     avg_pack_min,
        "avg_dispatch_min": avg_disp_min,
        "pick_hours":       ph_ord_pick,
        "pack_hours":       ph_ord_pack,
        "dispatch_hours":   disp_hours,
        "top_picker":       top_picker,
        "top_packer":       top_packer,
        "top_dispatcher":   top_dispatcher,
        "low_picker":       low_picker,
        "low_packer":       low_packer,
        "pick_hour_pickers": ph_picker_cnt,
        "pack_hour_packers": ph_packer_cnt,
        "pick_hour_orders":  ph_ord_pick,
        "pack_hour_orders":  ph_ord_pack,
        "pick_hour_qty":     pick_hour_qty,
        "pack_hour_qty":     pack_hour_qty,
    }

    spath = "data/history/daily_summary.json"
    sl = []
    if os.path.exists(spath):
        try:
            with open(spath) as f: sl = json.load(f)
        except: pass
    for s in sl:
        if s.get("date") == TODAY:
            s["warehouse"] = warehouse_summary
    with open(spath, "w") as f: json.dump(sl, f, indent=2)
    print(f"      ✓ Warehouse KPI saved: picked={picked_orders}/{total_b2c_orders} "
          f"packed={packed_orders} dispatched={dispatched_orders} pending={pending_orders}")

except Exception as e:
    print(f"      ⚠ Warehouse KPI skipped (non-critical): {e}")

print(f"\n=== DONE — {len(rows):,} B2C rows · {TODAY} · UTC {RUN_HOUR:02d}:xx ===")
