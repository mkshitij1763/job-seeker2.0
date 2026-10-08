import base64

import pytest

from jobseeker.backup.crypto import (
    MAGIC, MAX_BYTES, BackupDecryptError, BackupKeyError, decrypt, encrypt, load_key,
)

KEY = bytes(range(32))


def test_roundtrip_and_format():
    blob = encrypt(b"archive bytes", KEY)
    assert blob.startswith(MAGIC) and len(blob) == len(MAGIC) + 12 + len(b"archive bytes") + 16
    assert decrypt(blob, KEY) == b"archive bytes"
    assert encrypt(b"x", KEY)[5:17] != encrypt(b"x", KEY)[5:17]  # fresh nonce each time


def test_wrong_key_or_flipped_byte_fails_cleanly():
    blob = bytearray(encrypt(b"archive bytes", KEY))
    with pytest.raises(BackupDecryptError):
        decrypt(bytes(blob), bytes(32))
    blob[-1] ^= 1
    with pytest.raises(BackupDecryptError, match="wrong BACKUP_KEY or damaged file"):
        decrypt(bytes(blob), KEY)
    with pytest.raises(BackupDecryptError):
        decrypt(b"NOPE" + bytes(40), KEY)


def test_load_key_requires_32_bytes():
    assert load_key(base64.b64encode(KEY).decode()) == KEY
    for bad in ("", "abc", base64.b64encode(bytes(16)).decode()):
        with pytest.raises(BackupKeyError):
            load_key(bad)


def test_refuses_huge_archives(monkeypatch):
    monkeypatch.setattr("jobseeker.backup.crypto.MAX_BYTES", 10)
    with pytest.raises(ValueError, match="too large"):
        encrypt(b"x" * 11, KEY)
    assert MAX_BYTES == 512 * 1024 * 1024
