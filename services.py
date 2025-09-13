import requests
import logging

from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from config import Config
from datetime import datetime
from db import db
from google.cloud.firestore import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

    def to_dict(self):
        return asdict(self)


# ---------------------------
# Services
# ---------------------------
class UserService:
    """CRUD operations for user data in Firestore"""
    def __init__(self, db_client: Client):
        self.db = db_client

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
                'payer': "0111777777",#formatted_phone,
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
    def __init__(self, db_service: UserService, payment_service: PaymentService):
        self.db = db_service
        self.payment = payment_service

    def parse_text(self, raw_text: str) -> list:
        # AT sends empty string for new session or " " sometimes; normalize to ""
        if raw_text is None:
            return []
        text = raw_text.strip()
        if text == "" or text == " ":
            return []
        return text.split("*")

    def handle_ussd_request(self, phone_number: str,
                          text: str) -> Dict[str, str]:
        """Main USSD request handler"""
        try:
            parts = self.parse_text(text)
            user = self.db.get_user(phone_number)

            # Handle based on user status and session step
            if not user or user['status'] == 'new':
                return self.handle_new_user_flow(phone_number, parts)
            elif user['status'] in ['pending', 'failed']:
                return self.handle_incomplete_registration(phone_number, parts, user)
            elif user['status'] == 'registered':
                return self.handle_registered_user_flow(parts)
            else:
                return self.create_response("END", "Service temporarily unavailable. Please try again later.")

        except Exception as e:
            logger.error(f"USSD handler error: {e}")
            return self.create_response("END", "Service error. Please try again later.")

    def handle_new_user_flow(self, phone: str, parts: list) -> Dict[str, str]:
        """Handle new user registration flow"""
        # Step 0 (no input): show Welcome
        if len(parts) == 0:
            return self.create_response("CON",
                "Welcome to Yofarm Hub B2B\n1. Register\n2. Exit")

        # Step 1: user chose Register or Exit
        first = parts[0]
        if first not in ("1", "2"):
            return self.create_response("END",
                "Invalid choice. Please dial again. Thank you.")

        if first == "2":
            return self.create_response("END",
                "Thank you for your interest. Goodbye.")

        # first == "1" proceed to Step 2 (enter name)
        if len(parts) == 1:
            return self.create_response("CON",
                "Enter your full name:")

        # Step 2: name provided
        name = parts[1].strip()
        if name == "":
            return self.create_response("CON",
                "Enter your full name:")

        # Step 3: role selection
        if len(parts) == 2:
            return self.create_response("CON",
                "Select your role:\n1. Farmer\n2. Buyer\n3. Service Provider")

        # Step 4: user selected role
        role_choice = parts[2]
        roles_map = {"1": "Farmer", "2": "Buyer", "3": "Service Provider"}
        role = roles_map.get(role_choice)
        if not role:
            return self.create_response("END",
                "Invalid role selection. Session ended.")

        # Step 5: Enter location (district)
        if len(parts) == 3:
            return self.create_response("CON",
                "Enter your Location (District):")

        location = parts[3].strip()
        if location == "":
            return self.create_response("CON",
                "Enter your Location (District):")

        # Step 6: Terms & Privacy acceptance
        if len(parts) == 4:
            return self.create_response("CON",
                "By continuing, you agree to our Privacy Policy & Terms.\n1. Accept\n2. Decline")

        decision = parts[4]
        if decision not in ("1", "2"):
            return self.create_response("END",
                "Invalid input. Session ended.")

        if decision == "2":
            # user declined terms -> end session politely
            return self.create_response("END",
                "You must accept the Privacy Policy to use Yofarm Hub B2B. Thank you.")

        if len(parts) == 5:
            packages_txt = "Choose membership:\n1. Yofarm Access - UGX 9,999\n"
            return self.create_response("CON", packages_txt)

        # Step 7: package selected
        package_map = {"1": "Yofarm Access"}
        pkg_choice = parts[5]
        package = package_map.get(pkg_choice)
        if not package:
            return self.create_response("END",
                "Invalid package selection. Session ended.")

        # Ask for payment via Mobile Money
        if len(parts) == 6:
            return self.create_response("CON",
                f"You selected {package}.\nPay via Mobile Money?\n1. Yes\n2. Cancel")

        pay_choice = parts[6]
        if pay_choice not in ("1", "2"):
            return self.create_response("END",
                "Invalid option. Session ended.")

        if pay_choice == "2":
            # cancel registration or treat as not paid? We'll end session politely and store as not registered
            return self.create_response("END",
                "Your registration was cancelled. Dial again to register.")

        user = User(
            phone=phone,
            name=name,
            role=role,
            location=location,
            package=package,
        )

        return self.initiate_payment_for_new_user(user)

    def handle_incomplete_registration(self, phone: str,
                                     parts: list, user: Dict) -> Dict[str, str]:
        """Handle users with pending or failed registration"""
        if len(parts) == 0:
            if user['status'] == 'failed':
                option_text = f"1. Retry payment for {user['package']}"
            else:  # pending
                option_text = f"1. Confirm payment for {user['package']}"

            return self.create_response("CON",
                f"Welcome back {user['name']}. Your registration is incomplete.\n{option_text}\n2. Restart registration")

        choice = parts[0]
        if choice not in ("1", "2"):
            return self.create_response("END",
                "Invalid option. Session ended.")

        if choice == "2":
            self.db.delete_user(phone)
            return self.create_response("END",
                "Registration reset. Please redial the code to start fresh registration.")

        if user['status'] == 'failed':
            return self.retry_payment(user)
        else:  # pending
            return self.confirm_payment(user)

    def handle_registered_user_flow(self, parts: list) -> Dict[str, str]:
        """Handle registered users"""
        if len(parts) == 0:
            return self.create_response("CON",
                "Welcome back to Yofarm Hub B2B\n1. Buy produce or service\n2. Sell produce or service")

        choice = parts[0]
        if choice not in ("1", "2"):
            return self.create_response("END",
                "Invalid option. Session ended.")

        return self.create_response("END",
            f"Thank you for partnering with Yofarm Hub B2B. We'll get back ASAP. Inquiries: {Config.INQUIRY_PHONE}")

    def initiate_payment_for_new_user(self, user: User) -> Dict[str, str]:
        """Initiate payment for new user registration"""
        try:
            user_data = user.to_dict()

            # Initiate payment
            payment_result = self.payment.initiate_collection(
                phone=user.phone,
                amount=9999,  # UGX 9,999
                external_id=f"REG_{user.phone}_{int(datetime.now().timestamp())}",
                payer_note="Yofarm Hub B2B Registration",
                payee_note=f"Registration for {user.name}"
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

    def retry_payment(self, user: Dict) -> Dict[str, str]:
        """Retry payment for failed registration"""
        try:
            payment_result = self.payment.initiate_collection(
                phone=user['phone'],
                amount=9999,
                external_id=f"RETRY_{user['phone']}_{int(datetime.now().timestamp())}",
                payer_note="Yofarm Hub B2B Registration Retry",
                payee_note=f"Registration retry for {user['name']}"
            )

            if payment_result['success']:
                self.db.update_user_status(user['phone'], 'pending',
                                         payment_result.get('transaction_id', ''))
                return self.create_response("END",
                    "Payment request sent. Confirm on your phone.")
            else:
                self.db.update_user_status(user['phone'], 'failed')
                return self.create_response("END",
                    "We cannot process your payment at the moment. Please try again later.")

        except Exception as e:
            logger.error(f"Error retrying payment: {e}")
            return self.create_response("END",
                "Payment retry failed. Please try again later.")

    def confirm_payment(self, user: Dict) -> Dict[str, str]:
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
            self.db.update_user_status(user['phone'], new_status)

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
