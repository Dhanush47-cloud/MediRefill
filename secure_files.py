"""Authenticated encryption for prescription files using Fernet (AES-128-CBC + HMAC)."""
import os
from cryptography.fernet import Fernet, InvalidToken

class PrescriptionCryptoError(Exception):
    pass

def _fernet():
    key = os.getenv("PRESCRIPTION_ENCRYPTION_KEY", "").strip()
    if not key:
        raise PrescriptionCryptoError("PRESCRIPTION_ENCRYPTION_KEY is required; refusing to store an unencrypted prescription.")
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise PrescriptionCryptoError("PRESCRIPTION_ENCRYPTION_KEY is invalid. Generate a Fernet key.") from exc

def encrypt_bytes(data: bytes) -> bytes:
    if not data:
        raise ValueError("Cannot encrypt an empty file.")
    return _fernet().encrypt(data)

def decrypt_bytes(data: bytes) -> bytes:
    try:
        return _fernet().decrypt(data)
    except InvalidToken as exc:
        raise PrescriptionCryptoError("File authentication failed; the file may be corrupted or the key may be wrong.") from exc
