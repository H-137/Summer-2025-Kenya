import os
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pprint import pprint

import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

from export_ndvi import run_ndvi_export

app = FastAPI()

# Load TextSMS creds once at startup
TEXTSMS_CREDENTIALS_PATH = os.getenv("TEXTSMS_CREDENTIALS_PATH")
with open(TEXTSMS_CREDENTIALS_PATH, "r") as f:
    textsms_creds = json.load(f)

TEXTSMS_API_KEY = textsms_creds["apikey"]
TEXTSMS_PARTNER_ID = textsms_creds["partnerID"]
TEXTSMS_SHORTCODE = textsms_creds["shortcode"]

TEXTSMS_SEND_URL = "https://sms.textsms.co.ke/api/services/sendsms/"

executor = ThreadPoolExecutor(max_workers=2)


class NdviRequest(BaseModel):
    minLon: float
    minLat: float
    maxLon: float
    maxLat: float
    start_date: str
    end_date: str
    min_area: float
    mobile: str


def send_sms(mobile: str, message: str) -> bool:
    payload = {
        "apikey": TEXTSMS_API_KEY,
        "partnerID": TEXTSMS_PARTNER_ID,
        "shortcode": TEXTSMS_SHORTCODE,
        "mobile": mobile,
        "message": message,
    }
    try:
        resp = requests.post(TEXTSMS_SEND_URL, data=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send SMS: {e}")
        return False


async def run_ndvi_and_notify(request: NdviRequest):
    loop = asyncio.get_event_loop()
    ndvi_result = await loop.run_in_executor(
        executor,
        run_ndvi_export,
        request.minLon,
        request.minLat,
        request.maxLon,
        request.maxLat,
        request.start_date,
        request.end_date,
        request.min_area,
    )

    pprint(ndvi_result)

    # Compose SMS message with summary
    count = ndvi_result["count"]
    results = ndvi_result["results"]

    if count == 0:
        message = "No high NDVI zones found for your query."
    else:
        message_lines = [f"Found {count} high NDVI zones:"]
        for zone in results:
            line = f"NDVI: {zone['mean_ndvi']}, Area(ha): {zone['area_ha']}"
            message_lines.append(line)
        message = "\n".join(message_lines)

    # Send SMS
    success = send_sms(request.mobile, message)
    if not success:
        print("Warning: Failed to send SMS notification.")


@app.post("/ndvi")
async def ndvi_endpoint(request: NdviRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_ndvi_and_notify, request)
    return {"status": "NDVI job started, SMS notification will be sent on completion."}

@app.get("/ping")
async def ping():
    return {"status": "ok", "message": "Server is running."}
