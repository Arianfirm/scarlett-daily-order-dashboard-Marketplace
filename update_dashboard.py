import os
import requests
import json
import time
import csv
import io
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────────
EMAIL    = os.getenv("ACHANTO_EMAIL")
PASSWORD = os.getenv("ACHANTO_PASSWORD")
BASE_URL = "https://wms-api.anchanto.com"

# Tanggal hari ini UTC (sesuai timezone server Achanto)
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

HEADERS = {
    "Authorization": f"Bearer {jwt}",
    "Content-Type": "application/json"
}

# ── 2. Create Report ───────────────────────────────────────────────────────────
print("\n[2/5] Creating report...")
report_payload = {
    "report_schedule": {
        "report_type_id": "3",
        "report_format": "csv",
        "report_occurrence_id": "5",
        "mailing_list": [""],
        "field_ids": ["12","14","16","22","623","28","1220"],
        "filters": {
            "company_id": ["2"],
            "campaign_code": []
        },
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
MAX_ATTEMPTS = 24   # 24 × 15s = 6 menit max
POLL_INTERVAL = 15  # seconds

for attempt in range(1, MAX_ATTEMPTS + 1):
    time.sleep(POLL_INTERVAL)
    check_resp = requests.get(
        f"{BASE_URL}/api/v1/report_schedules/{report_id}",
        headers=HEADERS,
        timeout=30
    )
    attrs = check_resp.json().get("data", {}).get("attributes", {})
    status = attrs.get("status", "")
    url    = attrs.get("report_url", "")
    print(f"      [{attempt:02d}/{MAX_ATTEMPTS}] status={status}")

    if url:
        report_url = url
        print(f"      ✓ Report ready!")
        break

if not report_url:
    print("      ✗ Timeout: report URL not available after 6 minutes")
    exit(1)

# ── 4. Download CSV ────────────────────────────────────────────────────────────
print("\n[4/5] Downloading CSV...")
csv_resp = requests.get(report_url, timeout=120)
csv_resp.raise_for_status()
csv_text = csv_resp.text

# Count rows
reader = csv.reader(io.StringIO(csv_text))
rows = list(reader)
row_count = max(0, len(rows) - 1)  # exclude header
print(f"      ✓ Downloaded {row_count:,} rows")

# ── 5. Save files ──────────────────────────────────────────────────────────────
print("\n[5/5] Saving files...")
os.makedirs("data", exist_ok=True)

# Save CSV
with open("data/orders.csv", "w", encoding="utf-8", newline="") as f:
    f.write(csv_text)
print("      ✓ data/orders.csv saved")

# Save metadata JSON
meta = {
    "date": TODAY,
    "last_updated": NOW,
    "run_at_hour": datetime.now(timezone.utc).hour,
    "total_rows": row_count
}
with open("data/last_updated.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2)
print("      ✓ data/last_updated.json saved")

print(f"\n=== DONE — {row_count:,} order rows saved for {TODAY} ===")
