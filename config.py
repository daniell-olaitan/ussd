import os

class Config:
    IOTEC_AUTH_URL = "https://id.iotec.io/connect/token"
    IOTEC_COLLECTION_URL = "https://pay.iotec.io/api/collections/collect"
    IOTEC_STATUS_URL = "https://pay.iotec.io/api/collections/status"
    SECRET_KEY = os.getenv("SECRET_KEY", "default-secret")
    IOTEC_CLIENT_ID = os.getenv('IOTEC_CLIENT_ID')
    IOTEC_CLIENT_SECRET = os.getenv('IOTEC_CLIENT_SECRET')
    FIREBASE_SERVICE_ACCOUNT_B64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")
    WALLET_ID = os.getenv('WALLET_ID')
    INQUIRY_PHONE = "0200947464"
