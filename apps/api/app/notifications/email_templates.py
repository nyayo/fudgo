"""Email templates — port of v1's users/email_templates.py:EmailTemplates.

Each template returns {"subject": str, "plain": str, "html": str}.
HTML uses inline styles (email clients strip <style> blocks in some
contexts). v1's design kept; v2 trims the CSS to the essentials.
"""

from __future__ import annotations

from typing import Any


_BASE_STYLES = (
    'style="font-family: Arial, sans-serif; max-width: 600px; '
    'margin: 0 auto; padding: 20px; color: #333;"'
)
_BTN_STYLE = (
    'style="display: inline-block; background: #ff6b35; color: white; '
    'padding: 12px 24px; text-decoration: none; border-radius: 6px; '
    'font-weight: bold;"'
)


def _wrap(title: str, body_html: str, footer: str = "") -> str:
    return f"""
<html><body>
<div {_BASE_STYLES}>
  <h2 style="color: #ff6b35;">Fudgo</h2>
  <h3>{title}</h3>
  {body_html}
  <p style="margin-top: 32px; font-size: 12px; color: #999;">
    {footer or "This is an automated message from Fudgo. If you did not expect it, please ignore this email."}
  </p>
</div>
</body></html>
"""


class EmailTemplates:
    @classmethod
    def get(cls, template_type: str, **kwargs: Any) -> dict[str, str]:
        method = getattr(cls, f"_{template_type}", None)
        if method is None:
            raise ValueError(f"Unknown template type: {template_type}")
        result: dict[str, str] = method(**kwargs)
        return result

    @classmethod
    def _order_confirmation(cls, **kw: Any) -> dict[str, str]:
        order_number = kw.get("order_number", "")
        total = kw.get("total", "")
        subject = f"Order #{order_number} confirmed"
        plain = (
            f"Thanks for your order! Order #{order_number} has been received "
            f"and sent to the restaurant. Total: KES {total}."
        )
        html = _wrap(
            f"Order #{order_number} confirmed",
            f"<p>Hi,</p>"
            f"<p>Thanks for your order! We've sent it to the restaurant.</p>"
            f"<p><strong>Order:</strong> #{order_number}<br>"
            f"<strong>Total:</strong> KES {total}</p>",
        )
        return {"subject": subject, "plain": plain, "html": html}

    @classmethod
    def _order_delivered(cls, **kw: Any) -> dict[str, str]:
        order_number = kw.get("order_number", "")
        subject = f"Order #{order_number} delivered"
        plain = (
            f"Your order #{order_number} has been delivered. Enjoy! "
            f"We'd love your feedback."
        )
        html = _wrap(
            f"Order #{order_number} delivered",
            "<p>Hi,</p><p>Your order has been delivered. Enjoy!</p>"
            "<p>We'd love your feedback in the app.</p>",
        )
        return {"subject": subject, "plain": plain, "html": html}

    @classmethod
    def _promotion(cls, **kw: Any) -> dict[str, str]:
        promo_name = kw.get("promo_name", "")
        discount = kw.get("discount", "")
        subject = f"{promo_name}: {discount}% off!"
        plain = (
            f"New promotion: {promo_name} - {discount}% off. "
            f"Open the Fudgo app to order."
        )
        html = _wrap(
            f"{promo_name}",
            f"<p>A new promotion just dropped:</p>"
            f'<p><span {_BTN_STYLE}>{discount}% off</span></p>'
            f"<p>Open the Fudgo app to order before it ends.</p>",
            footer="You're receiving this because you opted into "
                   "promotions and offers.",
        )
        return {"subject": subject, "plain": plain, "html": html}

    @classmethod
    def _password_reset(cls, **kw: Any) -> dict[str, str]:
        reset_link = kw.get("reset_link", "")
        subject = "Reset your Fudgo password"
        plain = (
            f"Reset your password with this link (valid 30 minutes): "
            f"{reset_link}"
        )
        html = _wrap(
            "Password reset",
            "<p>Hi,</p><p>We got a request to reset your password.</p>"
            f'<p><a href="{reset_link}" {_BTN_STYLE}>Reset password</a></p>'
            "<p>The link is valid for 30 minutes. If you didn't ask for "
            "this, ignore this email.</p>",
        )
        return {"subject": subject, "plain": plain, "html": html}

    @classmethod
    def _account_locked(cls, **kw: Any) -> dict[str, str]:
        reason = kw.get("reason", "policy violation")
        support_email = kw.get("support_email", "support@fudgo.com")
        subject = "Your Fudgo account has been locked"
        plain = (
            f"Your account has been locked. Reason: {reason}. "
            f"Contact {support_email} to appeal."
        )
        html = _wrap(
            "Account locked",
            f"<p>Hi,</p><p>Your account has been locked.</p>"
            f"<p><strong>Reason:</strong> {reason}</p>"
            f"<p>To appeal, contact <a href='mailto:{support_email}'>"
            f"{support_email}</a>.</p>",
        )
        return {"subject": subject, "plain": plain, "html": html}
