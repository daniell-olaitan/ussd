#!/usr/bin/env python3
"""
Yofarm Hub B2B USSD Application
Built with Flask, Firestore, and ioTec Pay integration
"""

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import json
from datetime import datetime
import logging
from typing import Optional, Dict, Any
import os
from dataclasses import dataclass

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firebase Admin SDK
try:
    # Use service account key file or default credentials
    if os.path.exists('firebase-service-account.json'):
        cred = credentials.Certificate('firebase-service-account.json')
        firebase_admin.initialize_app(cred)
    else:
        # Use default credentials (for production/cloud environments)
        firebase_admin.initialize_app()

    db = firestore.client()
    logger.info("Firebase initialized successfully")
except Exception as e:
    logger.error(f"Firebase initialization failed: {e}")
    db = None

# Configuration
class Config:
    IOTEC_AUTH_URL = "https://id.iotec.io/connect/token"
    IOTEC_COLLECTION_URL = "https://pay.iotec.io/api/collections/collect"
    IOTEC_STATUS_URL = "https://pay.iotec.io/api/collections/status"
    IOTEC_CLIENT_ID = os.getenv('IOTEC_CLIENT_ID', 'your_client_id')
    IOTEC_CLIENT_SECRET = os.getenv('IOTEC_CLIENT_SECRET', 'your_client_secret')
    WALLET_ID = os.getenv('WALLET_ID', 'your_wallet_id')
    INQUIRY_PHONE = "0200947464"

@dataclass
class User:
    phone: str
    name: str = ""
    role: str = ""
    location: str = ""
    package: str = ""
    status: str = "new"  # new, pending, failed, registered
    transaction_id: str = ""
    created_at: str = ""
    updated_at: str = ""

class DatabaseService:
    """Handle Firestore database operations"""

    def __init__(self, db):
        self.db = db

    def get_user(self, phone: str) -> Optional[Dict[str, Any]]:
        """Retrieve user by phone number"""
        try:
            doc_ref = self.db.collection('users').document(phone)
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error getting user {phone}: {e}")
            return None

    def save_user(self, user_data: Dict[str, Any]) -> bool:
        """Save or update user data"""
        try:
            phone = user_data['phone']
            user_data['updated_at'] = datetime.now().isoformat()

            doc_ref = self.db.collection('users').document(phone)
            doc_ref.set(user_data, merge=True)
            logger.info(f"User {phone} saved successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving user: {e}")
            return False

    def delete_user(self, phone: str) -> bool:
        """Delete user from database"""
        try:
            doc_ref = self.db.collection('users').document(phone)
            doc_ref.delete()
            logger.info(f"User {phone} deleted successfully")
            return True
        except Exception as e:
            logger.error(f"Error deleting user {phone}: {e}")
            return False

    def update_user_status(self, phone: str, status: str, transaction_id: str = "") -> bool:
        """Update user status and transaction ID"""
        try:
            doc_ref = self.db.collection('users').document(phone)
            update_data = {
                'status': status,
                'updated_at': datetime.now().isoformat()
            }
            if transaction_id:
                update_data['transaction_id'] = transaction_id

            doc_ref.update(update_data)
            logger.info(f"User {phone} status updated to {status}")
            return True
        except Exception as e:
            logger.error(f"Error updating user status: {e}")
            return False

