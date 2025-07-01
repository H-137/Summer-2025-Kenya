from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# 🔐 Config - replace with your actual API details or set as environment variables
API_KEY = os.getenv("TEXTSMS_API_KEY", "your_api_key_here")
PARTNER_ID = os.getenv("TEXTSMS_PARTNER_ID", "your_partner_id_here")
SHORTCODE = os.getenv("TEXTSMS_SHORTCODE", "your_shortcode_or_sender_id")

TEXTSMS_SEND_URL = "https://sms.textsms.co.ke/api/services/sendsms/"

# 🧪 Health check endpoint
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "online"}), 200

# 📩 Receive incoming SMS via webhook
@app.route("/receive_sms", methods=["POST"])
def receive_sms():
    data = request.form.to_dict()  # Use .json if TextSMS sends JSON instead
    print("📩 Incoming SMS:", data)

    # Optional: extract useful parts
    sender = data.get("mobile") or data.get("from")
    message = data.get("message") or data.get("text")

    # TODO: Do something useful with the incoming message
    print(f"From: {sender} | Message: {message}")

    return jsonify({"status": "ok"}), 200

# 📤 Send an SMS
@app.route("/send_sms", methods=["POST"])
def send_sms():
    payload = request.json
    recipient = payload.get("mobile")
    message = payload.get("message")

    if not recipient or not message:
        return jsonify({"error": "Missing 'mobile' or 'message'"}), 400

    sms_payload = {
        "apikey": API_KEY,
        "partnerID": PARTNER_ID,
        "mobile": recipient,
        "message": message,
        "shortcode": SHORTCODE
    }

    try:
        response = requests.post(TEXTSMS_SEND_URL, data=sms_payload, timeout=10)
        response.raise_for_status()
        return jsonify({"status": "success", "response": response.text}), 200
    except requests.RequestException as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 🐛 Log all incoming requests for debugging
@app.before_request
def log_all_requests():
    print(f"📡 {request.method} {request.path} | Data: {request.values.to_dict()}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
