from unittest.mock import patch, MagicMock

from src.auth import service


def _mock_response(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {"id": "resend-msg-abc"}
    resp.text = str(body or "")
    return resp


def test_send_email_returns_false_when_key_missing(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(service.settings, "RESEND_FROM", "Tazkirati <x@y.z>")
    assert service._send_email("to@x.com", "sub", "<b>h</b>", "t") is False


def test_send_email_returns_false_when_from_missing(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "re_abc")
    monkeypatch.setattr(service.settings, "RESEND_FROM", None)
    assert service._send_email("to@x.com", "sub", "<b>h</b>", "t") is False


def test_send_email_posts_correct_body_and_headers(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(service.settings, "RESEND_FROM", "Tazkirati <no-reply@tazkirati.app>")

    with patch("src.auth.service.httpx.post", return_value=_mock_response()) as mock_post:
        ok = service._send_email("user@example.com", "Subject", "<b>Hello</b>", "Hello")

    assert ok is True
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.resend.com/emails"
    assert kwargs["headers"]["Authorization"] == "Bearer re_test_key"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["json"] == {
        "from": "Tazkirati <no-reply@tazkirati.app>",
        "to": ["user@example.com"],
        "subject": "Subject",
        "html": "<b>Hello</b>",
        "text": "Hello",
    }
    assert kwargs["timeout"] == 15


def test_send_email_returns_false_on_non_2xx(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(service.settings, "RESEND_FROM", "Tazkirati <x@y.z>")

    with patch("src.auth.service.httpx.post", return_value=_mock_response(status_code=422, body={"error": "bad"})):
        assert service._send_email("u@x.com", "s", "<b>h</b>", "t") is False


def test_send_email_returns_false_on_exception(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(service.settings, "RESEND_FROM", "Tazkirati <x@y.z>")

    with patch("src.auth.service.httpx.post", side_effect=Exception("network down")):
        assert service._send_email("u@x.com", "s", "<b>h</b>", "t") is False
