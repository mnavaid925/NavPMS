"""Module 5 views: vendor CRUD + classification, segmentation, risk profiling,
onboarding (public + admin), blacklist/suspension, and the vendor portal."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant

from .decorators import vendor_blocked, vendor_required
from .forms import (
    OnboardingReviewForm, VendorBankAccountForm, VendorBlacklistEventForm,
    VendorCategoryForm, VendorContactForm, VendorDocumentForm, VendorForm,
    VendorOnboardingApplicationForm, VendorPortalInviteForm,
    VendorPortalProfileForm, VendorRiskAssessmentForm, VendorSegmentForm,
)
from .models import (
    Vendor, VendorBankAccount, VendorBlacklistEvent, VendorCategory,
    VendorContact, VendorDocument, VendorOnboardingApplication,
    VendorRiskAssessment, VendorSegment, VENDOR_STATUS_CHOICES,
    VENDOR_TYPE_CHOICES, RISK_LEVEL_CHOICES,
)
from .services import (
    apply_risk_assessment, blacklist_vendor, convert_application_to_vendor,
    invite_to_portal, next_vendor_number, reinstate_vendor, reject_application,
    revoke_portal_access, suspend_vendor, verify_vendor,
)


# =================================================================
# Vendor list / CRUD
# =================================================================

@login_required
@vendor_blocked
def vendor_list(request):
    if not request.tenant:
        return redirect('tenants:onboarding_start')

    qs = Vendor.objects.filter(tenant=request.tenant).select_related(
        'category', 'segment',
    )
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(legal_name__icontains=q) | Q(trade_name__icontains=q)
            | Q(vendor_number__icontains=q) | Q(email__icontains=q)
            | Q(tax_id__icontains=q)
        )
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    category_id = request.GET.get('category', '')
    if category_id:
        qs = qs.filter(category_id=category_id)
    segment_id = request.GET.get('segment', '')
    if segment_id:
        qs = qs.filter(segment_id=segment_id)
    risk = request.GET.get('risk', '')
    if risk:
        qs = qs.filter(risk_level=risk)

    stats = {
        'total': Vendor.objects.filter(tenant=request.tenant).count(),
        'active': Vendor.objects.filter(tenant=request.tenant, status='active').count(),
        'pending': Vendor.objects.filter(
            tenant=request.tenant, status='pending_verification',
        ).count(),
        'blocked': Vendor.objects.filter(
            tenant=request.tenant, status__in=['suspended', 'blacklisted'],
        ).count(),
    }
    return render(request, 'vendors/vendors/list.html', {
        'vendors': qs.order_by('legal_name'),
        'status_choices': VENDOR_STATUS_CHOICES,
        'risk_choices': RISK_LEVEL_CHOICES,
        'categories': VendorCategory.objects.filter(
            tenant=request.tenant, is_active=True,
        ),
        'segments': VendorSegment.objects.filter(
            tenant=request.tenant, is_active=True,
        ),
        'stats': stats,
    })


@login_required
@vendor_blocked
def vendor_create(request):
    if not request.tenant:
        return redirect('tenants:onboarding_start')
    if request.method == 'POST':
        form = VendorForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            vendor = form.save(commit=False)
            vendor.tenant = request.tenant
            vendor.vendor_number = next_vendor_number(request.tenant)
            vendor.status = 'draft'
            vendor.save()
            messages.success(request, f'Vendor {vendor.vendor_number} created as a draft.')
            return redirect('vendors:vendor_detail', pk=vendor.pk)
    else:
        form = VendorForm(tenant=request.tenant)
    return render(request, 'vendors/vendors/form.html', {
        'form': form, 'title': 'New Vendor',
    })


@login_required
@vendor_blocked
def vendor_detail(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk, tenant=request.tenant)
    return render(request, 'vendors/vendors/detail.html', {
        'vendor': vendor,
        'contacts': vendor.contacts.all(),
        'documents': vendor.documents.all(),
        'bank_accounts': vendor.bank_accounts.all(),
        'risk_assessments': vendor.risk_assessments.all()[:10],
        'blacklist_events': vendor.blacklist_events.all()[:20],
        'contact_form': VendorContactForm(),
        'document_form': VendorDocumentForm(),
        'bank_form': VendorBankAccountForm(),
        'blacklist_form': VendorBlacklistEventForm(),
        'invite_form': VendorPortalInviteForm(),
    })


@login_required
@vendor_blocked
def vendor_edit(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = VendorForm(request.POST, instance=vendor, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f'Vendor {vendor.vendor_number} updated.')
            return redirect('vendors:vendor_detail', pk=vendor.pk)
    else:
        form = VendorForm(instance=vendor, tenant=request.tenant)
    return render(request, 'vendors/vendors/form.html', {
        'form': form, 'title': f'Edit {vendor.legal_name}', 'vendor': vendor,
    })


@login_required
@vendor_blocked
def vendor_delete(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        name = vendor.legal_name
        vendor.delete()
        messages.success(request, f'Vendor {name} deleted.')
    return redirect('vendors:vendor_list')


# ---- vendor actions ----

@login_required
@vendor_blocked
def vendor_verify(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        verify_vendor(vendor, user=request.user)
        messages.success(request, f'{vendor.legal_name} marked verified and set active.')
    return redirect('vendors:vendor_detail', pk=vendor.pk)


# =================================================================
# Vendor sub-records (inline CRUD on vendor detail)
# =================================================================

@login_required
@vendor_blocked
def contact_add(request, vendor_pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    if request.method == 'POST':
        form = VendorContactForm(request.POST)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.tenant = request.tenant
            contact.vendor = vendor
            contact.save()
            messages.success(request, f'Contact "{contact.name}" added.')
        else:
            messages.error(request, 'Could not add contact: ' + str(form.errors))
    return redirect('vendors:vendor_detail', pk=vendor.pk)


@login_required
@vendor_blocked
def contact_delete(request, vendor_pk, pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    contact = get_object_or_404(VendorContact, pk=pk, vendor=vendor, tenant=request.tenant)
    if request.method == 'POST':
        contact.delete()
        messages.success(request, 'Contact deleted.')
    return redirect('vendors:vendor_detail', pk=vendor.pk)


@login_required
@vendor_blocked
def document_add(request, vendor_pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    if request.method == 'POST':
        form = VendorDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.tenant = request.tenant
            doc.vendor = vendor
            doc.save()
            messages.success(request, f'Document "{doc.title}" added.')
        else:
            messages.error(request, 'Could not add document: ' + str(form.errors))
    return redirect('vendors:vendor_detail', pk=vendor.pk)


@login_required
@vendor_blocked
def document_verify(request, vendor_pk, pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    doc = get_object_or_404(VendorDocument, pk=pk, vendor=vendor, tenant=request.tenant)
    if request.method == 'POST':
        doc.is_verified = True
        doc.verified_at = timezone.now()
        doc.verified_by = request.user
        doc.save(update_fields=['is_verified', 'verified_at', 'verified_by', 'updated_at'])
        messages.success(request, f'Document "{doc.title}" marked verified.')
    return redirect('vendors:vendor_detail', pk=vendor.pk)


@login_required
@vendor_blocked
def document_delete(request, vendor_pk, pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    doc = get_object_or_404(VendorDocument, pk=pk, vendor=vendor, tenant=request.tenant)
    if request.method == 'POST':
        doc.delete()
        messages.success(request, 'Document deleted.')
    return redirect('vendors:vendor_detail', pk=vendor.pk)


@login_required
@vendor_blocked
def bank_add(request, vendor_pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    if request.method == 'POST':
        form = VendorBankAccountForm(request.POST)
        if form.is_valid():
            bank = form.save(commit=False)
            bank.tenant = request.tenant
            bank.vendor = vendor
            bank.save()
            messages.success(request, f'Bank account at "{bank.bank_name}" added.')
        else:
            messages.error(request, 'Could not add bank account: ' + str(form.errors))
    return redirect('vendors:vendor_detail', pk=vendor.pk)


@login_required
@vendor_blocked
def bank_delete(request, vendor_pk, pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    bank = get_object_or_404(VendorBankAccount, pk=pk, vendor=vendor, tenant=request.tenant)
    if request.method == 'POST':
        bank.delete()
        messages.success(request, 'Bank account deleted.')
    return redirect('vendors:vendor_detail', pk=vendor.pk)


# =================================================================
# Categories
# =================================================================

@login_required
@vendor_blocked
def category_list(request):
    if not request.tenant:
        return redirect('tenants:onboarding_start')
    qs = VendorCategory.objects.filter(tenant=request.tenant).annotate(
        vendor_count=Count('vendors'),
    )
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
    active = request.GET.get('active', '')
    if active == 'active':
        qs = qs.filter(is_active=True)
    elif active == 'inactive':
        qs = qs.filter(is_active=False)
    return render(request, 'vendors/categories/list.html', {
        'categories': qs.order_by('name'),
    })


@login_required
@vendor_blocked
def category_create(request):
    if request.method == 'POST':
        form = VendorCategoryForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.tenant = request.tenant
            obj.save()
            messages.success(request, f'Category "{obj.name}" created.')
            return redirect('vendors:category_list')
    else:
        form = VendorCategoryForm(tenant=request.tenant)
    return render(request, 'vendors/categories/form.html', {
        'form': form, 'title': 'New Vendor Category',
    })


@login_required
@vendor_blocked
def category_edit(request, pk):
    obj = get_object_or_404(VendorCategory, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = VendorCategoryForm(request.POST, instance=obj, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f'Category "{obj.name}" updated.')
            return redirect('vendors:category_list')
    else:
        form = VendorCategoryForm(instance=obj, tenant=request.tenant)
    return render(request, 'vendors/categories/form.html', {
        'form': form, 'title': f'Edit {obj.name}',
    })


@login_required
@vendor_blocked
def category_delete(request, pk):
    obj = get_object_or_404(VendorCategory, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        name = obj.name
        obj.delete()
        messages.success(request, f'Category {name} deleted.')
    return redirect('vendors:category_list')


# =================================================================
# Segments
# =================================================================

@login_required
@vendor_blocked
def segment_list(request):
    if not request.tenant:
        return redirect('tenants:onboarding_start')
    qs = VendorSegment.objects.filter(tenant=request.tenant).annotate(
        vendor_count=Count('vendors'),
    )
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
    return render(request, 'vendors/segments/list.html', {
        'segments': qs.order_by('name'),
    })


@login_required
@vendor_blocked
def segment_create(request):
    if request.method == 'POST':
        form = VendorSegmentForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.tenant = request.tenant
            obj.save()
            messages.success(request, f'Segment "{obj.name}" created.')
            return redirect('vendors:segment_list')
    else:
        form = VendorSegmentForm(tenant=request.tenant)
    return render(request, 'vendors/segments/form.html', {
        'form': form, 'title': 'New Vendor Segment',
    })


@login_required
@vendor_blocked
def segment_edit(request, pk):
    obj = get_object_or_404(VendorSegment, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = VendorSegmentForm(request.POST, instance=obj, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f'Segment "{obj.name}" updated.')
            return redirect('vendors:segment_list')
    else:
        form = VendorSegmentForm(instance=obj, tenant=request.tenant)
    return render(request, 'vendors/segments/form.html', {
        'form': form, 'title': f'Edit {obj.name}',
    })


@login_required
@vendor_blocked
def segment_delete(request, pk):
    obj = get_object_or_404(VendorSegment, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        name = obj.name
        obj.delete()
        messages.success(request, f'Segment {name} deleted.')
    return redirect('vendors:segment_list')


# =================================================================
# Risk profiling
# =================================================================

@login_required
@vendor_blocked
def risk_create(request, vendor_pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    if request.method == 'POST':
        form = VendorRiskAssessmentForm(request.POST)
        if form.is_valid():
            assessment = form.save(commit=False)
            assessment.tenant = request.tenant
            assessment.vendor = vendor
            assessment.assessed_by = request.user
            apply_risk_assessment(assessment, user=request.user)
            messages.success(
                request, f'Risk assessment saved — {assessment.get_level_display()}.',
            )
            return redirect('vendors:vendor_detail', pk=vendor.pk)
    else:
        form = VendorRiskAssessmentForm(initial={
            'assessment_date': timezone.localdate(),
        })
    return render(request, 'vendors/risk/form.html', {
        'form': form, 'vendor': vendor, 'title': f'New Risk Assessment — {vendor.legal_name}',
    })


@login_required
@vendor_blocked
def risk_detail(request, vendor_pk, pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    assessment = get_object_or_404(
        VendorRiskAssessment, pk=pk, vendor=vendor, tenant=request.tenant,
    )
    return render(request, 'vendors/risk/detail.html', {
        'vendor': vendor, 'assessment': assessment,
    })


@login_required
@vendor_blocked
def risk_delete(request, vendor_pk, pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    assessment = get_object_or_404(
        VendorRiskAssessment, pk=pk, vendor=vendor, tenant=request.tenant,
    )
    if request.method == 'POST':
        was_current = assessment.is_current
        assessment.delete()
        if was_current:
            # promote the next latest
            nxt = vendor.risk_assessments.first()
            if nxt:
                apply_risk_assessment(nxt, user=request.user)
            else:
                vendor.risk_level = 'low'
                vendor.risk_score = 0
                vendor.save(update_fields=['risk_level', 'risk_score', 'updated_at'])
        messages.success(request, 'Risk assessment deleted.')
    return redirect('vendors:vendor_detail', pk=vendor.pk)


# =================================================================
# Onboarding — PUBLIC apply + admin review queue
# =================================================================

def onboarding_apply(request, tenant_slug):
    """Public-facing supplier application. No login required."""
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    # The middleware doesn't know about this anonymous request; set scope so
    # TenantManager works during the save.
    set_current_tenant(tenant)
    if request.method == 'POST':
        form = VendorOnboardingApplicationForm(request.POST)
        if form.is_valid():
            app = form.save(commit=False)
            app.tenant = tenant
            app.status = 'submitted'
            app.save()
            return redirect('vendors:onboarding_applied', tenant_slug=tenant.slug)
    else:
        form = VendorOnboardingApplicationForm()
    return render(request, 'vendors/onboarding/apply.html', {
        'form': form, 'tenant': tenant,
    })


def onboarding_applied(request, tenant_slug):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    return render(request, 'vendors/onboarding/applied.html', {'tenant': tenant})


@login_required
@vendor_blocked
def onboarding_list(request):
    if not request.tenant:
        return redirect('tenants:onboarding_start')
    qs = VendorOnboardingApplication.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(company_name__icontains=q) | Q(contact_email__icontains=q)
            | Q(tax_id__icontains=q)
        )
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    apply_url = request.build_absolute_uri(
        f'/vendors/onboarding/apply/{request.tenant.slug}/'
    )
    return render(request, 'vendors/onboarding/list.html', {
        'applications': qs.order_by('-submitted_at'),
        'status_choices': VendorOnboardingApplication._meta.get_field('status').choices,
        'apply_url': apply_url,
    })


@login_required
@vendor_blocked
def onboarding_detail(request, pk):
    application = get_object_or_404(
        VendorOnboardingApplication, pk=pk, tenant=request.tenant,
    )
    if request.method == 'POST':
        form = OnboardingReviewForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            notes = form.cleaned_data.get('notes') or ''
            if notes:
                application.review_notes = (
                    (application.review_notes + '\n' if application.review_notes else '')
                    + notes
                )
            if action == 'approve':
                vendor = convert_application_to_vendor(application, request.user)
                application.review_notes = application.review_notes  # already saved
                application.save(update_fields=['review_notes'])
                messages.success(
                    request,
                    f'Application approved. Vendor {vendor.vendor_number} created.',
                )
                return redirect('vendors:vendor_detail', pk=vendor.pk)
            elif action == 'reject':
                reject_application(
                    application, request.user, form.cleaned_data['rejection_reason'],
                )
                application.review_notes = application.review_notes
                application.save(update_fields=['review_notes'])
                messages.success(request, 'Application rejected.')
                return redirect('vendors:onboarding_list')
            else:  # under_review
                application.status = 'under_review'
                application.reviewed_by = request.user
                application.reviewed_at = timezone.now()
                application.save()
                messages.info(request, 'Application marked under review.')
                return redirect('vendors:onboarding_detail', pk=application.pk)
    else:
        form = OnboardingReviewForm()
    return render(request, 'vendors/onboarding/detail.html', {
        'application': application, 'form': form,
    })


# =================================================================
# Blacklisting / suspension
# =================================================================

@login_required
@vendor_blocked
def blacklist_action(request, vendor_pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    if request.method == 'POST':
        form = VendorBlacklistEventForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            kwargs = {
                'user': request.user,
                'reason': form.cleaned_data['reason'],
                'effective_date': form.cleaned_data['effective_date'],
                'notes': form.cleaned_data.get('notes', ''),
            }
            if action == 'suspend':
                suspend_vendor(
                    vendor, end_date=form.cleaned_data.get('end_date'), **kwargs,
                )
                messages.success(request, f'{vendor.legal_name} suspended.')
            elif action == 'blacklist':
                blacklist_vendor(vendor, **kwargs)
                messages.success(request, f'{vendor.legal_name} blacklisted.')
            else:  # reinstate
                reinstate_vendor(vendor, **kwargs)
                messages.success(request, f'{vendor.legal_name} reinstated.')
        else:
            messages.error(request, 'Could not record action: ' + str(form.errors))
    return redirect('vendors:vendor_detail', pk=vendor.pk)


@login_required
@vendor_blocked
def blacklist_history(request):
    if not request.tenant:
        return redirect('tenants:onboarding_start')
    qs = VendorBlacklistEvent.objects.filter(
        tenant=request.tenant,
    ).select_related('vendor', 'actioned_by')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(vendor__legal_name__icontains=q) | Q(reason__icontains=q)
        )
    action = request.GET.get('action', '')
    if action:
        qs = qs.filter(action=action)
    return render(request, 'vendors/blacklist/history.html', {
        'events': qs.order_by('-effective_date', '-created_at'),
        'action_choices': VendorBlacklistEvent.ACTION_CHOICES,
    })


# =================================================================
# Portal invites (admin -> creates portal user, returns one-time password)
# =================================================================

@login_required
@vendor_blocked
def portal_invite(request, vendor_pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    if request.method == 'POST':
        form = VendorPortalInviteForm(request.POST)
        if form.is_valid():
            try:
                portal, raw = invite_to_portal(
                    vendor, user=request.user, email=form.cleaned_data.get('email'),
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f'Portal account ready for {portal.email}. '
                    f'Username: {portal.username}  |  One-time password: {raw}',
                )
        else:
            messages.error(request, 'Invalid form: ' + str(form.errors))
    return redirect('vendors:vendor_detail', pk=vendor.pk)


@login_required
@vendor_blocked
def portal_revoke(request, vendor_pk):
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    if request.method == 'POST':
        revoke_portal_access(vendor, user=request.user)
        messages.success(request, 'Portal access revoked.')
    return redirect('vendors:vendor_detail', pk=vendor.pk)


# =================================================================
# VENDOR PORTAL (separate shell)
# =================================================================

@vendor_required
def portal_dashboard(request):
    from datetime import timedelta
    vendor = request.user.vendor
    open_docs = vendor.documents.filter(is_verified=False).count()
    expiring = vendor.documents.filter(
        expires_at__lte=timezone.localdate() + timedelta(days=60),
        expires_at__gte=timezone.localdate(),
    ).count()
    return render(request, 'vendor_portal/dashboard.html', {
        'vendor': vendor,
        'open_docs': open_docs,
        'expiring_docs': expiring,
        'recent_events': vendor.blacklist_events.all()[:5],
        'latest_risk': vendor.risk_assessments.filter(is_current=True).first(),
    })


@vendor_required
def portal_profile(request):
    vendor = request.user.vendor
    return render(request, 'vendor_portal/profile.html', {'vendor': vendor})


@vendor_required
def portal_profile_edit(request):
    vendor = request.user.vendor
    if request.method == 'POST':
        form = VendorPortalProfileForm(request.POST, instance=vendor)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('vendor_portal:profile')
    else:
        form = VendorPortalProfileForm(instance=vendor)
    return render(request, 'vendor_portal/profile_edit.html', {
        'form': form, 'vendor': vendor,
    })


@vendor_required
def portal_documents(request):
    vendor = request.user.vendor
    if request.method == 'POST':
        form = VendorDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.tenant = vendor.tenant
            doc.vendor = vendor
            doc.save()
            messages.success(request, f'Document "{doc.title}" uploaded.')
            return redirect('vendor_portal:documents')
    else:
        form = VendorDocumentForm()
    return render(request, 'vendor_portal/documents.html', {
        'vendor': vendor,
        'documents': vendor.documents.all(),
        'form': form,
    })


@vendor_required
def portal_contacts(request):
    vendor = request.user.vendor
    if request.method == 'POST':
        form = VendorContactForm(request.POST)
        if form.is_valid():
            c = form.save(commit=False)
            c.tenant = vendor.tenant
            c.vendor = vendor
            c.save()
            messages.success(request, 'Contact added.')
            return redirect('vendor_portal:contacts')
    else:
        form = VendorContactForm()
    return render(request, 'vendor_portal/contacts.html', {
        'vendor': vendor,
        'contacts': vendor.contacts.all(),
        'form': form,
    })
