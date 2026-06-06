from django.contrib import admin

from .models import Document, DocumentEvent, DocumentVersion, PolicyTemplate


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    fk_name = 'document'
    fields = ['version_no', 'file', 'status', 'index_status', 'page_count', 'uploaded_by']
    raw_id_fields = ['uploaded_by', 'published_by']


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['document_number', 'title', 'category', 'status', 'confidentiality',
                    'owner', 'tenant']
    list_filter = ['tenant', 'status', 'category', 'confidentiality']
    search_fields = ['document_number', 'title', 'tags']
    raw_id_fields = ['owner', 'created_by', 'current_version']
    inlines = [DocumentVersionInline]


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ['document', 'version_no', 'status', 'index_status', 'page_count',
                    'extraction_engine', 'tenant']
    list_filter = ['tenant', 'status', 'index_status', 'extraction_engine']
    search_fields = ['document__document_number', 'original_filename']
    raw_id_fields = ['document', 'uploaded_by', 'published_by']


@admin.register(PolicyTemplate)
class PolicyTemplateAdmin(admin.ModelAdmin):
    list_display = ['template_number', 'title', 'category', 'status', 'owner', 'tenant']
    list_filter = ['tenant', 'status', 'category']
    search_fields = ['template_number', 'title']
    raw_id_fields = ['owner']


@admin.register(DocumentEvent)
class DocumentEventAdmin(admin.ModelAdmin):
    """Append-only document timeline."""

    list_display = ['document', 'event', 'from_status', 'to_status', 'actor', 'created_at', 'tenant']
    list_filter = ['tenant', 'event']
    search_fields = ['document__document_number', 'note']
    raw_id_fields = ['document', 'version', 'actor']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
