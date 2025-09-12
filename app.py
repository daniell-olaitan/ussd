from dotenv import load_dotenv
load_dotenv()

import os
import logging

from flask import Flask, request, Response, jsonify
from services import UserService, PaymentService, USSDHandler, User
from firebase_admin import firestore
from db import db
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY

# Initialize services
db_service = UserService(db)
payment_service = PaymentService()
ussd_handler = USSDHandler(db_service, payment_service)


@app.route('/ussd', methods=['POST'])
def handle_ussd():
    """Main USSD endpoint for Africa's Talking"""
    try:
        # Get parameters from Africa's Talking
        session_id = request.form.get('sessionId', '')
        phone_number = request.form.get('phoneNumber', '')
        text = request.form.get('text', '')

        logger.info(f"USSD Request - Session: {session_id}, Phone: {phone_number}, Text: '{text}'")

        response = ussd_handler.handle_ussd_request(phone_number, text)
        formatted_response = f"{response['response_type']} {response['message']}"

        logger.info(f"USSD Response - Session: {session_id}, Response: '{formatted_response[:100]}...'")

        return formatted_response

    except Exception as e:
        logger.error(f"USSD endpoint error: {e}")
        return "END Service error. Please try again later."


@app.route('/admin/user/<phone>', methods=['GET'])
def get_user_info(phone):
    """Admin endpoint to get user information"""
    try:
        user = db_service.get_user(phone)
        if user:
            return jsonify(user), 200
        else:
            return jsonify({'error': 'User not found'}), 404

    except Exception as e:
        logger.error(f"Admin get user error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/admin/payment-status/<transaction_id>', methods=['GET'])
def check_payment_status(transaction_id):
    """Admin endpoint to check payment status"""
    try:
        result = payment_service.check_transaction_status(transaction_id)
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Admin payment status error: {e}")
        return jsonify({'error': 'Status check failed'}), 500


if __name__ == '__main__':
    # Development server
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
