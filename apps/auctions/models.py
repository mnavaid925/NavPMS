"""Module 8: E-Auction Management.

Covers the five PMS sub-modules:
  1. Auction Setup & Configuration   -> Auction + AuctionLot
  2. Live Bidding Interface          -> AuctionParticipant + AuctionBid (vendor portal)
  3. Bid Extension & Rule Enforcement-> Auction anti-snipe fields + place_bid service
  4. Auction Monitoring Console      -> denormalised standing on AuctionParticipant
  5. Post-Auction Results            -> AuctionBid ledger + denormalised award on Auction

A reverse auction is a *live, time-bound, many-bids-per-vendor* contest won on the lowest
valid total price. AuctionBid is an append-only ledger (one row per placement); the live
standing is denormalised onto AuctionParticipant. AuctionDocument holds buyer attachments.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone

from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


AUCTION_TYPE_CHOICES = [
    ('reverse', 'Reverse (lowest price wins)'),
    ('forward', 'Forward (highest price wins)'),
]

AUCTION_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('scheduled', 'Scheduled'),
    ('live', 'Live (bidding open)'),
    ('closed', 'Closed (bidding ended)'),
    ('awarded', 'Awarded'),
    ('cancelled', 'Cancelled'),
]
AUCTION_EDITABLE_STATUSES = ('draft',)
AUCTION_CANCELLABLE_STATUSES = ('draft', 'scheduled', 'live')
AUCTION_FINISHED_STATUSES = ('closed', 'awarded', 'cancelled')

DECREMENT_TYPE_CHOICES = [
    ('amount', 'Fixed amount'),
    ('percent', 'Percent of current best'),
]

RANK_VISIBILITY_CHOICES = [
    ('rank_and_leading', 'Own rank + leading price (blind)'),
    ('rank_only', 'Own rank only'),
    ('full', 'Full leaderboard (open)'),
]

PARTICIPANT_STATUS_CHOICES = [
    ('invited', 'Invited'),
    ('accepted', 'Accepted'),
    ('declined', 'Declined'),
    ('won', 'Won'),
    ('lost', 'Lost'),
    ('withdrawn', 'Withdrawn'),
]
PARTICIPANT_ACTIVE_STATUSES = ('invited', 'accepted')

BID_SOURCE_CHOICES = [
    ('portal', 'Vendor portal'),
    ('manual', 'Buyer (on behalf)'),
    ('proxy', 'Proxy / auto-bid'),
]


# ---------- 1. Auction Setup & Configuration ----------

class Auction(TenantAwareModel, TimeStampedModel):
    """A live, time-bound reverse auction issued by a buyer."""

    STATUS_CHOICES = AUCTION_STATUS_CHOICES
    TYPE_CHOICES = AUCTION_TYPE_CHOICES
    DECREMENT_TYPE_CHOICES = DECREMENT_TYPE_CHOICES
    RANK_VISIBILITY_CHOICES = RANK_VISIBILITY_CHOICES

    auction_number = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    auction_type = models.CharField(
        max_length=10, choices=AUCTION_TYPE_CHOICES, default='reverse',
    )
    category = models.ForeignKey(
        'vendors.VendorCategory', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='auctions',
    )
    currency = models.CharField(max_length=3, default='USD')

    starting_price = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Ceiling — the first/maximum acceptable bid.',
    )
    reserve_price = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Hidden floor — buyer-only target below which the auction is a success.',
    )
    decrement_type = models.CharField(
        max_length=10, choices=DECREMENT_TYPE_CHOICES, default='amount',
    )
    decrement_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Minimum amount (or percent) each new global-best bid must improve by.',
    )

    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)

    anti_snipe_seconds = models.PositiveIntegerField(
        default=120,
        help_text='A valid bid within this many seconds of end_at extends the auction.',
    )
    anti_snipe_extension_seconds = models.PositiveIntegerField(
        default=120,
        help_text='How far end_at is pushed out when anti-snipe fires.',
    )
    max_extensions = models.PositiveIntegerField(
        default=10, help_text='Cap on automatic anti-snipe extensions.',
    )
    extension_count = models.PositiveIntegerField(default=0)

    rank_visibility = models.CharField(
        max_length=20, choices=RANK_VISIBILITY_CHOICES, default='rank_and_leading',
    )

    terms_and_conditions = models.TextField(blank=True)

    requisition = models.ForeignKey(
        'requisitions.Requisition', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='auctions',
        help_text='Source requisition this auction was spawned from (if any).',
    )
    sourcing_event = models.ForeignKey(
        'sourcing.SourcingEvent', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='auctions',
        help_text='Optional hand-off provenance from a sourcing event.',
    )

    status = models.CharField(
        max_length=20, choices=AUCTION_STATUS_CHOICES, default='draft',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='auctions_created',
    )

    awarded_vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='awarded_auctions',
    )
    awarded_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
    )
    awarded_at = models.DateTimeField(null=True, blank=True)
    award_notes = models.TextField(blank=True)

    cancelled_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='auctions_cancelled',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'auction_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'auction_type']),
        ]

    def __str__(self):
        return f'{self.auction_number} — {self.title}'

    @property
    def is_editable(self):
        return self.status in AUCTION_EDITABLE_STATUSES

    @property
    def is_live(self):
        return self.status == 'live'

    @property
    def can_cancel(self):
        return self.status in AUCTION_CANCELLABLE_STATUSES

    @property
    def is_finished(self):
        return self.status in AUCTION_FINISHED_STATUSES

    @property
    def seconds_remaining(self):
        """Whole seconds until end_at (never negative). 0 if no end_at set."""
        if not self.end_at:
            return 0
        delta = (self.end_at - timezone.now()).total_seconds()
        return int(delta) if delta > 0 else 0

    def effective_decrement(self, current_best):
        """Resolve the configured decrement to an absolute amount.

        For a percent decrement the base is the current best bid (or starting_price
        when there is no bid yet). Returns a Decimal quantized to 0.01.
        """
        value = self.decrement_value or Decimal('0')
        if self.decrement_type == 'percent':
            base = current_best if current_best is not None else self.starting_price
            base = base or Decimal('0')
            return (base * value / Decimal('100')).quantize(Decimal('0.01'))
        return value.quantize(Decimal('0.01'))

    def required_next_max(self, current_best):
        """Highest amount a new bid may be.

        With no bids yet, a bid only needs to be <= starting_price. Once there is a
        best bid, a new bid must beat it by at least the effective decrement, so the
        ceiling is current_best - effective_decrement (floored at 0).
        """
        if current_best is None:
            return self.starting_price
        nxt = current_best - self.effective_decrement(current_best)
        return nxt if nxt > Decimal('0') else Decimal('0.00')

    @property
    def total_budget(self):
        """Sum of lot estimated values; falls back to starting_price."""
        total = sum(
            ((lot.quantity or Decimal('0')) * (lot.est_unit_price or Decimal('0'))
             for lot in self.lots.all()),
            Decimal('0.00'),
        )
        return total if total else self.starting_price


# ---------- 1. Auction Setup & Configuration — basket lines ----------

class AuctionLot(TenantAwareModel, TimeStampedModel):
    """A descriptive basket line on an auction (not separately bid in v1)."""

    auction = models.ForeignKey(
        Auction, on_delete=models.CASCADE, related_name='lots',
    )
    lot_no = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=255, blank=True)
    item_description = models.CharField(max_length=255)
    uom = models.CharField(max_length=20, default='EA', help_text='Unit of measure')
    quantity = models.DecimalField(
        max_digits=14, decimal_places=3, default=Decimal('1.000'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    est_unit_price = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='auction_lots',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['lot_no', 'id']
        unique_together = [('auction', 'lot_no')]

    def __str__(self):
        return f'#{self.lot_no} {self.item_description} x{self.quantity}'

    @property
    def estimated_line_total(self):
        return (self.quantity or Decimal('0')) * (self.est_unit_price or Decimal('0'))


# ---------- 2. Live Bidding — invited vendor + denormalised standing ----------

class AuctionParticipant(TenantAwareModel, TimeStampedModel):
    """An invited vendor plus their denormalised live standing in the auction."""

    STATUS_CHOICES = PARTICIPANT_STATUS_CHOICES

    auction = models.ForeignKey(
        Auction, on_delete=models.CASCADE, related_name='participants',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE,
        related_name='auction_participations',
    )
    status = models.CharField(
        max_length=12, choices=PARTICIPANT_STATUS_CHOICES, default='invited',
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='auction_invitations_sent',
    )
    responded_at = models.DateTimeField(null=True, blank=True)

    current_bid_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Latest (best) bid placed by this vendor.',
    )
    current_rank = models.PositiveIntegerField(
        null=True, blank=True, help_text='1 = lowest/leading.',
    )
    bid_count = models.PositiveIntegerField(default=0)
    last_bid_at = models.DateTimeField(null=True, blank=True)
    is_winner = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['current_rank', '-current_bid_amount']
        unique_together = [('auction', 'vendor')]
        indexes = [
            models.Index(fields=['tenant', 'vendor', 'status']),
        ]

    def __str__(self):
        return f'{self.vendor.legal_name} -> {self.auction.auction_number}'


# ---------- 2./5. Live Bidding — append-only bid ledger ----------

class AuctionBid(TenantAwareModel, TimeStampedModel):
    """An append-only ledger row: one record per placed bid."""

    SOURCE_CHOICES = BID_SOURCE_CHOICES

    auction = models.ForeignKey(
        Auction, on_delete=models.CASCADE, related_name='bids',
    )
    participant = models.ForeignKey(
        AuctionParticipant, on_delete=models.CASCADE, related_name='bids',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='auction_bids',
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    placed_at = models.DateTimeField(auto_now_add=True)
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='auction_bids_placed',
    )
    source = models.CharField(
        max_length=10, choices=BID_SOURCE_CHOICES, default='portal',
    )
    rank_at_placement = models.PositiveIntegerField(null=True, blank=True)
    was_leading = models.BooleanField(
        default=False, help_text='Did this bid take the lead when placed?',
    )
    triggered_extension = models.BooleanField(
        default=False, help_text='Did this bid fire an anti-snipe extension?',
    )

    class Meta:
        ordering = ['-placed_at']
        indexes = [
            models.Index(fields=['auction', 'placed_at']),
            models.Index(fields=['auction', 'amount']),
        ]

    def __str__(self):
        return f'{self.vendor.legal_name} @ {self.amount} ({self.auction.auction_number})'


# ---------- Buyer attachments ----------

class AuctionDocument(TenantAwareModel, TimeStampedModel):
    """A buyer attachment on an auction (spec sheet, terms PDF, etc.)."""

    auction = models.ForeignKey(
        Auction, on_delete=models.CASCADE, related_name='documents',
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='auction_docs/', blank=True, null=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='auction_documents_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.title} ({self.auction.auction_number})'
