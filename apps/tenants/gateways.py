"""Payment gateway abstraction.

Production note: when you swap MockGateway for a real provider (Stripe, Razorpay,
PayPal), DO NOT trust the client-submitted amount. Always derive the charge amount
from the Invoice on the server and verify webhook signatures before marking paid.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from django.conf import settings


@dataclass
class ChargeResult:
    ok: bool
    gateway_ref: str
    message: str = ''


class PaymentGateway(Protocol):
    name: str

    def charge(self, *, amount: Decimal, currency: str, description: str,
               customer_ref: str = '', metadata: dict | None = None) -> ChargeResult: ...

    def refund(self, *, gateway_ref: str, amount: Decimal) -> ChargeResult: ...


class MockGateway:
    """Dev-only gateway. Always succeeds; emits a fake transaction ref."""

    name = 'mock'

    def charge(self, *, amount, currency, description, customer_ref='', metadata=None):
        time.sleep(0.2)
        ref = f'mock_{secrets.token_hex(8)}'
        return ChargeResult(ok=True, gateway_ref=ref, message='Mock charge OK')

    def refund(self, *, gateway_ref, amount):
        return ChargeResult(
            ok=True,
            gateway_ref=f'mock_refund_{secrets.token_hex(6)}',
            message=f'Mock refund of {amount} for {gateway_ref}',
        )


_GATEWAY_REGISTRY = {
    'mock': MockGateway,
}


def get_gateway():
    """Return an instance of the configured payment gateway."""
    name = getattr(settings, 'PAYMENT_GATEWAY', 'mock')
    cls = _GATEWAY_REGISTRY.get(name, MockGateway)
    return cls()
