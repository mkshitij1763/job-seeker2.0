"""Encryption for off-site backup copies: AES-256-GCM with BACKUP_KEY. Local copies stay plaintext."""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"JSBK1"
MAX_BYTES = 512 * 1024 * 1024


class BackupKeyError(ValueError):
    pass


class BackupDecryptError(ValueError):
    pass


def load_key(b64: str) -> bytes:
    try:
        key = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if len(key) != 32:
        raise BackupKeyError("BACKUP_KEY must be 32 random bytes, base64 (run `jobseeker gen-key`)")
    return key


def encrypt(data: bytes, key: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise ValueError(f"backup archive too large to upload ({len(data)} bytes)")
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, key: bytes) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 12 + 16:
        raise BackupDecryptError("Couldn't decrypt: wrong BACKUP_KEY or damaged file")
    nonce, body = blob[len(MAGIC):len(MAGIC) + 12], blob[len(MAGIC) + 12:]
    try:
        return AESGCM(key).decrypt(nonce, body, MAGIC)
    except InvalidTag as e:
        raise BackupDecryptError("Couldn't decrypt: wrong BACKUP_KEY or damaged file") from e
