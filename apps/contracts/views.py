"""Module 9 views: Contract Management (buyer side).

Function-based views mirroring the auctions module: ``@login_required`` + a
``_require_manage`` / ``_require_view`` permission gate, ``_get_contract`` scoped
to ``request.tenant``, list search + filters + ``Paginator(qs, 20)``, and
lifecycle actions that delegate to :mod:`apps.contracts.services` and surface
``ValidationError.messages`` back to the user.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.vendors.models import VendorCategory

from . import services
from .forms import (
    AddClauseFromLibraryForm,
    AmendmentForm,
    ApplyTemplateForm,
    CancelContractForm,
    ContractClauseForm,
    ContractClauseLineForm,
    ContractDocumentForm,
    ContractForm,
    ContractTemplateForm,
    ObligationForm,
    SaveAsTemplateForm,
    SignatoryForm,
    SignForm,
    TerminateContractForm,
)
from .models import (
    CONTRACT_STATUS_CHOICES,
    CONTRACT_TYPE_CHOICES,
    OBLIGATION_OPEN_STATUSES,
    Contract,
    ContractAmendment,
    ContractClause,
    ContractClauseLine,
    ContractDocument,
    ContractObligation,
    ContractSignatory,
    ContractTemplate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _has_named_url(name):
    try:
        reverse(name)
        return True
    except Exception:
        return False


def _require_manage(request):
    if not services.can_manage_contract(request.user):
        messages.error(request, 'You do not have permission to manage contracts.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_view(request):
    if not services.can_view_contract(request.user):
        messages.error(request, 'You do not have permission to view contracts.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _get_contract(request, pk):
    return get_object_or_404(Contract, pk=pk, tenant=request.tenant)


def _client_ip(request):
    return request.META.get('REMOTE_ADDR', '')


# ---------------------------------------------------------------------------
# Contract list + CRUD
# ---------------------------------------------------------------------------
@login_required
def contract_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = Contract.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'category', 'owner',
    )

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    contract_type = request.GET.get('type', '')
    category = request.GET.get('category', '')

    if q:
        qs = qs.filter(
            Q(contract_number__icontains=q)
            | Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(vendor__legal_name__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if contract_type:
        qs = qs.filter(contract_type=contract_type)
    if category:
        qs = qs.filter(category_id=category)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    querystring = request.GET.copy()
    querystring.pop('page', None)

    context = {
        'page_obj': page_obj,
        'contracts': page_obj.object_list,
        'q': q,
        'status_choices': CONTRACT_STATUS_CHOICES,
        'type_choices': CONTRACT_TYPE_CHOICES,
        'categories': VendorCategory.objects.filter(tenant=request.tenant, is_active=True),
        'querystring': querystring.urlencode(),
        'can_manage': services.can_manage_contract(request.user),
    }
    return render(request, 'contracts/contract_list.html', context)


@login_required
def contract_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = ContractForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            contract = form.save(commit=False)
            contract.tenant = request.tenant
            contract.created_by = request.user
            if not contract.owner_id:
                contract.owner = request.user
            contract.contract_number = services.next_contract_number(request.tenant)
            contract.save()
            services.record_status_event(contract, 'draft', request.user, 'Contract created')
            services.record_audit(
                request.tenant, request.user, 'contract.created',
                target_type='Contract', target_id=str(contract.pk),
                message=f'{contract.contract_number}: {contract.title}',
                request=request,
            )
            messages.success(request, f'Contract {contract.contract_number} created.')
            return redirect('contracts:contract_author', pk=contract.pk)
    else:
        form = ContractForm(tenant=request.tenant)

    return render(request, 'contracts/contract_form.html', {
        'form': form, 'is_edit': False,
    })


@login_required
def contract_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    services.expire_contract(contract, request.user)

    context = {
        'contract': contract,
        'clause_lines': contract.clause_lines.all(),
        'signatories': contract.signatories.select_related('user', 'vendor').all(),
        'obligations': contract.obligations.select_related('account_code', 'owner').all(),
        'amendments': contract.amendments.all(),
        'documents': contract.documents.select_related('uploaded_by').all(),
        'status_events': contract.status_events.select_related('actor').all()[:30],
        'renewals': contract.renewals.all(),
        'document_form': ContractDocumentForm(),
        'terminate_form': TerminateContractForm(),
        'cancel_form': CancelContractForm(),
        'save_as_template_form': SaveAsTemplateForm(),
        'can_manage': services.can_manage_contract(request.user),
    }
    return render(request, 'contracts/contract_detail.html', context)


@login_required
def contract_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    if not contract.is_editable:
        messages.error(request, 'Only draft contracts can be edited.')
        return redirect('contracts:contract_detail', pk=contract.pk)

    if request.method == 'POST':
        form = ContractForm(request.POST, instance=contract, tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.record_audit(
                request.tenant, request.user, 'contract.updated',
                target_type='Contract', target_id=str(contract.pk),
                message=f'{contract.contract_number} updated.', request=request,
            )
            messages.success(request, 'Contract updated.')
            return redirect('contracts:contract_detail', pk=contract.pk)
    else:
        form = ContractForm(instance=contract, tenant=request.tenant)

    return render(request, 'contracts/contract_form.html', {
        'form': form, 'contract': contract, 'is_edit': True,
    })


@login_required
@require_POST
def contract_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    if not contract.is_editable:
        messages.error(request, 'Only draft contracts can be deleted.')
        return redirect('contracts:contract_detail', pk=contract.pk)

    number = contract.contract_number
    services.record_audit(
        request.tenant, request.user, 'contract.deleted', level='warning',
        target_type='Contract', target_id=str(contract.pk),
        message=f'{number} deleted.', request=request,
    )
    contract.delete()
    messages.success(request, f'Contract {number} deleted.')
    return redirect('contracts:contract_list')


# ---------------------------------------------------------------------------
# Authoring (clause lines)
# ---------------------------------------------------------------------------
@login_required
def contract_author(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    context = {
        'contract': contract,
        'clause_lines': contract.clause_lines.all(),
        'add_library_form': AddClauseFromLibraryForm(tenant=request.tenant),
        'has_library': ContractClause.objects.filter(
            tenant=request.tenant, is_active=True).exists(),
        'can_manage': True,
    }
    return render(request, 'contracts/contract_author.html', context)


@login_required
def clause_line_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    if not contract.is_editable:
        messages.error(request, 'Clauses can only be changed while the contract is a draft.')
        return redirect('contracts:contract_author', pk=contract.pk)

    if request.method == 'POST':
        form = ContractClauseLineForm(request.POST, contract=contract)
        if form.is_valid():
            line = form.save(commit=False)
            line.tenant = request.tenant
            line.contract = contract
            line.save()
            services.assemble_body(contract)
            messages.success(request, 'Clause added.')
            return redirect('contracts:contract_author', pk=contract.pk)
    else:
        next_order = contract.clause_lines.count() + 1
        form = ContractClauseLineForm(contract=contract, initial={'sort_order': next_order})

    return render(request, 'contracts/clause_line_form.html', {
        'form': form, 'contract': contract, 'is_edit': False,
    })


@login_required
def clause_line_edit(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    line = get_object_or_404(
        ContractClauseLine, pk=line_pk, contract=contract, tenant=request.tenant)
    if not contract.is_editable:
        messages.error(request, 'Clauses can only be changed while the contract is a draft.')
        return redirect('contracts:contract_author', pk=contract.pk)

    if request.method == 'POST':
        form = ContractClauseLineForm(request.POST, instance=line, contract=contract)
        if form.is_valid():
            form.save()
            services.assemble_body(contract)
            messages.success(request, 'Clause updated.')
            return redirect('contracts:contract_author', pk=contract.pk)
    else:
        form = ContractClauseLineForm(instance=line, contract=contract)

    return render(request, 'contracts/clause_line_form.html', {
        'form': form, 'contract': contract, 'line': line, 'is_edit': True,
    })


@login_required
@require_POST
def clause_line_delete(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    line = get_object_or_404(
        ContractClauseLine, pk=line_pk, contract=contract, tenant=request.tenant)
    if not contract.is_editable:
        messages.error(request, 'Clauses can only be changed while the contract is a draft.')
        return redirect('contracts:contract_author', pk=contract.pk)
    line.delete()
    services.assemble_body(contract)
    messages.success(request, 'Clause removed.')
    return redirect('contracts:contract_author', pk=contract.pk)


@login_required
@require_POST
def clause_line_add_from_library(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    if not contract.is_editable:
        messages.error(request, 'Clauses can only be changed while the contract is a draft.')
        return redirect('contracts:contract_author', pk=contract.pk)

    form = AddClauseFromLibraryForm(request.POST, tenant=request.tenant)
    if not form.is_valid():
        messages.error(request, 'Choose a clause from the library.')
        return redirect('contracts:contract_author', pk=contract.pk)
    try:
        services.add_clause_from_library(contract, form.cleaned_data['clause'], request.user)
        messages.success(request, 'Clause added from the library.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('contracts:contract_author', pk=contract.pk)


@login_required
@require_POST
def contract_save_as_template(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    form = SaveAsTemplateForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('contracts:contract_detail', pk=contract.pk)
    template = services.save_contract_as_template(
        contract, request.user,
        title=form.cleaned_data['title'],
        description=form.cleaned_data.get('description', ''),
        is_shared=form.cleaned_data.get('is_shared', True),
    )
    messages.success(request, f'Saved as template “{template.title}”.')
    return redirect('contracts:template_detail', pk=template.pk)


# ---------------------------------------------------------------------------
# Lifecycle transitions (POST)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def contract_send_for_signature(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    try:
        services.send_for_signature(contract, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('contracts:contract_detail', pk=contract.pk)
    messages.success(request, f'{contract.contract_number} sent for signature.')
    return redirect('contracts:contract_detail', pk=contract.pk)


@login_required
@require_POST
def contract_activate(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    try:
        services.activate_contract(contract, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('contracts:contract_detail', pk=contract.pk)
    messages.success(request, f'{contract.contract_number} is now active.')
    return redirect('contracts:contract_detail', pk=contract.pk)


@login_required
@require_POST
def contract_terminate(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    form = TerminateContractForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('contracts:contract_detail', pk=contract.pk)
    try:
        services.terminate_contract(contract, request.user, form.cleaned_data['reason'])
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('contracts:contract_detail', pk=contract.pk)
    messages.success(request, 'Contract terminated.')
    return redirect('contracts:contract_detail', pk=contract.pk)


@login_required
@require_POST
def contract_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    form = CancelContractForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('contracts:contract_detail', pk=contract.pk)
    try:
        services.cancel_contract(contract, request.user, form.cleaned_data['reason'])
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('contracts:contract_detail', pk=contract.pk)
    messages.success(request, 'Contract cancelled.')
    return redirect('contracts:contract_detail', pk=contract.pk)


@login_required
@require_POST
def contract_renew(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    try:
        new_contract = services.renew_contract(contract, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('contracts:contract_detail', pk=contract.pk)
    messages.success(
        request, f'Renewal {new_contract.contract_number} created as a draft.')
    return redirect('contracts:contract_author', pk=new_contract.pk)


# ---------------------------------------------------------------------------
# Signatories
# ---------------------------------------------------------------------------
@login_required
def signatory_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    if not contract.is_editable:
        messages.error(request, 'Signatories can only be changed while the contract is a draft.')
        return redirect('contracts:contract_detail', pk=contract.pk)

    if request.method == 'POST':
        form = SignatoryForm(request.POST, tenant=request.tenant, contract=contract)
        if form.is_valid():
            signatory = form.save(commit=False)
            signatory.tenant = request.tenant
            signatory.contract = contract
            signatory.save()
            messages.success(request, 'Signatory added.')
            return redirect('contracts:contract_detail', pk=contract.pk)
    else:
        next_order = contract.signatories.count() + 1
        form = SignatoryForm(tenant=request.tenant, contract=contract,
                             initial={'order': next_order})

    return render(request, 'contracts/signatory_form.html', {
        'form': form, 'contract': contract, 'is_edit': False,
    })


@login_required
@require_POST
def signatory_remove(request, pk, signatory_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    signatory = get_object_or_404(
        ContractSignatory, pk=signatory_pk, contract=contract, tenant=request.tenant)
    if not contract.is_editable:
        messages.error(request, 'Signatories can only be changed while the contract is a draft.')
        return redirect('contracts:contract_detail', pk=contract.pk)
    signatory.delete()
    messages.success(request, 'Signatory removed.')
    return redirect('contracts:contract_detail', pk=contract.pk)


@login_required
def signatory_sign(request, pk, signatory_pk):
    """Internal stakeholder signs from inside the app (typed-name signature)."""
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    signatory = get_object_or_404(
        ContractSignatory, pk=signatory_pk, contract=contract, tenant=request.tenant)
    if signatory.party != 'internal':
        messages.error(request, 'Supplier signatories sign from the vendor portal.')
        return redirect('contracts:contract_detail', pk=contract.pk)

    if request.method == 'POST':
        form = SignForm(request.POST)
        if form.is_valid():
            try:
                services.sign_contract(
                    signatory, request.user, form.cleaned_data['signed_name'],
                    ip=_client_ip(request))
                messages.success(request, 'Signed. Thank you.')
                return redirect('contracts:contract_detail', pk=contract.pk)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
    else:
        form = SignForm()

    return render(request, 'contracts/sign_form.html', {
        'form': form, 'contract': contract, 'signatory': signatory,
    })


# ---------------------------------------------------------------------------
# Amendments
# ---------------------------------------------------------------------------
@login_required
def amendment_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    if contract.status in ('cancelled', 'terminated', 'renewed'):
        messages.error(request, 'Cannot amend a closed contract.')
        return redirect('contracts:contract_detail', pk=contract.pk)

    if request.method == 'POST':
        form = AmendmentForm(request.POST)
        if form.is_valid():
            amendment = form.save(commit=False)
            amendment.tenant = request.tenant
            amendment.contract = contract
            amendment.created_by = request.user
            amendment.amendment_number = services.next_amendment_number(contract)
            amendment.save()
            messages.success(request, f'Amendment {amendment.amendment_number} drafted.')
            return redirect('contracts:amendment_detail', pk=contract.pk, amendment_pk=amendment.pk)
    else:
        form = AmendmentForm(initial={
            'new_value': contract.value, 'new_end_date': contract.end_date,
        })

    return render(request, 'contracts/amendment_form.html', {
        'form': form, 'contract': contract, 'is_edit': False,
    })


@login_required
def amendment_detail(request, pk, amendment_pk):
    denied = _require_view(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    amendment = get_object_or_404(
        ContractAmendment, pk=amendment_pk, contract=contract, tenant=request.tenant)
    return render(request, 'contracts/amendment_detail.html', {
        'contract': contract, 'amendment': amendment,
        'can_manage': services.can_manage_contract(request.user),
    })


@login_required
@require_POST
def amendment_apply(request, pk, amendment_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    amendment = get_object_or_404(
        ContractAmendment, pk=amendment_pk, contract=contract, tenant=request.tenant)
    try:
        services.apply_amendment(amendment, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('contracts:amendment_detail', pk=contract.pk, amendment_pk=amendment.pk)
    messages.success(request, f'Amendment {amendment.amendment_number} applied.')
    return redirect('contracts:contract_detail', pk=contract.pk)


@login_required
@require_POST
def amendment_cancel(request, pk, amendment_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    amendment = get_object_or_404(
        ContractAmendment, pk=amendment_pk, contract=contract, tenant=request.tenant)
    try:
        services.cancel_amendment(amendment, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('contracts:amendment_detail', pk=contract.pk, amendment_pk=amendment.pk)
    messages.success(request, 'Amendment cancelled.')
    return redirect('contracts:contract_detail', pk=contract.pk)


# ---------------------------------------------------------------------------
# Obligations
# ---------------------------------------------------------------------------
@login_required
def obligation_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    if request.method == 'POST':
        form = ObligationForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            obligation = form.save(commit=False)
            obligation.tenant = request.tenant
            obligation.contract = contract
            obligation.save()
            messages.success(request, 'Obligation added.')
            return redirect('contracts:contract_detail', pk=contract.pk)
    else:
        form = ObligationForm(tenant=request.tenant)

    return render(request, 'contracts/obligation_form.html', {
        'form': form, 'contract': contract, 'is_edit': False,
    })


@login_required
def obligation_edit(request, pk, obligation_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    obligation = get_object_or_404(
        ContractObligation, pk=obligation_pk, contract=contract, tenant=request.tenant)
    if request.method == 'POST':
        form = ObligationForm(request.POST, instance=obligation, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Obligation updated.')
            return redirect('contracts:contract_detail', pk=contract.pk)
    else:
        form = ObligationForm(instance=obligation, tenant=request.tenant)

    return render(request, 'contracts/obligation_form.html', {
        'form': form, 'contract': contract, 'obligation': obligation, 'is_edit': True,
    })


@login_required
@require_POST
def obligation_delete(request, pk, obligation_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    obligation = get_object_or_404(
        ContractObligation, pk=obligation_pk, contract=contract, tenant=request.tenant)
    obligation.delete()
    messages.success(request, 'Obligation removed.')
    return redirect('contracts:contract_detail', pk=contract.pk)


@login_required
@require_POST
def obligation_complete(request, pk, obligation_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    obligation = get_object_or_404(
        ContractObligation, pk=obligation_pk, contract=contract, tenant=request.tenant)
    try:
        services.complete_obligation(obligation, request.user)
        messages.success(request, 'Obligation marked complete.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('contracts:contract_detail', pk=contract.pk)


@login_required
@require_POST
def obligation_waive(request, pk, obligation_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    obligation = get_object_or_404(
        ContractObligation, pk=obligation_pk, contract=contract, tenant=request.tenant)
    try:
        services.waive_obligation(obligation, request.user)
        messages.success(request, 'Obligation waived.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('contracts:contract_detail', pk=contract.pk)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@login_required
@require_POST
def document_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    form = ContractDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.tenant = request.tenant
        doc.contract = contract
        doc.uploaded_by = request.user
        doc.save()
        services.record_audit(
            request.tenant, request.user, 'contract.document.added',
            target_type='Contract', target_id=str(contract.pk),
            message=f'Document "{doc.title}" added to {contract.contract_number}.',
            request=request,
        )
        messages.success(request, 'Document uploaded.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect('contracts:contract_detail', pk=contract.pk)


@login_required
@require_POST
def document_delete(request, pk, document_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    doc = get_object_or_404(
        ContractDocument, pk=document_pk, contract=contract, tenant=request.tenant)
    title = doc.title
    doc.delete()
    services.record_audit(
        request.tenant, request.user, 'contract.document.deleted', level='warning',
        target_type='Contract', target_id=str(contract.pk),
        message=f'Document "{title}" removed from {contract.contract_number}.',
        request=request,
    )
    messages.success(request, 'Document removed.')
    return redirect('contracts:contract_detail', pk=contract.pk)


# ---------------------------------------------------------------------------
# Clause library
# ---------------------------------------------------------------------------
@login_required
def clause_library_list(request):
    denied = _require_manage(request)
    if denied:
        return denied

    qs = ContractClause.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
    if category:
        qs = qs.filter(category=category)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    querystring = request.GET.copy()
    querystring.pop('page', None)

    return render(request, 'contracts/clause_list.html', {
        'page_obj': page_obj,
        'clauses': page_obj.object_list,
        'q': q,
        'category_choices': ContractClause.CATEGORY_CHOICES,
        'querystring': querystring.urlencode(),
    })


@login_required
def clause_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = ContractClauseForm(request.POST)
        if form.is_valid():
            clause = form.save(commit=False)
            clause.tenant = request.tenant
            clause.save()
            messages.success(request, 'Clause added to the library.')
            return redirect('contracts:clause_list')
    else:
        form = ContractClauseForm()
    return render(request, 'contracts/clause_form.html', {'form': form, 'is_edit': False})


@login_required
def clause_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    clause = get_object_or_404(ContractClause, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = ContractClauseForm(request.POST, instance=clause)
        if form.is_valid():
            form.save()
            messages.success(request, 'Clause updated.')
            return redirect('contracts:clause_list')
    else:
        form = ContractClauseForm(instance=clause)
    return render(request, 'contracts/clause_form.html', {
        'form': form, 'clause': clause, 'is_edit': True,
    })


@login_required
@require_POST
def clause_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    clause = get_object_or_404(ContractClause, pk=pk, tenant=request.tenant)
    clause.delete()
    messages.success(request, 'Clause removed from the library.')
    return redirect('contracts:clause_list')


# ---------------------------------------------------------------------------
# Template library
# ---------------------------------------------------------------------------
@login_required
def template_list(request):
    denied = _require_manage(request)
    if denied:
        return denied

    qs = ContractTemplate.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    querystring = request.GET.copy()
    querystring.pop('page', None)

    return render(request, 'contracts/template_list.html', {
        'page_obj': page_obj,
        'templates': page_obj.object_list,
        'q': q,
        'querystring': querystring.urlencode(),
    })


@login_required
def template_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = ContractTemplateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.tenant = request.tenant
            template.created_by = request.user
            template.save()
            messages.success(request, 'Template created. Add clauses below.')
            return redirect('contracts:template_detail', pk=template.pk)
    else:
        form = ContractTemplateForm()
    return render(request, 'contracts/template_form.html', {'form': form, 'is_edit': False})


@login_required
def template_detail(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    template = get_object_or_404(ContractTemplate, pk=pk, tenant=request.tenant)
    return render(request, 'contracts/template_detail.html', {
        'template': template,
        'clauses': template.clauses.all(),
        'clause_line_form': ContractClauseLineForm(),
        'add_library_form': AddClauseFromLibraryForm(tenant=request.tenant),
        'apply_form': ApplyTemplateForm(tenant=request.tenant),
    })


@login_required
def template_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    template = get_object_or_404(ContractTemplate, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = ContractTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, 'Template updated.')
            return redirect('contracts:template_detail', pk=template.pk)
    else:
        form = ContractTemplateForm(instance=template)
    return render(request, 'contracts/template_form.html', {
        'form': form, 'template': template, 'is_edit': True,
    })


@login_required
@require_POST
def template_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    template = get_object_or_404(ContractTemplate, pk=pk, tenant=request.tenant)
    template.delete()
    messages.success(request, 'Template removed.')
    return redirect('contracts:template_list')


@login_required
@require_POST
def template_clause_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    template = get_object_or_404(ContractTemplate, pk=pk, tenant=request.tenant)
    # Either add a free-form clause or one snapshotted from the library.
    library_form = AddClauseFromLibraryForm(request.POST, tenant=request.tenant)
    from .models import ContractTemplateClause
    if request.POST.get('clause') and library_form.is_valid():
        clause = library_form.cleaned_data['clause']
        next_order = template.clauses.count() + 1
        ContractTemplateClause.all_objects.create(
            tenant=request.tenant, template=template, clause=clause,
            heading=clause.title, body=clause.body, sort_order=next_order,
        )
        messages.success(request, 'Clause added from the library.')
        return redirect('contracts:template_detail', pk=template.pk)

    form = ContractClauseLineForm(request.POST)
    if form.is_valid():
        next_order = template.clauses.count() + 1
        ContractTemplateClause.all_objects.create(
            tenant=request.tenant, template=template,
            heading=form.cleaned_data['heading'], body=form.cleaned_data['body'],
            sort_order=form.cleaned_data.get('sort_order') or next_order,
        )
        messages.success(request, 'Clause added.')
    else:
        messages.error(request, 'Provide a clause heading and body, or pick a library clause.')
    return redirect('contracts:template_detail', pk=template.pk)


@login_required
@require_POST
def template_clause_delete(request, pk, clause_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    template = get_object_or_404(ContractTemplate, pk=pk, tenant=request.tenant)
    from .models import ContractTemplateClause
    tc = get_object_or_404(
        ContractTemplateClause, pk=clause_pk, template=template, tenant=request.tenant)
    tc.delete()
    messages.success(request, 'Clause removed from the template.')
    return redirect('contracts:template_detail', pk=template.pk)


@login_required
def template_use(request, pk):
    """Create a new draft contract from a template (pick the supplier)."""
    denied = _require_manage(request)
    if denied:
        return denied

    template = get_object_or_404(ContractTemplate, pk=pk, tenant=request.tenant)
    from apps.vendors.models import Vendor
    vendors = Vendor.objects.filter(tenant=request.tenant).exclude(
        status__in=('suspended', 'blacklisted', 'inactive')).order_by('legal_name')

    if request.method == 'POST':
        vendor = get_object_or_404(
            Vendor, pk=request.POST.get('vendor'), tenant=request.tenant)
        title = (request.POST.get('title') or '').strip()
        contract = services.create_contract_from_template(
            template, request.user, vendor=vendor, title=title)
        messages.success(request, f'Contract {contract.contract_number} created from template.')
        return redirect('contracts:contract_author', pk=contract.pk)

    return render(request, 'contracts/template_use.html', {
        'template': template, 'vendors': vendors,
    })


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------
@login_required
def renewals_board(request):
    denied = _require_view(request)
    if denied:
        return denied

    # Lazy sweep: raise alerts / auto-renew / expire before rendering the board.
    if services.can_manage_contract(request.user):
        services.scan_contract_alerts(tenant=request.tenant)

    base = Contract.objects.filter(tenant=request.tenant).select_related('vendor')
    active = list(base.filter(status='active').order_by('end_date'))
    board = [
        ('active', 'Active', 'badge-soft-success',
         [c for c in active if not c.is_expiring_soon]),
        ('expiring', 'Expiring soon', 'badge-soft-warning',
         [c for c in active if c.is_expiring_soon]),
        ('expired', 'Expired', 'badge-soft-danger',
         list(base.filter(status='expired').order_by('-end_date'))),
        ('renewed', 'Renewed', 'badge-soft-primary',
         list(base.filter(status='renewed').order_by('-updated_at'))),
    ]
    return render(request, 'contracts/renewals_board.html', {
        'board': board,
        'can_manage': services.can_manage_contract(request.user),
    })


@login_required
def obligation_board(request):
    denied = _require_view(request)
    if denied:
        return denied

    if services.can_manage_contract(request.user):
        services.mark_overdue_obligations(request.tenant)

    base = ContractObligation.objects.filter(
        contract__tenant=request.tenant).select_related('contract', 'contract__vendor')
    board = [
        ('overdue', 'Overdue', 'badge-soft-danger',
         list(base.filter(status='overdue').order_by('due_date'))),
        ('open', 'Open', 'badge-soft-warning',
         list(base.filter(status__in=('pending', 'in_progress')).order_by('due_date'))),
        ('completed', 'Completed', 'badge-soft-success',
         list(base.filter(status='completed').order_by('-completed_at')[:50])),
        ('waived', 'Waived', 'badge-soft-secondary',
         list(base.filter(status='waived')[:50])),
    ]
    return render(request, 'contracts/obligation_board.html', {
        'board': board,
        'can_manage': services.can_manage_contract(request.user),
    })


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@login_required
def analytics_dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied

    metrics = services.tenant_contract_metrics(request.tenant)
    recent = Contract.objects.filter(tenant=request.tenant).select_related('vendor')[:10]
    return render(request, 'contracts/analytics_dashboard.html', {
        'metrics': metrics,
        'recent_contracts': recent,
        'can_manage': services.can_manage_contract(request.user),
    })


@login_required
def contract_analytics(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    contract = _get_contract(request, pk)
    analytics = services.contract_analytics(contract)
    return render(request, 'contracts/contract_analytics.html', {
        'contract': contract, 'analytics': analytics,
        'can_manage': services.can_manage_contract(request.user),
    })
