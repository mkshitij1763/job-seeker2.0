"""Secrets at rest (Gmail tokens): AES-256-GCM under TOKEN_KEY, bound to the owning user through the AAD."""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE = 12


class TokenKeyError(ValueError):
    pass


class DecryptError(ValueError):
    pass


def load_token_key(b64: str) -> bytes:
    try:
        key = base64.b64decode(b64 or "", validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if len(key) != 32:
        raise TokenKeyError("TOKEN_KEY must be 32 random bytes, base64 (run `jobseeker gen-key`)")
    return key


def user_aad(user_id: int) -> bytes:
    return b"user:%d" % user_id


def seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def open_(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < NONCE + 16:
        raise DecryptError("token is damaged")
    try:
        return AESGCM(key).decrypt(blob[:NONCE], blob[NONCE:], aad)
    except InvalidTag as e:
        raise DecryptError("token doesn't decrypt for this user (key rotated or row moved)") from e
