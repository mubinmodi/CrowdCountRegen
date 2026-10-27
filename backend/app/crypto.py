"""Encryption at rest for camera passwords, keyed from CC_SECRET_KEY.

Rotating the secret key makes stored camera passwords unreadable; those cameras then report
an auth error until their password is re-entered.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


@lru_cache
def _fernet(secret: str) -> Fernet:
    key = hashlib.sha256(b"crowdcounting/camera-credentials/v1:" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: str) -> str:
    return _fernet(get_settings().secret_key).encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet(get_settings().secret_key).decrypt(token.encode()).decode()
    except InvalidToken:
        return None
