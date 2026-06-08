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
with open("data/orders.csv", "w", encoding="utf-8", newline="") as f:
    f.write(csv_text)
meta = {"date": TODAY, "last_updated": NOW,
        "run_at_hour": datetime.now(timezone.utc).hour,
        "total_rows": len(rows), "columns": cols}
with open("data/last_updated.json", "w") as f:
    json.dump(meta, f, indent=2)
print(f"      ✓ Saved\n\n=== DONE — {len(rows):,} rows · {len(cols)} columns · {TODAY} ===")
