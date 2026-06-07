import os

email = os.getenv("ACHANTO_EMAIL")
password = os.getenv("ACHANTO_PASSWORD")

print("EMAIL:", email)
print("PASSWORD FOUND:", password is not None)
