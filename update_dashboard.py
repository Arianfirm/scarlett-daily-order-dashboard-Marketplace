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
print("\n[1/6] Login...")
login_resp = requests.post(
    f"{BASE_URL}/api/login",
    json={"api_user": {"email": EMAIL, "password": PASSWORD}},
    timeout=30
)
login_resp.raise_for_status()
jwt = login_resp.json()["jwt"]
print("      ✓ Login success")

HEADERS = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}

# ── 2. Fetch all available fields & auto-detect IDs ───────────────────────────
print("\n[2/6] Fetching available report fields...")
fields_resp = requests.get(
    f"{BASE_URL}/api/v1/report_types/3/report_fields",
    headers=HEADERS,
    timeout=30
)
fields_data = fields_resp.json()

# Build name → id map
field_map = {}
for item in fields_data.get("data", []):
    attrs = item.get("attributes", {})
    name  = attrs.get("name", "").strip().lower()
    fid   = item.get("id", "")
    field_map[name] = fid

print(f"      ✓ Found {len(field_map)} fields")
print(f"      All fields: {json.dumps({v:k for k,v in field_map.items()}, indent=2)}")

# Target columns we want
WANTED = [
    "marketplace",
    "order date",
    "order number",
    "item name",
    "ordered quantity",
    "total ordered qty",
    "payment method",
    "order status",
    "customer name",
    "shipping city",
    "shipping province",
    "shipping country",
    "shipping provider",
    "tracking number",
    "dispatch date",
    "order type",
    "kit name",
]

field_ids = []
found_fields = []
missing_fields = []

for want in WANTED:
    # exact match first
    if want in field_map:
        field_ids.append(field_map[want])
        found_fields.append(want)
    else:
        # fuzzy: check if any key contains the want string
        matched = [(k,v) for k,v in field_map.items() if want in k or k in want]
        if matched:
            field_ids.append(matched[0][1])
            found_fields.append(f"{want} → {matched[0][0]}")
        else:
            missing_fields.append(want)

print(f"\n      ✓ Mapped fields ({len(field_ids)}):")
for f in found_fields:
    print(f"        · {f}")
if missing_fields:
    print(f"      ⚠ Not found ({len(missing_fields)}): {missing_fields}")

# Fallback to known IDs if field endpoint fails
if not field_ids:
    print("      ⚠ Using fallback field IDs")
    field_ids = ["12","14","16","22","623","28","1220","29","30","31","32","33","34","35","36"]

# ── 3. Create Report ───────────────────────────────────────────────────────────
print("\n[3/6] Creating report...")
report_payload = {
    "report_schedule": {
        "report_type_id": "3",
        "report_format": "csv",
        "report_occurrence_id": "5",
        "mailing_list": [""],
        "field_ids": field_ids,
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

# ── 4. Poll sampai ready ───────────────────────────────────────────────────────
print("\n[4/6] Waiting for report...")
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
    print("      ✗ Timeout: report URL not available")
    exit(1)

# ── 5. Download & decode CSV ───────────────────────────────────────────────────
print("\n[5/6] Downloading CSV...")
csv_resp = requests.get(report_url, timeout=120)
csv_resp.raise_for_status()
# Fix BOM character dari Achanto
csv_text = csv_resp.content.decode("utf-8-sig")

reader   = csv.DictReader(io.StringIO(csv_text))
rows     = list(reader)
columns  = reader.fieldnames or []
print(f"      ✓ Downloaded {len(rows):,} rows")
print(f"      Columns ({len(columns)}): {columns}")

# Validate key columns exist
key_cols = ["Order Status", "Shipping Provider", "Shipping City"]
for col in key_cols:
    if col in columns:
        print(f"      ✓ '{col}' found")
    else:
        print(f"      ⚠ '{col}' NOT found — check field IDs")

# Sample status values
statuses = set(r.get("Order Status","").strip() for r in rows[:500])
print(f"      Sample statuses: {statuses}")

# ── 6. Save files ──────────────────────────────────────────────────────────────
print("\n[6/6] Saving files...")
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
