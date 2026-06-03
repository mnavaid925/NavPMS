"""Module 10 vendor-portal views: a supplier's catalog + self-service uploads.

Mirrors :mod:`apps.contracts.portal_views`: every view is gated by
``@vendor_required`` and scoped to ``request.user.vendor`` and its tenant, so a
supplier can only ever see their own catalog items and uploads (cross-vendor
isolation). Uploads are parsed by ``services.process_catalog_upload`` into draft
items that then flow through the buyer's approval workflow.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.vendors.decorators import vendor_required

from . import services
from .forms import SupplierCatalogUploadForm
from .models import CatalogItem, SupplierCatalogUpload


@vendor_required
def portal_catalog_list(request):
    """This vendor's approved catalog items (read-only)."""
    vendor = request.user.vendor
    items = (
        CatalogItem.objects
        .filter(vendor=vendor, tenant=vendor.tenant, source='supplier')
        .select_related('category')
        .order_by('-created_at')
    )
    return render(request, 'vendor_portal/catalog/list.html', {
        'items': items, 'vendor': vendor,
    })


@vendor_required
def portal_upload_list(request):
    """This vendor's catalog file uploads."""
    vendor = request.user.vendor
    uploads = SupplierCatalogUpload.objects.filter(
        vendor=vendor, tenant=vendor.tenant).order_by('-created_at')
    return render(request, 'vendor_portal/catalog/upload_list.html', {
        'uploads': uploads, 'vendor': vendor,
    })


@vendor_required
def portal_upload_create(request):
    """Upload a CSV/XLSX catalog file (extension + size validated)."""
    vendor = request.user.vendor
    if request.method == 'POST':
        form = SupplierCatalogUploadForm(
            request.POST, request.FILES, tenant=vendor.tenant)
        if form.is_valid():
            upload = form.save(commit=False)
            upload.tenant = vendor.tenant
            upload.vendor = vendor
            upload.uploaded_by = request.user
            upload.original_filename = getattr(upload.file, 'name', '')[:255]
            upload.save()
            services.record_audit(
                vendor.tenant, request.user, 'catalog.upload.created',
                target_type='SupplierCatalogUpload', target_id=str(upload.pk),
                message=f'{vendor.legal_name} uploaded {upload.original_filename}',
                request=request)
            messages.success(
                request,
                'Catalog file uploaded. The buyer will review and import it.')
            return redirect('vendor_portal:catalog_upload_detail', pk=upload.pk)
    else:
        form = SupplierCatalogUploadForm(tenant=vendor.tenant)
    return render(request, 'vendor_portal/catalog/upload_form.html', {
        'form': form, 'vendor': vendor,
    })


@vendor_required
def portal_upload_detail(request, pk):
    """Status + per-row error log for one of this vendor's uploads."""
    vendor = request.user.vendor
    upload = get_object_or_404(
        SupplierCatalogUpload, pk=pk, tenant=vendor.tenant, vendor=vendor)
    return render(request, 'vendor_portal/catalog/upload_detail.html', {
        'upload': upload, 'vendor': vendor,
    })


@vendor_required
@require_POST
def portal_upload_delete(request, pk):
    """Remove an upload that has not been processed yet."""
    vendor = request.user.vendor
    upload = get_object_or_404(
        SupplierCatalogUpload, pk=pk, tenant=vendor.tenant, vendor=vendor)
    if not upload.is_open:
        messages.error(request, 'This upload has already been processed.')
        return redirect('vendor_portal:catalog_upload_detail', pk=upload.pk)
    upload.delete()
    messages.success(request, 'Upload removed.')
    return redirect('vendor_portal:catalog_uploads')
