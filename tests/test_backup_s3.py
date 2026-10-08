import hashlib
from datetime import UTC, datetime

import httpx
import pytest
import respx

from jobseeker.backup.s3 import OffsiteConfigError, S3Config, UploadError, put_object, sign_put
from jobseeker.config import Settings

CFG = S3Config(endpoint="https://s3.us-west-004.backblazeb2.com", region="us-west-004", bucket="js-backups",
               key_id="004a1b2c3d4e5f60000000001", secret="K004abcdefghijklmnopqrstuvwxyz012")
NOW = datetime(2026, 10, 11, 5, 50, tzinfo=UTC)
BODY = b"jobseeker backup test body"
URL = "https://s3.us-west-004.backblazeb2.com/js-backups/daily/jobseeker-2026-10-11.tar.gz.enc"


def test_signature_matches_botocore_vector():
    h = sign_put(URL, BODY, CFG, NOW)
    assert h["x-amz-date"] == "20261011T055000Z"
    assert h["x-amz-content-sha256"] == "1022779fed4a8ae7964451d556877801abc2ec616465f1a50f39bd5d49a011ff"
    assert h["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=004a1b2c3d4e5f60000000001/20261011/us-west-004/s3/aws4_request, "
        "SignedHeaders=host;x-amz-content-sha256;x-amz-date, "
        "Signature=e5e21e39a9e721cdbdab1f855bd66490d199c01da1596eae49a76fe9d83455a1")


@respx.mock
def test_put_object_sends_signed_request():
    route = respx.put(URL).mock(return_value=httpx.Response(200))
    with httpx.Client() as client:
        put_object(client, CFG, "daily/jobseeker-2026-10-11.tar.gz.enc", BODY, NOW)
    req = route.calls.last.request
    assert req.content == BODY
    assert req.headers["x-amz-content-sha256"] == hashlib.sha256(BODY).hexdigest()
    assert "/20261011/us-west-004/s3/aws4_request" in req.headers["Authorization"]


@respx.mock
def test_put_object_retries_then_raises():
    route = respx.put(URL).mock(return_value=httpx.Response(500))
    with httpx.Client() as client, pytest.raises(UploadError, match="HTTP 500"):
        put_object(client, CFG, "daily/jobseeker-2026-10-11.tar.gz.enc", BODY, NOW, sleep=lambda s: None)
    assert route.call_count == 3


@respx.mock
def test_put_object_does_not_retry_client_errors():
    route = respx.put(URL).mock(return_value=httpx.Response(403, text="<Error>AccessDenied</Error>"))
    with httpx.Client() as client, pytest.raises(UploadError, match="HTTP 403"):
        put_object(client, CFG, "daily/jobseeker-2026-10-11.tar.gz.enc", BODY, NOW, sleep=lambda s: None)
    assert route.call_count == 1


def test_from_settings(tmp_path):
    assert S3Config.from_settings(Settings(jobseeker_home=tmp_path)) is None
    full = Settings(jobseeker_home=tmp_path, backup_s3_endpoint=CFG.endpoint, backup_s3_region=CFG.region,
                    backup_s3_bucket=CFG.bucket, backup_s3_key_id=CFG.key_id, backup_s3_secret=CFG.secret)
    assert S3Config.from_settings(full) == CFG
    partial = Settings(jobseeker_home=tmp_path, backup_s3_endpoint=CFG.endpoint)
    with pytest.raises(OffsiteConfigError, match="BACKUP_S3_SECRET"):
        S3Config.from_settings(partial)
