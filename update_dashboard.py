import os
import requests
import json
import time
import csv
import io
from datetime import datetime, timezone

EMAIL    = os.getenv("ACHANTO_EMAIL")
PASSWORD = os.getenv("ACHANTO_PASSWORD")
BASE_URL = "https://wms-api.anchanto.com"

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

print(f"=== Scarlett Dashboard Updater ===")
print(f"Run time : {NOW}")
print(f"Fetching : {TODAY} 00:00 → 23:59")

# ── 1. Login ───────────────────────────────────────────────────────────────────
print("\n[1/5] Login...")
login_resp = requests.post(
    f"{BASE_URL}/api/login",
    json={"api_user": {"email": EMAIL, "password": PASSWORD}},
    timeout=30
)
login_resp.raise_for_status()
jwt = login_resp.json()["jwt"]
print("      ✓ Login success")

HEADERS = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}

# ── 2. Create Report ───────────────────────────────────────────────────────────
# Field IDs dari Achanto B2C Order Report:
# 12=Marketplace, 14=Order Date, 16=Order Number, 22=Item Name
# 623=Kit Name, 28=Ordered Quantity, 1220=Total Ordered Qty
# 29=Payment Method, 30=Order Status, 31=Customer Name
# 32=Shipping Address, 33=Shipping City, 34=Shipping Province
# 35=Shipping Country, 36=Shipping Provider, 37=Tracking Number
# 38=Dispatch Date, 39=Order Type
print("\n[2/5] Creating report...")
report_payload = {
    "report_schedule": {
        "report_type_id": "3",
        "report_format": "csv",
        "report_occurrence_id": "5",
        "mailing_list": [""],
        "field_ids": [
            "12","14","16","22","623","28","1220",
            "29","30","31","33","34","35","36","37","38","39"
        ],
        "filters": {"company_id": ["2"], "campaign_code": []},
        "from_date": TODAY,
        "end_date": TODAY,
        "notification_type": "email",
        "carrier_code": []
    }
}
create_resp = requests.post(
    f"{BASE_URL}/api/v1/report_schedules",
    headers=HEADERS,
    json=report_payload,
    timeout=30
)
create_resp.raise_for_status()
create_data = create_resp.json()

if create_data.get("status_code") != 1000:
    print(f"      ✗ Failed: {json.dumps(create_data, indent=2)}")
    exit(1)

report_id = create_data["data"]["id"]
print(f"      ✓ Report created (ID: {report_id})")

# ── 3. Poll sampai ready ───────────────────────────────────────────────────────
print("\n[3/5] Waiting for report...")
report_url = ""
for attempt in range(1, 25):
    time.sleep(15)
    check = requests.get(
        f"{BASE_URL}/api/v1/report_schedules/{report_id}",
        headers=HEADERS,
        timeout=30
    )
    attrs  = check.json().get("data", {}).get("attributes", {})
    status = attrs.get("status", "")
    url    = attrs.get("report_url", "")
    print(f"      [{attempt:02d}/24] status={status}")
    if url:
        report_url = url
        print("      ✓ Report ready!")
        break

if not report_url:
    print("      ✗ Timeout")
    exit(1)

# ── 4. Download CSV ────────────────────────────────────────────────────────────
print("\n[4/5] Downloading CSV...")
csv_resp = requests.get(report_url, timeout=120)
csv_resp.raise_for_status()
csv_text = csv_resp.content.decode("utf-8-sig")  # fix BOM

reader  = csv.DictReader(io.StringIO(csv_text))
rows    = list(reader)
columns = reader.fieldnames or []
print(f"      ✓ Downloaded {len(rows):,} rows")
print(f"      Columns: {columns}")

# Cek kolom penting
for col in ["Order Status", "Shipping Provider", "Shipping City", "Payment Method"]:
    status_check = "✓" if col in columns else "✗ MISSING"
    print(f"      {status_check} '{col}'")

# Sample values
statuses  = set(r.get("Order Status","").strip() for r in rows[:200] if r.get("Order Status","").strip())
providers = set(r.get("Shipping Provider","").strip() for r in rows[:200] if r.get("Shipping Provider","").strip())
print(f"      Sample statuses:  {statuses}")
print(f"      Sample providers: {providers}")

# ── 5. Save files ──────────────────────────────────────────────────────────────
print("\n[5/5] Saving files...")
os.makedirs("data", exist_ok=True)

with open("data/orders.csv", "w", encoding="utf-8", newline="") as f:
    f.write(csv_text)
print("      ✓ data/orders.csv saved")

meta = {
    "date":         TODAY,
    "last_updated": NOW,
    "run_at_hour":  datetime.now(timezone.utc).hour,
    "total_rows":   len(rows),
    "columns":      columns,
}
with open("data/last_updated.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2)
print("      ✓ data/last_updated.json saved")

print(f"\n=== DONE — {len(rows):,} rows · {len(columns)} columns · {TODAY} ===")
