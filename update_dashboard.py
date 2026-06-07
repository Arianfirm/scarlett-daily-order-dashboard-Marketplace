import os
import requests

email = os.getenv("ACHANTO_EMAIL")
password = os.getenv("ACHANTO_PASSWORD")

url = "https://wms-api.anchanto.com/api/login"

payload = {
    "api_user": {
        "email": email,
        "password": password
    }
}

response = requests.post(url, json=payload)

print("Status:", response.status_code)

data = response.json()

print("Summary:", data.get("summary"))

if "jwt" in data:
    print("LOGIN SUCCESS")
else:
    print("LOGIN FAILED")
