"""Test AES-256-GCM encryption roundtrip."""

import pytest
from src.crypto import encrypt, decrypt


def test_encrypt_decrypt_roundtrip():
    plain = "my_secret_cookie_token_value"
    enc = encrypt(plain)
    dec = decrypt(enc)
    assert dec == plain


def test_encrypt_different_each_time():
    plain = "same_text"
    enc1 = encrypt(plain)
    enc2 = encrypt(plain)
    # Same plaintext → different ciphertext (random nonce)
    assert enc1 != enc2
    # Both decrypt to same value
    assert decrypt(enc1) == decrypt(enc2) == plain


def test_encrypt_empty_string():
    enc = encrypt("")
    assert decrypt(enc) == ""


def test_encrypt_unicode():
    plain = "テスト cookie 🔥"
    enc = encrypt(plain)
    assert decrypt(enc) == plain


def test_decrypt_invalid_raises():
    with pytest.raises((Exception,)):
        decrypt("nothex")