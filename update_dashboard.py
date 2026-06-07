import os
import requests
import json
from datetime import datetime

email = os.getenv("ACHANTO_EMAIL")
password = os.getenv("ACHANTO_PASSWORD")

today = datetime.utcnow().strftime("%Y-%m-%d")

# LOGIN
login_url = "https://wms-api.anchanto.com/api/login"
login_payload = {
    "api_user": {
        "email": email,
        "password": password
    }
}
login_response = requests.post(login_url, json=login_payload)
login_data = login_response.json()
jwt = login_data["jwt"]
print("LOGIN SUCCESS")

# CREATE REPORT
headers = {
    "Authorization": f"Bearer {jwt}",
    "Content-Type": "application/json"
}

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
        "from_date": today,
        "end_date": today,
        "notification_type": "email",
        "carrier_code": []
    }
}

create_url = "https://wms-api.anchanto.com/api/v1/report_schedules"
response = requests.post(
    create_url,
    headers=headers,
    json=report_payload
)
print("CREATE REPORT STATUS:", response.status_code)
print(json.dumps(response.json(), indent=2))
