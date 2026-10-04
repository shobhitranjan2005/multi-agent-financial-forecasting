import sys
from fastapi.testclient import TestClient
from backend.api.main import app, _hits

client = TestClient(app)

_hits.clear()
codes = []
for i in range(7):
    r = client.post("/api/forecast/RELIANCE.NS", json={"as_of": "2025-06-02"})
    codes.append(r.status_code)
    if r.status_code == 500:
        print("Error:", r.json())

print("Codes:", codes)
print("Hits:", dict(_hits))
