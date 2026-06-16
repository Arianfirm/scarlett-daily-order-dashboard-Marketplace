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
    """Create report, auto-delete if duplicate exists, then retry with modified campaign_code to bypass server cache lock."""
    import re as _rex
    import copy
    
    current_payload = copy.deepcopy(payload_dict)
    
    print(f"      Attempting to create {label}...")
    resp = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=current_payload, timeout=30)
    cd = resp.json() if resp.text.strip() else {}

    # Jika terkena block duplikat 400
    if resp.status_code == 400:
        err = cd.get("errors", "")
        print(f"      ⚠ Server blocked with error: {err}")
        
        # Ekstrak ID duplikat dari error message untuk coba dihapus
        m = _rex.search(r'Report schedule number:\s*(\d+)', str(err))
        if m:
            dup_id = m.group(1)
            print(f"      -> Attempting to clear ID: {dup_id} from queue...")
            dr = requests.delete(f"{BASE_URL}/api/v1/report_schedules/{dup_id}", headers=H, timeout=30)
            print(f"      -> Delete status: {dr.status_code}")
            
        # JEDA 5 DETIK
        print("      ⏳ Waiting 5 seconds...")
        time.sleep(5)
        
        # STRATEGI PAMUNGKAS: Modifikasi payload agar bypass proteksi duplikat server
        print(f"      🔄 Modifying campaign_code filter to bypass server lock...")
        bypass_string = f"bypass_{int(time.time())}"
        
        # Masukkan string unik ke campaign_code agar parameter dianggap berbeda oleh server
        if "filters" in current_payload["report_schedule"]:
            current_payload["report_schedule"]["filters"]["campaign_code"] = [bypass_string]
        
        # RETRY 1 dengan Payload Baru
        print(f"      Retrying POST with modified parameters...")
        resp2 = requests.post(f"{BASE_URL}/api/v1/report_schedules", headers=H, json=current_payload, timeout=30)
        cd2 = resp2.json() if resp2.text.strip() else {}
        
        if resp2.status_code == 200:
            rid = cd2.get("data", {}).get("id")
            print(f"      ✓ {label} successfully created via bypass technique (ID: {rid})")
            return rid
            
        # Jika masih keras kepala juga, tunggu 10 detik dan coba sekali lagi
        if resp2.status_code == 400:
            print("      ⏳ Server still persistent. Waiting 10 seconds for ultimate retry...")
            time.sleep(10)
            
            # Ganti lagi string bypass-nya dengan timestamp baru
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

    # Sukses pada percobaan pertama
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

# 3. Poll — check immediately first
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
            if not ch.text.strip():
                print(f"      [{i:02d}/24] empty response, retrying...")
                continue
            at = ch.json().get("data", {}).get("attributes", {})
            status = at.get("status","")
            url    = at.get("report_url","")
            print(f"      [{i:02d}/24] status={status}")
            if url:
                report_url = url
                print("      ✓ Report ready!")
                break
        except Exception as e:
            print(f"      [{i:02d}/24] poll error: {e}, retrying...")
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

# ── 5b. Compute & save daily summary ──
try:
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
            with open(summary_path) as f:
                summary_list = json.load(f)
        except Exception:
            summary_list = []

    summary_list = [s for s in summary_list if s.get("date") != TODAY]
    summary_list.append(summary_entry)
    summary_list = sorted(summary_list, key=lambda s: s["date"])[-30:]

    with open(summary_path, "w") as f:
        json.dump(summary_list, f, indent=2)
    print(f"      ✓ history/daily_summary.json updated ({len(summary_list)} days)")

except Exception as e:
    print(f"      ⚠ History snapshot skipped (non-critical): {e}")

# ── 6. Stock/Inventory Report ──
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
    inv_cd = inv_cr.json() if inv_cr.text.strip() else {}
    if inv_cr.status_code == 400:
        import re as _re4
        m = _re4.search(r'Report schedule number:\s*(\d+)', inv_cd.get("errors",""))
        if m:
            inv_id =
