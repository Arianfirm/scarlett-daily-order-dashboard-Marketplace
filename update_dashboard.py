import os
import requests
import json
import time
import csv
from datetime import datetime

email = os.getenv("ACHANTO_EMAIL")
password = os.getenv("ACHANTO_PASSWORD")
today = datetime.utcnow().strftime("%Y-%m-%d")

# LOGIN
login_response = requests.post(
    "https://wms-api.anchanto.com/api/login",
    json={"api_user": {"email": email, "password": password}}
)
jwt = login_response.json()["jwt"]
print("LOGIN SUCCESS")

headers = {
    "Authorization": f"Bearer {jwt}",
    "Content-Type": "application/json"
}

# CREATE REPORT
report_payload = {
    "report_schedule": {
        "report_type_id": "3",
        "report_format": "csv",
        "report_occurrence_id": "5",
        "mailing_list": [""],
        "field_ids": ["12","14","16","22","623","28","1220"],
        "filters": {"company_id": ["2"], "campaign_code": []},
        "from_date": today,
        "end_date": today,
        "notification_type": "email",
        "carrier_code": []
    }
}

create_response = requests.post(
    "https://wms-api.anchanto.com/api/v1/report_schedules",
    headers=headers,
    json=report_payload
)
report_data = create_response.json()["data"]
report_id = report_data["id"]
print(f"REPORT CREATED: ID {report_id}")

# POLLING - tunggu sampai report_url tersedia
print("Waiting for report to be ready...")
report_url = ""
for attempt in range(20):  # max 10 menit
    time.sleep(30)
    check = requests.get(
        f"https://wms-api.anchanto.com/api/v1/report_schedules/{report_id}",
        headers=headers
    )
    check_data = check.json().get("data", {}).get("attributes", {})
    report_url = check_data.get("report_url", "")
    status = check_data.get("status", "")
    print(f"Attempt {attempt+1}: status={status}, url={report_url[:50] if report_url else 'empty'}")
    if report_url:
        break

if not report_url:
    print("TIMEOUT: Report URL not available")
    exit(1)

# DOWNLOAD CSV
print("Downloading CSV...")
csv_response = requests.get(report_url)
csv_text = csv_response.text
rows = list(csv.reader(csv_text.splitlines()))
headers_csv = rows[0] if rows else []
data_rows = rows[1:] if len(rows) > 1 else []
print(f"DOWNLOADED: {len(data_rows)} orders")

# GENERATE HTML DASHBOARD
html_rows = ""
for row in data_rows:
    cells = "".join(f"<td>{cell}</td>" for cell in row)
    html_rows += f"<tr>{cells}</tr>\n"

header_cells = "".join(f"<th>{h}</th>" for h in headers_csv)

html = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Order Dashboard</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
  h1 {{ color: #333; }}
  .meta {{ color: #666; font-size: 14px; margin-bottom: 16px; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 24px; }}
  .card {{ background: white; border-radius: 8px; padding: 16px 24px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .card h3 {{ margin: 0; font-size: 28px; color: #2563eb; }}
  .card p {{ margin: 4px 0 0; color: #666; font-size: 13px; }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  th {{ background: #2563eb; color: white; padding: 10px 12px; text-align: left; font-size: 13px; }}
  td {{ padding: 9px 12px; font-size: 13px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #f0f4ff; }}
</style>
</head>
<body>
<h1>📦 Daily Order Dashboard</h1>
<div class="meta">Tanggal: {today} | Last updated: {datetime.utcnow().strftime("%H:%M:%S")} UTC | Total orders: {len(data_rows)}</div>
<div class="summary">
  <div class="card"><h3>{len(data_rows)}</h3><p>Total Orders Hari Ini</p></div>
</div>
<div class="table-wrap">
<table>
<thead><tr>{header_cells}</tr></thead>
<tbody>
{html_rows}
</tbody>
</table>
</div>
</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("DASHBOARD UPDATED SUCCESSFULLY")
