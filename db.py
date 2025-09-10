import json
import firebase_admin

from firebase_admin import credentials, firestore
from google.cloud.firestore import Client
from config import get_settings


def init_firebase() -> Client:
    try:
        firebase_admin.get_app()
    except ValueError:
        sa_json = get_settings().firebase_service_account_json
        cred = credentials.Certificate(json.loads(sa_json))
        firebase_admin.initialize_app(cred)

    return firestore.client()


db: Client = init_firebase()
