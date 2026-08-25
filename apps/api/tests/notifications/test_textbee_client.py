"""TextBee client tests (mocked requests.post)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.notifications.textbee_client import TextBeeClient


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("TEXTBEE_API_KEY", "tb_test")
    monkeypatch.setenv("TEXTBEE_DEVICE_ID", "dev-42")
    get_settings().TEXTBEE_API_KEY = "tb_test"
    get_settings().TEXTBEE_DEVICE_ID = "dev-42"


def _client() -> TextBeeClient:
    from app.core.config import get_settings

    get_settings().TEXTBEE_API_KEY = "tb_test"
    get_settings().TEXTBEE_DEVICE_ID = "dev-42"
    return TextBeeClient()


@patch("requests.post")
def test_sends_to_device_url_with_api_key(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=200)
    assert _client().send_sms("+254712345678", "hi") is True
    args, kwargs = mock_post.call_args
    assert args[0] == (
        "https://sms.unshifter.site/api/v1/gateway/devices/dev-42/send-sms"
    )
    assert kwargs["headers"]["x-api-key"] == "tb_test"
    assert kwargs["json"] == {
        "recipients": ["+254712345678"],
        "message": "hi",
    }


@patch("requests.post")
def test_false_on_4xx(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=403, text="no")
    assert _client().send_sms("+254712345678", "hi") is False


def test_skips_when_unconfigured() -> None:
    from app.core.config import get_settings

    get_settings().TEXTBEE_API_KEY = ""
    get_settings().TEXTBEE_DEVICE_ID = ""
    c = TextBeeClient()
    assert c.is_configured is False
    with patch("requests.post") as m:
        assert c.send_sms("+254712345678", "x") is False
        m.assert_not_called()
