import requests

from typing import Optional
from dataclasses import dataclass, asdict
from config import get_settings
from db import db
from google.cloud.firestore import Client

settings = get_settings()


@dataclass
class User:
    phone: str
    name: Optional[str] = None
    role: Optional[str] = None  # Farmer | Buyer | Service Provider
    district: Optional[str] = None
    accepted_terms: bool = False
    package: Optional[str] = None  # Basic / Prime / Express / Enterprise
    registered: bool = False

    def to_dict(self):
        return asdict(self)


# ---------------------------
# Services
# ---------------------------
class UserService:
    """CRUD operations for user data in Firestore"""
    COLLECTION = "yofarm_users"

    def __init__(self, db_client: Client):
        self.db = db_client

    def get_user(self, phone: str) -> Optional[User]:
        doc = self.db.collection(self.COLLECTION).document(phone).get()
        if doc.exists:
            data = doc.to_dict()
            return User(**data)
        return None

    def create_or_update_user(self, user: User):
        self.db.collection(self.COLLECTION).document(user.phone).set(user.to_dict())

    def mark_registered(self, phone: str, name: str, role: str, district: str, package: str):
        user = self.get_user(phone) or User(phone=phone)
        user.name = name
        user.role = role
        user.district = district
        user.package = package
        user.accepted_terms = True
        user.registered = True
        self.create_or_update_user(user)

        return user

    def set_accepted_terms(self, phone: str, accepted: bool):
        user = self.get_user(phone) or User(phone=phone)
        user.accepted_terms = accepted
        self.create_or_update_user(user)

        return user

    def set_name(self, phone: str, name: str):
        user = self.get_user(phone) or User(phone=phone)
        user.name = name
        self.create_or_update_user(user)

        return user

    def set_role(self, phone: str, role: str):
        user = self.get_user(phone) or User(phone=phone)
        user.role = role
        self.create_or_update_user(user)

        return user

    def set_district(self, phone: str, district: str):
        user = self.get_user(phone) or User(phone=phone)
        user.district = district
        self.create_or_update_user(user)

        return user

    def set_package(self, phone: str, package: str):
        user = self.get_user(phone) or User(phone=phone)
        user.package = package
        self.create_or_update_user(user)

        return user


