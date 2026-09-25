import ssl
from unittest.mock import patch

from config import settings


def test_langflow_tls_kwargs_default_verifies_with_system_ca(monkeypatch):
    monkeypatch.setattr(settings, "LANGFLOW_VERIFY_CERTS", True)
    monkeypatch.setattr(settings, "LANGFLOW_CA_CERTS", None)
    monkeypatch.setattr(settings, "OPENRAG_TLS_CERT_PATH", None)
    monkeypatch.setattr(settings, "OPENRAG_TLS_KEY_PATH", None)

    with patch("ssl.create_default_context") as mock_create_ctx:
        mock_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        mock_create_ctx.return_value = mock_ctx

        kwargs = settings._langflow_tls_kwargs()

        mock_create_ctx.assert_called_once_with()
        assert kwargs["verify"] is mock_ctx


def test_langflow_tls_kwargs_with_custom_ca(monkeypatch):
    monkeypatch.setattr(settings, "LANGFLOW_VERIFY_CERTS", True)
    monkeypatch.setattr(settings, "LANGFLOW_CA_CERTS", "/path/to/ca.crt")
    monkeypatch.setattr(settings, "OPENRAG_TLS_CERT_PATH", None)
    monkeypatch.setattr(settings, "OPENRAG_TLS_KEY_PATH", None)

    with patch("ssl.create_default_context") as mock_create_ctx:
        mock_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        mock_create_ctx.return_value = mock_ctx

        kwargs = settings._langflow_tls_kwargs()

        mock_create_ctx.assert_called_once_with(cafile="/path/to/ca.crt")
        assert kwargs["verify"] is mock_ctx


def test_langflow_tls_kwargs_disabled():
    with patch.object(settings, "LANGFLOW_VERIFY_CERTS", False):
        kwargs = settings._langflow_tls_kwargs()
        ctx = kwargs["verify"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE


def test_langflow_tls_kwargs_mtls_client_cert(monkeypatch):
    monkeypatch.setattr(settings, "LANGFLOW_VERIFY_CERTS", True)
    monkeypatch.setattr(settings, "LANGFLOW_CA_CERTS", None)
    monkeypatch.setattr(settings, "OPENRAG_TLS_CERT_PATH", "/path/to/client.crt")
    monkeypatch.setattr(settings, "OPENRAG_TLS_KEY_PATH", "/path/to/client.key")

    with patch("ssl.create_default_context") as mock_create_ctx:
        mock_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        mock_ctx.load_cert_chain = patch.object(mock_ctx, "load_cert_chain").start()
        mock_create_ctx.return_value = mock_ctx

        kwargs = settings._langflow_tls_kwargs()

        mock_ctx.load_cert_chain.assert_called_once_with(
            "/path/to/client.crt", "/path/to/client.key"
        )
        assert kwargs["verify"] is mock_ctx