class PaymentService:
    """Handle ioTec Pay payment operations"""

    def __init__(self):
        self.access_token = None
        self.token_expires_at = None

    def get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token from ioTec Pay"""
        try:
            if self.access_token and self.token_expires_at:
                # Check if token is still valid (with 30 seconds buffer)
                current_time = datetime.now().timestamp()
                if current_time < (self.token_expires_at - 30):
                    return self.access_token

            # Request new token
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            data = {
                'client_id': Config.IOTEC_CLIENT_ID,
                'client_secret': Config.IOTEC_CLIENT_SECRET,
                'grant_type': 'client_credentials'
            }

            response = requests.post(Config.IOTEC_AUTH_URL, headers=headers, data=data)
            response.raise_for_status()

            token_data = response.json()
            self.access_token = token_data['access_token']
            expires_in = token_data.get('expires_in', 300)
            self.token_expires_at = datetime.now().timestamp() + expires_in

            logger.info("Access token obtained successfully")
            return self.access_token

        except Exception as e:
            logger.error(f"Error getting access token: {e}")
            return None

    def initiate_collection(self, phone: str, amount: int, external_id: str,
                          payer_note: str = "", payee_note: str = "") -> Dict[str, Any]:
        """Initiate mobile money collection"""
        try:
            access_token = self.get_access_token()
            if not access_token:
                return {'success': False, 'message': 'Authentication failed'}

            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            # Format phone number to MSISDN format
            formatted_phone = self.format_phone_number(phone)
            if not formatted_phone:
                return {'success': False, 'message': 'Invalid phone number format'}

            payload = {
                'category': 'MobileMoney',
                'currency': 'UGX',
                'walletId': Config.WALLET_ID,
                'externalId': external_id,
                'payer': formatted_phone,
                'amount': amount,
                'payerNote': payer_note,
                'payeeNote': payee_note,
                'transactionChargesCategory': 'ChargeCustomer'
            }

            response = requests.post(Config.IOTEC_COLLECTION_URL,
                                   headers=headers, json=payload)
            response.raise_for_status()

            result = response.json()
            logger.info(f"Collection initiated for {phone}: {result.get('id', 'N/A')}")

            return {
                'success': True,
                'transaction_id': result.get('id'),
                'status': result.get('status'),
                'message': result.get('statusMessage', 'Payment request sent')
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Payment API error: {e}")
            return {'success': False, 'message': 'Payment service unavailable'}
        except Exception as e:
            logger.error(f"Error initiating collection: {e}")
            return {'success': False, 'message': 'Payment initialization failed'}

    def check_transaction_status(self, transaction_id: str) -> Dict[str, Any]:
        """Check transaction status from ioTec Pay"""
        try:
            access_token = self.get_access_token()
            if not access_token:
                return {'success': False, 'message': 'Authentication failed'}

            headers = {'Authorization': f'Bearer {access_token}'}
            url = f"{Config.IOTEC_STATUS_URL}/{transaction_id}"

            response = requests.get(url, headers=headers)
            response.raise_for_status()

            result = response.json()
            status = result.get('status', 'Unknown').lower()

            # Map ioTec Pay status to our internal status
            status_mapping = {
                'success': 'registered',
                'failed': 'failed',
                'pending': 'pending',
                'senttovendor': 'pending'
            }

            mapped_status = status_mapping.get(status, 'failed')

            return {
                'success': True,
                'status': mapped_status,
                'original_status': result.get('status'),
                'message': result.get('statusMessage', ''),
                'amount': result.get('amount', 0)
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Status check API error: {e}")
            return {'success': False, 'message': 'Status check failed'}
        except Exception as e:
            logger.error(f"Error checking transaction status: {e}")
            return {'success': False, 'message': 'Status check failed'}

    def format_phone_number(self, phone: str) -> Optional[str]:
        """Format phone number to MSISDN format (256XXXXXXXXX)"""
        try:
            # Remove any non-digit characters
            phone = ''.join(filter(str.isdigit, phone))

            # Handle different formats
            if phone.startswith('256') and len(phone) == 12:
                return phone
            elif phone.startswith('0') and len(phone) == 10:
                return '256' + phone[1:]
            elif len(phone) == 9:
                return '256' + phone
            else:
                return None

        except Exception:
            return None

class USSDHandler:
    """Handle USSD session logic and responses"""

    def __init__(self, db_service: DatabaseService, payment_service: PaymentService):
        self.db = db_service
        self.payment = payment_service
        self.sessions = {}  # In-memory session storage

    def handle_ussd_request(self, session_id: str, phone_number: str,
                          text: str) -> Dict[str, str]:
        """Main USSD request handler"""
        try:
            # Get or create session
            if session_id not in self.sessions:
                self.sessions[session_id] = {'step': 0, 'data': {}}

            session = self.sessions[session_id]
            user = self.db.get_user(phone_number)

            # Handle based on user status and session step
            if not user or user['status'] == 'new':
                return self.handle_new_user_flow(session, phone_number, text)
            elif user['status'] in ['pending', 'failed']:
                return self.handle_incomplete_registration(session, phone_number, text, user)
            elif user['status'] == 'registered':
                return self.handle_registered_user_flow(session, phone_number, text, user)
            else:
                return self.create_response("END", "Service temporarily unavailable. Please try again later.")

        except Exception as e:
            logger.error(f"USSD handler error: {e}")
            return self.create_response("END", "Service error. Please try again later.")

    def handle_new_user_flow(self, session: Dict, phone: str, text: str) -> Dict[str, str]:
        """Handle new user registration flow"""
        inputs = text.split('*') if text else ['']
        step = len(inputs) - 1

        if step == 0:  # Welcome screen
            return self.create_response("CON",
                "Welcome to Yofarm Hub B2B\n1. Register\n2. Exit")

        elif step == 1:  # Registration choice
            choice = inputs[1]
            if choice == '1':
                return self.create_response("CON", "Enter your full name:")
            elif choice == '2':
                return self.create_response("END", "Thank you for visiting Yofarm Hub B2B!")
            else:
                return self.create_response("CON",
                    "Invalid choice. Please try again.\n1. Register\n2. Exit")

        elif step == 2:  # Name input
            name = inputs[2].strip()
            if not name or len(name) < 2:
                return self.create_response("CON",
                    "Please enter a valid name (at least 2 characters):")

            session['data']['name'] = name
            return self.create_response("CON",
                "Select your role:\n1. Farmer\n2. Buyer\n3. Service Provider")

        elif step == 3:  # Role selection
            choice = inputs[3]
            roles = {'1': 'Farmer', '2': 'Buyer', '3': 'Service Provider'}

            if choice not in roles:
                return self.create_response("CON",
                    "Invalid choice. Select your role:\n1. Farmer\n2. Buyer\n3. Service Provider")

            session['data']['role'] = roles[choice]
            return self.create_response("CON", "Enter your Location (District):")

        elif step == 4:  # Location input
            location = inputs[4].strip()
            if not location or len(location) < 2:
                return self.create_response("CON",
                    "Please enter a valid location (at least 2 characters):")

            session['data']['location'] = location
            return self.create_response("CON",
                "By continuing, you agree to our Privacy Policy & Terms.\n1. Accept\n2. Decline")

        elif step == 5:  # Privacy policy acceptance
            choice = inputs[5]
            if choice == '2':
                return self.create_response("END",
                    "You must accept the Privacy Policy to use Yofarm Hub B2B. Thank you.")
            elif choice == '1':
                return self.create_response("CON",
                    "Choose membership:\n1. Yofarm Access - UGX 9,999")
            else:
                return self.create_response("CON",
                    "Invalid choice. By continuing, you agree to our Privacy Policy & Terms.\n1. Accept\n2. Decline")

        elif step == 6:  # Package selection
            choice = inputs[6]
            if choice == '1':
                session['data']['package'] = 'Yofarm Access - UGX 9,999'
                return self.create_response("CON",
                    f"You selected {session['data']['package']}.\nPay via Mobile Money?\n1. Yes\n2. Cancel")
            else:
                return self.create_response("CON",
                    "Invalid choice. Choose membership:\n1. Yofarm Access - UGX 9,999")

        elif step == 7:  # Payment confirmation
            choice = inputs[7]
            if choice == '2':
                return self.create_response("END", "Registration cancelled. Thank you!")
            elif choice == '1':
                return self.initiate_payment_for_new_user(session, phone)
            else:
                return self.create_response("CON",
                    f"Invalid choice. You selected {session['data']['package']}.\nPay via Mobile Money?\n1. Yes\n2. Cancel")

        return self.create_response("END", "Invalid session. Please try again.")

    def handle_incomplete_registration(self, session: Dict, phone: str,
                                     text: str, user: Dict) -> Dict[str, str]:
        """Handle users with pending or failed registration"""
        inputs = text.split('*') if text else ['']
        step = len(inputs) - 1

        if step == 0:  # Welcome back screen
            if user['status'] == 'failed':
                option_text = f"1. Retry payment for {user['package']}"
            else:  # pending
                option_text = f"1. Confirm payment for {user['package']}"

            return self.create_response("CON",
                f"Welcome back {user['name']}. Your registration is incomplete.\n{option_text}\n2. Restart registration")

        elif step == 1:  # Choice selection
            choice = inputs[1]
            if choice == '1':
                if user['status'] == 'failed':
                    return self.retry_payment(phone, user)
                else:  # pending
                    return self.confirm_payment(phone, user)
            elif choice == '2':
                # Delete user and restart
                self.db.delete_user(phone)
                return self.create_response("END",
                    "Registration reset. Please redial the code to start fresh registration.")
            else:
                option_text = "1. Retry payment" if user['status'] == 'failed' else "1. Confirm payment"
                return self.create_response("CON",
                    f"Invalid choice. {option_text} for {user['package']}\n2. Restart registration")

        return self.create_response("END", "Invalid session. Please try again.")

    def handle_registered_user_flow(self, session: Dict, phone: str,
                                   text: str, user: Dict) -> Dict[str, str]:
        """Handle registered users"""
        inputs = text.split('*') if text else ['']
        step = len(inputs) - 1

        if step == 0:  # Main menu
            return self.create_response("CON",
                "Welcome back to Yofarm Hub B2B\n1. Buy produce or service\n2. Sell produce or service")

        elif step == 1:  # Menu selection
            choice = inputs[1]
            if choice in ['1', '2']:
                return self.create_response("END",
                    f"Thank you for partnering with Yofarm Hub B2B. We'll get back ASAP. Inquiries: {Config.INQUIRY_PHONE}")
            else:
                return self.create_response("CON",
                    "Invalid choice. Welcome back to Yofarm Hub B2B\n1. Buy produce or service\n2. Sell produce or service")

        return self.create_response("END", "Thank you for using Yofarm Hub B2B!")

    def initiate_payment_for_new_user(self, session: Dict, phone: str) -> Dict[str, str]:
        """Initiate payment for new user registration"""
        try:
            # Save user with pending status first
            user_data = {
                'phone': phone,
                'name': session['data']['name'],
                'role': session['data']['role'],
                'location': session['data']['location'],
                'package': session['data']['package'],
                'status': 'pending',
                'created_at': datetime.now().isoformat(),
                'transaction_id': ''
            }

            # Initiate payment
            payment_result = self.payment.initiate_collection(
                phone=phone,
                amount=9999,  # UGX 9,999
                external_id=f"REG_{phone}_{int(datetime.now().timestamp())}",
                payer_note="Yofarm Hub B2B Registration",
                payee_note=f"Registration for {session['data']['name']}"
            )

            if payment_result['success']:
                user_data['transaction_id'] = payment_result.get('transaction_id', '')
                user_data['status'] = 'pending'
                self.db.save_user(user_data)

                return self.create_response("END",
                    "Payment request sent. Confirm on your phone.")
            else:
                user_data['status'] = 'failed'
                self.db.save_user(user_data)

                return self.create_response("END",
                    "We cannot process your payment at the moment. Please try again later.")

        except Exception as e:
            logger.error(f"Error initiating payment for new user: {e}")
            return self.create_response("END",
                "Payment initialization failed. Please try again later.")

    def retry_payment(self, phone: str, user: Dict) -> Dict[str, str]:
        """Retry payment for failed registration"""
        try:
            payment_result = self.payment.initiate_collection(
                phone=phone,
                amount=9999,
                external_id=f"RETRY_{phone}_{int(datetime.now().timestamp())}",
                payer_note="Yofarm Hub B2B Registration Retry",
                payee_note=f"Registration retry for {user['name']}"
            )

            if payment_result['success']:
                self.db.update_user_status(phone, 'pending',
                                         payment_result.get('transaction_id', ''))
                return self.create_response("END",
                    "Payment request sent. Confirm on your phone.")
            else:
                self.db.update_user_status(phone, 'failed')
                return self.create_response("END",
                    "We cannot process your payment at the moment. Please try again later.")

        except Exception as e:
            logger.error(f"Error retrying payment: {e}")
            return self.create_response("END",
                "Payment retry failed. Please try again later.")

    def confirm_payment(self, phone: str, user: Dict) -> Dict[str, str]:
        """Confirm pending payment status"""
        try:
            if not user.get('transaction_id'):
                return self.create_response("END",
                    "No transaction found. Please restart registration.")

            status_result = self.payment.check_transaction_status(user['transaction_id'])

            if not status_result['success']:
                return self.create_response("END",
                    "Unable to check payment status. Please try again later.")

            new_status = status_result['status']
            self.db.update_user_status(phone, new_status)

            if new_status == 'registered':
                return self.create_response("END",
                    f"Thank you {user['name']}!\nYou're now registered as a {user['role']} in {user['location']}. We'll get back to you ASAP.\nInquiries: {Config.INQUIRY_PHONE}")
            elif new_status == 'failed':
                return self.create_response("END",
                    "Payment failed. Try again later.")
            else:  # still pending
                return self.create_response("END",
                    "Payment is pending. Confirm again later")

        except Exception as e:
            logger.error(f"Error confirming payment: {e}")
            return self.create_response("END",
                "Payment confirmation failed. Please try again later.")

    def create_response(self, response_type: str, message: str) -> Dict[str, str]:
        """Create standardized USSD response"""
        return {
            'response_type': response_type,
            'message': message
        }

# Initialize services
db_service = DatabaseService(db) if db else None
payment_service = PaymentService()
ussd_handler = USSDHandler(db_service, payment_service) if db_service else None

@app.route('/ussd', methods=['POST'])
def handle_ussd():
    """Main USSD endpoint for Africa's Talking"""
    try:
        # Get parameters from Africa's Talking
        session_id = request.form.get('sessionId', '')
        phone_number = request.form.get('phoneNumber', '')
        text = request.form.get('text', '')

        logger.info(f"USSD Request - Session: {session_id}, Phone: {phone_number}, Text: '{text}'")

        if not ussd_handler:
            return "END Service temporarily unavailable. Please try again later."

        # Handle USSD request
        response = ussd_handler.handle_ussd_request(session_id, phone_number, text)

        # Format response for Africa's Talking
        formatted_response = f"{response['response_type']} {response['message']}"

        logger.info(f"USSD Response - Session: {session_id}, Response: '{formatted_response[:100]}...'")

        return formatted_response

    except Exception as e:
        logger.error(f"USSD endpoint error: {e}")
        return "END Service error. Please try again later."

