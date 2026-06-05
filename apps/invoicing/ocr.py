"""Invoice OCR capture abstraction (Module 14, sub-module 1).

A pluggable connector registry modelled exactly on the payment gateway
(:mod:`apps.tenants.gateways`), the freight carriers (:mod:`apps.fulfillment.carriers`)
and the punch-out connectors (:mod:`apps.catalog.punchout`). The default is a deterministic
``MockOcrEngine`` so the whole capture -> match -> approve -> pay flow can be exercised end to
end (in tests and the demo seed) with no external dependency or binary.

To wire a real engine (Tesseract / AWS Textract / Google Vision):
  1. Implement ``extract`` on a new class returning an :class:`OcrResult`.
  2. Register it in ``_OCR_REGISTRY``.
  3. Set ``OCR_ENGINE=<name>`` in ``.env``.
  4. A real engine that calls out over HTTP MUST SSRF-validate its endpoint and run with a
     timeout (mirror ``apps.fulfillment.carriers.validate_carrier_url``).

WARNING (security / integrity): OCR output is *untrusted*. Never pay an invoice from
OCR-extracted totals. The captured lines are a draft only; the amount actually paid is
re-derived server-side from the three-way-matched lines (see
``apps.invoicing.services.run_three_way_match`` / ``pay_voucher``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from django.conf import settings


@dataclass
class OcrLine:
    description: str = ''
    quantity: Decimal = Decimal('1.00')
    unit_price: Decimal = Decimal('0.00')
    uom: str = 'unit'


@dataclass
class OcrResult:
    """The structured data an OCR engine extracted from an uploaded invoice file."""

    supplier_invoice_ref: str = ''
    currency: str = 'USD'
    tax_amount: Decimal = Decimal('0.00')
    shipping_amount: Decimal = Decimal('0.00')
    confidence: Decimal = Decimal('0.00')
    engine: str = ''
    lines: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class OcrEngine(Protocol):
    name: str

    def extract(self, source_file, *, purchase_order=None) -> OcrResult: ...


class MockOcrEngine:
    """Dev/demo engine. Deterministic — derives a plausible extraction from the PO.

    When a ``purchase_order`` is supplied it seeds one OCR line per (non-cancelled) PO line
    using the PO's own quantities and unit prices, so a captured invoice three-way-matches
    cleanly out of the box. The caller (the seed command / a test) can then nudge a value to
    manufacture a variance. With no PO it returns an empty shell for manual entry.
    """

    name = 'mock'

    def extract(self, source_file, *, purchase_order=None) -> OcrResult:
        result = OcrResult(engine=self.name, confidence=Decimal('92.00'))
        fname = getattr(source_file, 'name', '') or ''
        result.raw = {'source_name': fname, 'engine': self.name}
        if purchase_order is not None:
            result.currency = getattr(purchase_order, 'currency', 'USD') or 'USD'
            result.supplier_invoice_ref = f'SUP-{purchase_order.po_number}'
            lines = (
                purchase_order.lines.exclude(delivery_status='cancelled').order_by('line_no')
            )
            for pol in lines:
                # Bill the received qty if known, else the ordered qty.
                qty = pol.received_quantity if (pol.received_quantity or 0) > 0 else pol.quantity
                result.lines.append(OcrLine(
                    description=pol.description,
                    quantity=Decimal(str(qty or '0')),
                    unit_price=Decimal(str(pol.unit_price or '0')),
                    uom=pol.uom or 'unit',
                ))
            result.raw['po_number'] = purchase_order.po_number
        return result


_OCR_REGISTRY = {
    'mock': MockOcrEngine,
}


def get_ocr_engine():
    """Return an instance of the configured OCR engine (default: mock)."""
    name = getattr(settings, 'OCR_ENGINE', 'mock')
    cls = _OCR_REGISTRY.get(name, MockOcrEngine)
    return cls()
