"""Plunk client tests (mocked requests.post)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.notifications.plunk_client import PlunkClient


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUNK_API_KEY", "pk_test_123")
    from app.core.config import get_settings

    get_settings().PLUNK_API_KEY = "pk_test_123"


def _client() -> PlunkClient:
    from app.core.config import get_settings

    get_settings().PLUNK_API_KEY = "pk_test_123"
    return PlunkClient()


GOOD = {
    "to_email": "a@b.com",
    "email_subject": "Hi",
    "email_body": "plain body",
    "email_html": "<p>body</p>",
}


@patch("requests.post")
def test_sends_correct_payload(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=200)
    c = _client()
    assert c.send_email(GOOD) is True
    kwargs = mock_post.call_args
    assert kwargs.args[0] == "https://api.useplunk.com/v1/send"
    assert kwargs.kwargs["headers"]["Authorization"] == "Bearer pk_test_123"
    body = kwargs.kwargs["json"]
    assert body["to"] == "a@b.com"
    assert body["type"] == "html"
    assert body["body"] == "<p>body</p>"  # html preferred


@patch("requests.post")
def test_returns_true_on_2xx(mock_post: MagicMock) -> None:
    for code in (200, 201, 202):
        mock_post.return_value = MagicMock(status_code=code)
        assert _client().send_email(GOOD) is True


@patch("requests.post")
def test_returns_false_on_4xx(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=401, text="unauth")
    assert _client().send_email(GOOD) is False


@patch("requests.post")
def test_returns_false_on_5xx(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=503, text="boom")
    assert _client().send_email(GOOD) is False


def test_skips_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    get_settings().PLUNK_API_KEY = ""
    c = PlunkClient()
    assert c.is_configured is False
    with patch("requests.post") as mock_post:
        assert c.send_email(GOOD) is False
        mock_post.assert_not_called()


@pytest.mark.parametrize(
    "missing", ["to_email", "email_subject", "email_body"]
)
@patch("requests.post")
def test_rejects_missing_fields(
    mock_post: MagicMock, missing: str
) -> None:
    bad = {k: v for k, v in GOOD.items() if k != missing}
    assert _client().send_email(bad) is False
    mock_post.assert_not_called()


@patch("requests.post")
def test_request_exception_returns_false(mock_post: MagicMock) -> None:
    import requests

    mock_post.side_effect = requests.ConnectionError("down")
    assert _client().send_email(GOOD) is False


@patch("requests.post")
def test_plain_type_when_no_html(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=200)
    data = {"to_email": "a@b.com", "email_subject": "s", "email_body": "b"}
    assert _client().send_email(data) is True
    assert mock_post.call_args.kwargs["json"]["body"] == "b"
