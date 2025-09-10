import os
from functools import lru_cache


class Settings:
    secret_key: str = os.getenv("SECRET_KEY", "default-secret")
    firebase_service_account_json: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    iotec_client_id: str = os.getenv("IOTEC_CLIENT_ID")
    iotec_api_key: str = os.getenv("IOTEC_API_KEY")
    iotec_base_url: str = os.getenv("IOTEC_BASE_URL")
    at_ussd_shortcode: str = os.getenv("AT_USSD_SHORTCODE")
    inquiry_number: str = os.getenv("INQUIRY_NUMBER")


@lru_cache
def get_settings() -> Settings:
    return Settings()