class PaymentService:
    """A simple wrapper demonstrating ioTec Pay initiation & verification.
       Replace endpoints/paths based on ioTec docs and your account.
    """

    def __init__(self, client_id: str, api_key: str, base_url: str):
        self.client_id = client_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def headers(self):
        # ioTec docs indicate header auth with Client-Id and X-Api-Key for messaging.
        # For Pay, confirm with your ioTec Pay docs; adjust auth scheme accordingly.
        return {
            "Client-Id": self.client_id,
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json"
        }

    def initiate_mobile_money_payment(self, phone: str, amount: int, description: str, callback_url: str):
        """
        Initiates a payment request to ioTec Pay.
        NOTE: This is a generic example. Confirm `endpoint`, body fields and auth from ioTec Pay docs.
        """

        payload = {
            "amount": amount,
            "currency": "UGX",
            "customer": {
                "msisdn": phone
            },
            "description": description,
            "callback_url": callback_url
        }

        # Example endpoint (confirm in docs and replace if different)
        url = f"{self.base_url}/transactions/initiate"

        try:
            r = requests.post(url, json=payload, headers=self.headers(), timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            # Log and return friendly error
            print("Payment initiation error:", exc, getattr(exc, "response", None))
            return {"status": False, "message": "Could not initiate payment at this time."}

    def verify_transaction(self, transaction_id: str):
        url = f"{self.base_url}/transactions/{transaction_id}/status"
        try:
            r = requests.get(url, headers=self.headers(), timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            print("Payment verify error:", exc)
            return {"status": False, "message": "Could not verify transaction"}


class USSDService:
    """Logic to parse 'text' from Africa's Talking and route user through menu steps."""

    def __init__(self, user_service: UserService, payment_service: PaymentService):
        self.user_svc = user_service
        self.pay_svc = payment_service

    def parse_text(self, raw_text: str):
        # AT sends empty string for new session or " " sometimes; normalize to ""
        if raw_text is None:
            return []
        text = raw_text.strip()
        if text == "" or text == " ":
            return []
        return text.split("*")

    def handle_request(self, phone: str, text: str, base_url: str):
        """
        Returns tuple (response_text, end_session_boolean)
        """
        parts = self.parse_text(text)
        user = self.user_svc.get_user(phone)
        if not user or not user.registered:
            return self._handle_registration_flow(parts, phone, base_url)

        return self._handle_returning_flow(parts, user)

    def _handle_registration_flow(self, parts: list, phone: str, base_url: str):
        # parts is list of inputs so far
        # Step 0 (no input): show Welcome
        if len(parts) == 0:
            resp = "CON Welcome to Yofarm Hub B2B\n1. Register\n2. Exit"
            return resp

        # Step 1: user chose Register or Exit
        first = parts[0]
        if first not in ("1", "2"):
            return "END Invalid choice. Please dial again. Thank you."

        if first == "2":
            return "END Thank you for your interest. Goodbye."

        # first == "1" proceed to Step 2 (enter name)
        if len(parts) == 1:
            return "CON Enter your full name:"

        # Step 2: name provided
        name = parts[1].strip()
        if name == "":
            return "CON Enter your full name:"

        self.user_svc.set_name(phone, name)

        # Step 3: role selection
        if len(parts) == 2:
            return "CON Select your role:\n1. Farmer\n2. Buyer\n3. Service Provider"

        # Step 4: user selected role
        role_choice = parts[2]
        roles_map = {"1": "Farmer", "2": "Buyer", "3": "Service Provider"}
        role = roles_map.get(role_choice)
        if not role:
            return "END Invalid role selection. Session ended."

        self.user_svc.set_role(phone, role)

        # Step 5: Enter location (district)
        if len(parts) == 3:
            return "CON Enter your Location (District):"

        district = parts[3].strip()
        if district == "":
            return "CON Enter your Location (District):", False

        self.user_svc.set_district(phone, district)

        # Step 6: Terms & Privacy acceptance
        if len(parts) == 4:
            return "CON By continuing, you agree to our Privacy Policy & Terms.\n1. Accept\n2. Decline"

        decision = parts[4]
        if decision not in ("1", "2"):
            return "END Invalid input. Session ended."

        if decision == "2":
            # user declined terms -> end session politely
            self.user_svc.set_accepted_terms(phone, False)
            return "END You must accept the Privacy Policy to use Yofarm Hub B2B. Thank you."

        # decision == "1": accepted -> present membership packages
        self.user_svc.set_accepted_terms(phone, True)
        if len(parts) == 5:
            return "CON Choose membership:\n1. Yofarm Access - UGX 9,999\n"

        # Step 7: package selected
        package_map = {"1": "Yofarm Access"}
        pkg_choice = parts[5]
        chosen_pkg = package_map.get(pkg_choice)
        if not chosen_pkg:
            return "END Invalid package selection. Session ended."

        self.user_svc.set_package(phone, chosen_pkg)

        # Ask for payment via Mobile Money
        if len(parts) == 6:
            return f"CON You selected {chosen_pkg}.\nPay via Mobile Money?\n1. Yes\n2. Cancel"

        pay_choice = parts[6]
        if pay_choice not in ("1", "2"):
            return "END Invalid option. Session ended."

        if pay_choice == "2":
            return "END Your registration was cancelled. Dial again to register."

        amount = 9999
        description = f"Yofarm Hub B2B {chosen_pkg} membership"
        # callback url should be public and will receive payment webhook from ioTec.
        # For this demo we'll assume endpoint /payment/webhook
        callback_url = f"{base_url.rstrip('/')}/payment/webhook"
        pay_resp = self.pay_svc.initiate_mobile_money_payment(phone=phone, amount=amount,
                                                             description=description, callback_url=callback_url)

        # Example: ioTec should return a transaction id or status; adapt below according to actual response.
        if not pay_resp or not pay_resp.get("status", True):
            return "END We couldn't initiate payment at this time. Please try again later or contact support."

        # On success, we may store a "pending" payment reference in user doc.
        txn_id = pay_resp.get("data", {}).get("transaction_id", pay_resp.get("transaction_id", None))
        if txn_id:
            # mark user pending registration until webhook confirms payment
            user = self.user_svc.get_user(phone) or User(phone=phone)
            user.name = self.user_svc.get_user(phone).name if self.user_svc.get_user(phone) else None
            user.role = self.user_svc.get_user(phone).role if self.user_svc.get_user(phone) else None
            user.district = self.user_svc.get_user(phone).district if self.user_svc.get_user(phone) else None
            user.package = chosen_pkg
            user.registered = False
            # store transaction reference
            doc_ref = db.collection(UserService.COLLECTION).document(phone)
            doc_ref.set(user.to_dict(), merge=True)
            doc_ref.update({"pending_txn": txn_id})
            # Tell user to expect payment prompt on their phone (depending on provider)
            return ("END A payment prompt has been sent to your phone. "
                    "Complete the payment to finish registration. We'll notify you once payment is confirmed. "
                    f"Inquiries: {settings.inquiry_number}")

        # If no txn_id but success true: assume immediate success (unlikely)
        # finalize registration
        self.user_svc.mark_registered(phone, self.user_svc.get_user(phone).name,
                                     self.user_svc.get_user(phone).role,
                                     self.user_svc.get_user(phone).district,
                                     chosen_pkg)
        name = self.user_svc.get_user(phone).name or ""
        role = self.user_svc.get_user(phone).role or ""
        district = self.user_svc.get_user(phone).district or ""
        return f"END Thank you {name}!\nYou're now registered as a {role} in {district}.\nWe'll get back to you ASAP.\nInquiries: {settings.inquiry_number}"

    def _handle_returning_flow(self, parts, user: User):
        # Step 1: show welcome back menu
        if len(parts) == 0:
            return "CON Welcome back to Yofarm Hub B2B\n1. Buy produce or service\n2. Sell produce or service", False

        choice = parts[0]
        if choice not in ("1", "2"):
            return "END Invalid option. Please dial again. Thank you."

        # Placeholder: user selected Buy or Sell; user promised to provide more detail later
        # For now we will acknowledge and end as per user's spec
        # If you want categories later, extend here.
        return ("END Thank you for partnering with Yofarm Hub B2B. We'll get back ASAP. "
                f"Inquiries: {settings.inquiry_number}")
