"""Admin registrations for Module 8: E-Auction Management.

Mirrors the Sourcing admin: the parent ``Auction`` carries lot + participant
inlines, while the append-only ``AuctionBid`` ledger has add/change/delete
disabled (like ``AuditLog`` / ``SourcingAward``).
"""
from django.contrib import admin

from .models import (
    Auction, AuctionBid, AuctionDocument, AuctionLot, AuctionParticipant,
)


class AuctionLotInline(admin.TabularInline):
    model = AuctionLot
    extra = 0
    fields = ['lot_no', 'item_description', 'uom', 'quantity', 'est_unit_price']


class AuctionParticipantInline(admin.TabularInline):
    model = AuctionParticipant
    extra = 0
    fields = [
        'vendor', 'status', 'current_bid_amount', 'current_rank',
        'bid_count', 'last_bid_at',
    ]
    readonly_fields = ['invited_at', 'last_bid_at']


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = [
        'auction_number', 'title', 'auction_type', 'status', 'currency',
        'starting_price', 'awarded_amount', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'auction_type']
    search_fields = ['auction_number', 'title', 'description']
    readonly_fields = [
        'auction_number', 'extension_count', 'awarded_vendor', 'awarded_amount',
        'awarded_at', 'cancelled_at', 'cancelled_by',
    ]
    inlines = [AuctionLotInline, AuctionParticipantInline]


@admin.register(AuctionParticipant)
class AuctionParticipantAdmin(admin.ModelAdmin):
    list_display = [
        'auction', 'vendor', 'status', 'current_bid_amount', 'current_rank',
        'bid_count', 'is_winner',
    ]
    list_filter = ['tenant', 'status', 'is_winner']
    search_fields = ['vendor__legal_name', 'auction__auction_number']
    readonly_fields = ['invited_at', 'last_bid_at']


@admin.register(AuctionBid)
class AuctionBidAdmin(admin.ModelAdmin):
    list_display = [
        'auction', 'vendor', 'amount', 'rank_at_placement', 'was_leading',
        'triggered_extension', 'source', 'placed_at',
    ]
    list_filter = ['tenant', 'source', 'was_leading', 'triggered_extension']
    search_fields = ['vendor__legal_name', 'auction__auction_number']
    readonly_fields = [
        'auction', 'participant', 'vendor', 'amount', 'placed_at', 'placed_by',
        'source', 'rank_at_placement', 'was_leading', 'triggered_extension',
    ]

    def has_add_permission(self, request):
        return False  # append-only

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False  # append-only


@admin.register(AuctionDocument)
class AuctionDocumentAdmin(admin.ModelAdmin):
    list_display = ['auction', 'title', 'uploaded_by', 'uploaded_at']
    list_filter = ['tenant']
    search_fields = ['auction__auction_number', 'title']
    readonly_fields = ['uploaded_at']
