import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02
from typer.testing import CliRunner

from jobseeker.b64 import urlsafe_decode, urlsafe_encode
from jobseeker.cli import app
from jobseeker.config import Settings


def test_settings_have_extras_fields(tmp_path):
    s = Settings(jobseeker_home=tmp_path)
    for name in ("vapid_private_key", "vapid_public_key", "vapid_subject", "backup_key", "backup_s3_endpoint",
                 "backup_s3_region", "backup_s3_bucket", "backup_s3_key_id", "backup_s3_secret",
                 "healthcheck_ping_url"):
        assert getattr(s, name) == ""


def test_b64_roundtrip_without_padding():
    assert urlsafe_encode(b"\xfb\xff") == "-_8"
    assert urlsafe_decode("-_8") == b"\xfb\xff" and urlsafe_decode("-_8=") == b"\xfb\xff"


def test_gen_key_prints_32_bytes():
    out = CliRunner().invoke(app, ["gen-key"]).output.strip()
    assert len(base64.b64decode(out)) == 32


def test_vapid_keys_roundtrip():
    out = CliRunner().invoke(app, ["vapid-keys"]).output
    lines = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
    private, public = lines["VAPID_PRIVATE_KEY"], lines["VAPID_PUBLIC_KEY"]
    assert len(urlsafe_decode(private)) == 32 and len(urlsafe_decode(public)) == 65
    v = Vapid02.from_raw(private.encode())
    derived = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    assert derived == urlsafe_decode(public)
    assert isinstance(v.private_key, ec.EllipticCurvePrivateKey)
    assert lines["VAPID_SUBJECT"].startswith("mailto:")
