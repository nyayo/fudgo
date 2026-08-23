"""Order-domain exceptions. All return v1 envelope shape via the global
``AppError`` handler.
"""

from __future__ import annotations

from app.core.exceptions import AppError


class OrderError(AppError):
    """Base class for all order-domain errors (status defaults to 422)."""

    code = 422
    message = "Order error"


class CartEmpty(OrderError):
    code = 422
    message = "Cart is empty"


class MenuItemUnavailable(OrderError):
    code = 422
    message = "One or more menu items are unavailable"


class RestaurantClosed(OrderError):
    code = 409
    message = "Restaurant is not currently accepting orders"


class DeliveryAddressOutOfRange(OrderError):
    code = 422
    message = "Delivery address is outside restaurant's delivery radius"


class MinOrderAmountNotMet(OrderError):
    code = 422
    message = "Cart subtotal is below the restaurant's minimum order amount"


class OrderInvalidTransition(OrderError):
    code = 409
    message = "Order cannot transition to the requested status from its current status"


class OrderNotCancellable(OrderError):
    code = 409
    message = "Order can no longer be cancelled at its current state"


class DeliveryAddressNotOwned(OrderError):
    code = 403
    message = "Delivery address does not belong to the current customer"


class RestaurantMismatch(OrderError):
    code = 422
    message = "All cart items must be from the same restaurant"


class IdempotencyConflict(OrderError):
    code = 409
    message = "Idempotency-Key already used for a different request"
