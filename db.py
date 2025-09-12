import json
import firebase_admin
import logging
import base64

from firebase_admin import credentials, firestore
from google.cloud.firestore import Client
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_firebase() -> Client:
    try:
        firebase_admin.get_app()
    except ValueError:
        b64 = Config.FIREBASE_SERVICE_ACCOUNT_B64
        sa_json = base64.b64decode(b64).decode("utf-8")
        cred = credentials.Certificate(json.loads(sa_json))
        firebase_admin.initialize_app(cred)
        logger.info("Firebase initialized successfully")

    return firestore.client()


db: Client = init_firebase()