@app.route('/webhook/payment', methods=['POST'])
def payment_webhook():
    """Webhook endpoint for payment notifications (optional)"""
    try:
        data = request.get_json()
        logger.info(f"Payment webhook received: {data}")

        # Process webhook data if needed
        # This could be used for real-time payment status updates

        return jsonify({'status': 'received'}), 200

    except Exception as e:
        logger.error(f"Payment webhook error: {e}")
        return jsonify({'error': 'webhook processing failed'}), 500

@app.route('/admin/user/<phone>', methods=['GET'])
def get_user_info(phone):
    """Admin endpoint to get user information"""
    try:
        if not db_service:
            return jsonify({'error': 'Database unavailable'}), 500

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

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        services_status = {
            'app': 'healthy',
            'database': 'healthy' if db_service else 'unavailable',
            'payment': 'healthy',
            'timestamp': datetime.now().isoformat()
        }

        # Test database connection
        if db_service:
            try:
                # Try to read from database
                db_service.db.collection('health_check').limit(1).get()
            except Exception:
                services_status['database'] = 'error'

        # Test payment service
        try:
            token = payment_service.get_access_token()
            if not token:
                services_status['payment'] = 'auth_error'
        except Exception:
            services_status['payment'] = 'error'

        status_code = 200 if all(status != 'error' for status in services_status.values()) else 503

        return jsonify(services_status), status_code

    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({'error': 'Health check failed'}), 500

if __name__ == '__main__':
    # Development server
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
