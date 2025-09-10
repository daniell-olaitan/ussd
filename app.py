from dotenv import load_dotenv
load_dotenv()

import os

from flask import Flask, request, Response, jsonify
from services import UserService, PaymentService, USSDService, User
from firebase_admin import firestore
from db import db
from config import get_settings

settings = get_settings()

user_service = UserService(db)
payment_service = PaymentService(
    settings.iotec_client_id,
    settings.secret_key,
    settings.iotec_base_url
)

ussd_service = USSDService(user_service, payment_service)

app = Flask(__name__)


@app.route("/ussd", methods=["POST", "GET"])
def ussd_entry():
    """
    Africa's Talking USSD callback handler.
    Expects: sessionId, serviceCode, phoneNumber, text (in AT format)
    """
    phone = request.values.get("phoneNumber", "")
    text = request.values.get("text", "")

    # Build base URL for callbacks (used in payment initiation)
    base_url = request.url_root.rstrip("/")
    response_text = ussd_service.handle_request(phone, text, base_url)

    return Response(response_text, mimetype="text/plain")


# ---------------------------
# Payment webhook (ioTec)
# ---------------------------
@app.route("/payment/webhook", methods=["POST"])
def payment_webhook():
    """
    Endpoint to receive payment/webhook notifications from ioTec.
    Confirm the payload shape in ioTec docs and adjust parsing accordingly.
    """
    payload = request.get_json(force=True, silent=True) or {}
    # Example payload fields (depends on ioTec): transaction_id, status, amount, msisdn, reference
    tx_id = payload.get("transaction_id") or payload.get("id") or payload.get("reference")
    status = payload.get("status") or payload.get("transaction_status") or payload.get("state")
    msisdn = payload.get("msisdn") or (payload.get("customer") or {}).get("msisdn")

    if not tx_id:
        # try to parse common alternatives
        tx_id = payload.get("data", {}).get("transaction_id")

    # If msisdn not available, you might have reference to phone stored in DB as pending_txn -> search
    phone = msisdn
    if not phone and tx_id:
        # query Firestore for any user with pending_txn == tx_id
        users_ref = db.collection(UserService.COLLECTION).where("pending_txn", "==", tx_id).stream()
        phone = None
        for doc in users_ref:
            phone = doc.id
            break

    # Handle payment success/failure states - adjust according to ioTec statuses
    if status and str(status).lower() in ("success", "completed", "paid"):
        # finalize user registration if we have a phone
        if phone:
            # retrieve user doc
            udoc = db.collection(UserService.COLLECTION).document(phone).get()
            if udoc.exists:
                data = udoc.to_dict()
                # check pending package
                pkg = data.get("package")
                name = data.get("name")
                role = data.get("role")
                district = data.get("district")
                user_obj = User(phone=phone, name=name, role=role, district=district,
                                accepted_terms=True, package=pkg, registered=True)
                db.collection(UserService.COLLECTION).document(phone).set(user_obj.to_dict(), merge=True)
                # remove pending_txn
                db.collection(UserService.COLLECTION).document(phone).update({"pending_txn": firestore.DELETE_FIELD})
                # optionally notify user via SMS (via ioTec messaging or Africa's Talking SMS) - not implemented here
        # respond 200
        return jsonify({"ok": True}), 200

    # For failed or pending, you can update status accordingly
    if phone:
        db.collection(UserService.COLLECTION).document(phone).update({"payment_status": status})

    return jsonify({"ok": True}), 200


@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
