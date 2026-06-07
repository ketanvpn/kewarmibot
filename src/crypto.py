"""AES-256-GCM cookie encryption. Same pattern as KetanTechPay."""

import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config import settings


def _get_key() -> bytes:
    k = settings.encryption_key_bytes
    if len(k) != 32:
        raise ValueError(f"Encryption key must be 32 bytes (got {len(k)})")
    return k


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext → hex( nonce || ciphertext )."""
    nonce = os.urandom(12)
    aesgcm = AESGCM(_get_key())
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return (nonce + ct).hex()


def decrypt(payload: str) -> str:
    """Decrypt hex( nonce || ciphertext ) → plaintext."""
    raw = bytes.fromhex(payload)
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(_get_key())
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")