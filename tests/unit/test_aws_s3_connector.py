import json
from types import SimpleNamespace

import pytest

from connectors.aws_s3 import api as s3_api
from connectors.aws_s3 import auth as s3_auth
from connectors.aws_s3.connector import S3Connector
from connectors.aws_s3.models import S3ConfigureBody
from connectors.aws_s3.support import build_s3_config
from session_manager import User


class FakeClient:
    def __init__(self):
        self.calls = []

    def head_bucket(self, **kwargs):
        self.calls.append(("head_bucket", kwargs))

    def list_buckets(self):
        self.calls.append(("list_buckets", {}))
        return {"Buckets": [{"Name": "bucket-a"}, {"Name": "bucket-b"}]}


class FakeClientWithSessionToken(FakeClient):
    pass


def test_build_s3_config_keeps_session_token_and_bucket_names(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)

    body = S3ConfigureBody(
        access_key="access",
        secret_key="secret",
        session_token="session",
        bucket_names=["bucket-a", "bucket-b"],
    )

    config, error = build_s3_config(body, {})

    assert error is None
    assert config == {
        "access_key": "access",
        "secret_key": "secret",
        "session_token": "session",
        "bucket_names": ["bucket-a", "bucket-b"],
    }


def test_build_boto3_kwargs_includes_session_token():
    kwargs = s3_auth._build_boto3_kwargs(
        {
            "access_key": "access",
            "secret_key": "secret",
            "session_token": "session",
            "endpoint_url": None,
            "region": "us-east-1",
        }
    )

    assert kwargs["aws_access_key_id"] == "access"
    assert kwargs["aws_secret_access_key"] == "secret"
    assert kwargs["aws_session_token"] == "session"
    assert kwargs["region_name"] == "us-east-1"


def test_validate_s3_access_uses_head_bucket_for_scoped_buckets(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(s3_auth, "create_s3_client", lambda config: fake_client)

    buckets = s3_auth.validate_s3_access(
        {"bucket_names": ["bucket-a", "bucket-b"]},
    )

    assert buckets == ["bucket-a", "bucket-b"]
    assert fake_client.calls == [
        ("head_bucket", {"Bucket": "bucket-a"}),
        ("head_bucket", {"Bucket": "bucket-b"}),
    ]


def test_validate_s3_access_lists_buckets_when_not_scoped(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(s3_auth, "create_s3_client", lambda config: fake_client)

    buckets = s3_auth.validate_s3_access({})

    assert buckets == ["bucket-a", "bucket-b"]
    assert fake_client.calls == [("list_buckets", {})]


@pytest.mark.asyncio
async def test_connector_authenticate_succeeds_for_bucket_scoped_config(monkeypatch):
    called = {}

    def fake_validate(config, bucket_names=None):
        called["config"] = config
        called["bucket_names"] = bucket_names
        return ["bucket-a"]

    monkeypatch.setattr("connectors.aws_s3.connector.validate_s3_access", fake_validate)

    connector = S3Connector({"bucket_names": ["bucket-a"]})

    assert await connector.authenticate() is True
    assert called["config"] == {"bucket_names": ["bucket-a"]}
    assert called["bucket_names"] == ["bucket-a"]


@pytest.mark.asyncio
async def test_s3_configure_returns_specific_access_denied_error(monkeypatch):
    async def fake_list_connections(**kwargs):
        return []

    fake_connection_manager = SimpleNamespace(
        list_connections=fake_list_connections,
    )
    fake_service = SimpleNamespace(connection_manager=fake_connection_manager)

    def fake_validate(config):
        error = Exception("AccessDenied")
        error.response = {"Error": {"Code": "AccessDenied"}}
        raise error

    monkeypatch.setattr(
        s3_api,
        "validate_s3_access",
        fake_validate,
        raising=True,
    )

    response = await s3_api.s3_configure(
        S3ConfigureBody(access_key="access", secret_key="secret"),
        connector_service=fake_service,
        user=User(user_id="u1", email="u1@example.com", name="User One"),
    )

    assert response.status_code == 400
    body = json.loads(response.body.decode())
    assert "s3:ListAllMyBuckets" in body["error"]
