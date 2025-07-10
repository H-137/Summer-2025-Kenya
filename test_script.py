import subprocess

url = input("Input the cloudflare tunnel URL: ")

json_data = '''
{
    "minLon": -76.0,
    "minLat": 38.0,
    "maxLon": -75.9,
    "maxLat": 38.1,
    "start_date": "2025-06-23",
    "end_date": "2025-07-07",
    "min_area": 10000,
    "mobile": "254712345678"
}
'''

result = subprocess.run(
    ["curl", "-X", "POST", f"{url}/ndvi", "-H", "Content-Type: application/json", "-d", json_data],
    capture_output=True,
    text=True,
)

print(result.stdout)
