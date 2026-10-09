import base64

import pytest

from jobseeker.crypto import DecryptError, TokenKeyError, load_token_key, open_, seal, user_aad

KEY = base64.b64encode(b"k" * 32).decode()


def test_roundtrip_and_fresh_nonce():
    key = load_token_key(KEY)
    a, b = seal(key, b"secret", user_aad(1)), seal(key, b"secret", user_aad(1))
    assert a != b and open_(key, a, user_aad(1)) == b"secret"


def test_wrong_user_aad_fails():  # a row copied to another user never decrypts
    key = load_token_key(KEY)
    with pytest.raises(DecryptError):
        open_(key, seal(key, b"secret", user_aad(1)), user_aad(2))


def test_tampered_or_short_blob_fails():
    key = load_token_key(KEY)
    blob = bytearray(seal(key, b"secret", user_aad(1)))
    blob[-1] ^= 1
    for bad in (bytes(blob), b"short"):
        with pytest.raises(DecryptError):
            open_(key, bad, user_aad(1))


@pytest.mark.parametrize("raw", ["", "not base64!", base64.b64encode(b"k" * 16).decode()])
def test_key_must_be_32_bytes(raw):
    with pytest.raises(TokenKeyError, match="TOKEN_KEY"):
        load_token_key(raw)
