"""Module 9 vendor-portal views: a supplier's contracts + mock e-signature.

Mirrors :mod:`apps.auctions.portal_views`: every view is gated by
``@vendor_required`` and scoped to ``request.user.vendor`` and its tenant. The
supplier signs via a tokenized link (the token is issued by
``services.send_for_signature``); the signing action delegates to
``services.sign_contract`` / ``services.decline_signature``.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.vendors.decorators import vendor_required

from . import services
from .forms import DeclineForm, SignForm
from .models import Contract


def _get_contract(request, pk):
    vendor = request.user.vendor
    return get_object_or_404(Contract, pk=pk, tenant=vendor.tenant, vendor=vendor)


def _get_signatory(request, token):
    """Resolve a signing token to a signatory owned by the current vendor."""
    vendor = request.user.vendor
    signatory = services.signatory_for_token(token)
    if (not signatory
            or signatory.contract.tenant_id != vendor.tenant_id
            or signatory.contract.vendor_id != vendor.id):
        return None
    return signatory


@vendor_required
def portal_contract_list(request):
    """List this vendor's contracts (everything that has left draft)."""
    vendor = request.user.vendor
    contracts = (
        Contract.objects
        .filter(vendor=vendor, tenant=vendor.tenant)
        .exclude(status='draft')
        .select_related('category')
        .order_by('-created_at')
    )
    return render(request, 'vendor_portal/contracts/list.html', {
        'contracts': contracts, 'vendor': vendor,
    })


@vendor_required
def portal_contract_detail(request, pk):
    """Read-only contract view for the supplier, with their signing action."""
    contract = _get_contract(request, pk)
    if contract.status == 'draft':
        messages.error(request, 'This contract is not available yet.')
        return redirect('vendor_portal:contract_inbox')
    my_signatory = contract.signatories.filter(
        party='vendor', status='pending').first()
    return render(request, 'vendor_portal/contracts/detail.html', {
        'contract': contract,
        'clause_lines': contract.clause_lines.all(),
        'obligations': contract.obligations.all(),
        'documents': contract.documents.all(),
        'signatories': contract.signatories.all(),
        'my_signatory': my_signatory,
    })


@vendor_required
def portal_sign(request, token):
    """Tokenized signing page — supplier types their name to sign (mock e-sign)."""
    signatory = _get_signatory(request, token)
    if not signatory:
        messages.error(request, 'That signing link is invalid or has expired.')
        return redirect('vendor_portal:contract_inbox')
    contract = signatory.contract

    if signatory.status != 'pending':
        messages.info(request, 'You have already responded to this contract.')
        return redirect('vendor_portal:contract_detail', pk=contract.pk)

    if request.method == 'POST':
        form = SignForm(request.POST)
        if form.is_valid():
            try:
                services.sign_contract(
                    signatory, request.user, form.cleaned_data['signed_name'],
                    ip=request.META.get('REMOTE_ADDR', ''))
                messages.success(request, 'Thank you — your signature has been recorded.')
                return redirect('vendor_portal:contract_detail', pk=contract.pk)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
    else:
        form = SignForm()

    return render(request, 'vendor_portal/contracts/sign.html', {
        'form': form, 'contract': contract, 'signatory': signatory,
        'clause_lines': contract.clause_lines.all(),
    })


@vendor_required
@require_POST
def portal_sign_decline(request, token):
    """Supplier declines to sign (drops the contract back to draft)."""
    signatory = _get_signatory(request, token)
    if not signatory:
        messages.error(request, 'That signing link is invalid or has expired.')
        return redirect('vendor_portal:contract_inbox')
    contract = signatory.contract
    form = DeclineForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please give a reason for declining.')
        return redirect('vendor_portal:contract_detail', pk=contract.pk)
    try:
        services.decline_signature(signatory, request.user, form.cleaned_data['reason'])
        messages.success(request, 'You have declined to sign this contract.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('vendor_portal:contract_inbox')
