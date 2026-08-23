"""Delivery-domain exceptions."""

from __future__ import annotations

from app.core.exceptions import AppError


class DeliveryError(AppError):
    """Base for all delivery-domain errors."""

    code: int = 500


class DeliveryInvalidTransition(DeliveryError):
    status_code = 409

    def __init__(self, msg: str = "Invalid delivery state transition") -> None:
        super().__init__(msg)


class DeliveryNotFound(DeliveryError):
    status_code = 404

    def __init__(self, msg: str = "Delivery not found") -> None:
        super().__init__(msg)


class DeliveryAlreadyClaimed(DeliveryError):
    status_code = 409

    def __init__(self, msg: str = "Delivery has already been claimed") -> None:
        super().__init__(msg)


class DeliveryProofRequired(DeliveryError):
    status_code = 422

    def __init__(self, msg: str = "Proof of delivery is required") -> None:
        super().__init__(msg)


class CourierUnavailable(DeliveryError):
    status_code = 409

    def __init__(self, msg: str = "Courier is off shift") -> None:
        super().__init__(msg)


class CourierLocationRequired(DeliveryError):
    status_code = 422

    def __init__(self, msg: str = "lat / lng are required") -> None:
        super().__init__(msg)
