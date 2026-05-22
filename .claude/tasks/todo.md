# Module 2 — User Dashboard & Portal

**Created:** 2026-05-22
**Scope:** New Django app `apps/portal/` implementing the 5 PMS sub-modules of Module 2.

A new Django app `apps/portal/` implementing the 5 PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| Personalized Overview | `DashboardWidget` (per-user CRUD rows) + `/portal/` dashboard that renders enabled widgets |
| Task & Alert Center | `Notification` model — categorized, prioritized, read/unread |
| Quick Requisition Entry | `QuickRequisition` + `QuickRequisitionItem` (auto-numbered, status workflow, inline items) |
| Recent Activity Feed | Reuse `tenants.AuditLog` filtered by `user=request.user`; portal writes via `record_audit()` |
| Self-Service Reporting | `SavedReport` model + report-run view (spend/usage/activity charts) |

## Architecture decisions
- Per-user, NOT admin-only: views use `TenantRequiredMixin`; every query filters `tenant=request.tenant` AND `user=request.user`.
- Reuse `apps.tenants.services.record_audit` for the activity feed — no duplicate audit infra.
- Reuse `TenantAwareModel` / `TimeStampedModel` from `apps.core.models`.
- Mounted at `/portal/`. Root `/` dashboard stays unchanged.

## Models (`apps/portal/models.py`)
1. **DashboardWidget** — user, widget_type (pending_tasks/pending_approvals/spend_summary/recent_activity/notifications/quick_requisition/my_reports/quick_links), title, position, size (small/medium/large), is_visible.
2. **Notification** — user, category (deadline/approval/delivery/system/info), priority (low/normal/high/urgent), title, message, link_url, is_read, read_at.
3. **QuickRequisition** — user, number (QR-SLUG-00001), title, category, description, vendor_name, needed_by, priority, status (draft/submitted/approved/rejected/cancelled), justification, estimated_total, currency, submitted_at, decided_at/by, decision_note.
4. **QuickRequisitionItem** — requisition FK, name, quantity, unit, unit_price, line_total (tenant-aware child, managed inline).
5. **SavedReport** — user, name, report_type (spend_by_category/spend_by_month/requisition_status/my_activity/notification_summary), date_from, date_to, filters JSON, last_run_at.

## Tasks

### Backend — `apps/portal/`
- [ ] `__init__.py`
- [ ] `apps.py` — `PortalConfig`
- [ ] `models.py` — 5 models above
- [ ] `admin.py` — register all models
- [ ] `forms.py` — `DashboardWidgetForm`, `NotificationForm`, `QuickRequisitionForm`, `QuickRequisitionItemForm`, `SavedReportForm`
- [ ] `services.py` — `_next_requisition_number`, `recalc_requisition_total`, `create_notification`, `ensure_default_widgets`, `build_dashboard_context`, `generate_report`
- [ ] `views.py` — see view list below
- [ ] `urls.py` — `app_name = 'portal'`
- [ ] `migrations/__init__.py`
- [ ] `management/__init__.py`, `management/commands/__init__.py`
- [ ] `management/commands/seed_portal.py` — idempotent seed for widgets/notifications/requisitions/reports per tenant user

### Views (full CRUD per CLAUDE.md rules)
- Portal dashboard: `PortalDashboardView` (auto-creates default widgets on first visit)
- Widgets: `WidgetListView`, `WidgetCreateView`, `WidgetEditView`, `WidgetDeleteView`
- Notifications: `NotificationListView`, `NotificationDetailView`, `NotificationCreateView`, `NotificationEditView`, `NotificationDeleteView`, `NotificationMarkReadView`, `NotificationMarkAllReadView`
- Quick Requisition: `RequisitionListView`, `RequisitionCreateView`, `RequisitionDetailView`, `RequisitionEditView`, `RequisitionDeleteView`, `RequisitionSubmitView`, `RequisitionItemAddView`, `RequisitionItemDeleteView`
- Reports: `ReportListView`, `ReportCreateView`, `ReportEditView`, `ReportDeleteView`, `ReportRunView` (detail = generated report)
- Activity: `ActivityFeedView` (AuditLog filtered by user)

### Templates — `templates/portal/`
- [ ] `dashboard.html` — widget grid (hero + stat tiles, reuses dashboard styles)
- [ ] `widgets/list.html`, `widgets/form.html`
- [ ] `notifications/list.html`, `notifications/detail.html`, `notifications/form.html`
- [ ] `requisitions/list.html`, `requisitions/form.html`, `requisitions/detail.html` (inline item CRUD)
- [ ] `reports/list.html`, `reports/form.html`, `reports/detail.html` (Chart.js)
- [ ] `activity/feed.html`

### Wiring (modified files)
- [ ] `config/settings.py` — add `'apps.portal'` to `INSTALLED_APPS`
- [ ] `config/urls.py` — `path('portal/', include('apps.portal.urls'))`
- [ ] `templates/partials/sidebar.html` — new "User Portal" nav section
- [ ] `apps/core/management/commands/seed_data.py` — add `seed_portal` step
- [ ] `README.md` — Project Structure, Roadmap (Module 2 → Shipped), Routes, Management Commands, Seeded Data, new Module 2 section

### Verification
- [ ] `python manage.py makemigrations portal` + `migrate`
- [ ] `python manage.py seed_portal`
- [ ] `python manage.py check`
- [ ] Manual click-through: dashboard, all CRUD, filters, submit workflow, report run

## Review

**Status: complete & verified (2026-05-22).**

- New app `apps/portal/` with 5 models, services layer, full-CRUD views, urls, admin,
  and idempotent `seed_portal` command (wired into `seed_data` orchestrator).
- 13 templates under `templates/portal/`.
- Wiring: `INSTALLED_APPS`, `config/urls.py` (`/portal/`), sidebar "User Portal" section.
- `README.md` updated: intro, ToC, structure, commands, seeded data, Module 2 section,
  routes table, roadmap (Module 2 → Shipped).

**Verification performed:**
- `manage.py check` — 0 issues.
- `makemigrations portal` → `0001_initial` (5 models + 4 indexes); `migrate` OK.
- `seed_portal` — seeded widgets/notifications/requisitions/reports for all 3 tenants.
- Smoke test 1: all 16 portal GET routes + 3 report-run pages returned HTTP 200.
- Smoke test 2 (POST flows): create requisition → add item (total recalculated to 37.50)
  → submit (status=submitted) → edit correctly locked; mark-all-read cleared unread;
  all 5 report types computed without error.

**Design notes:**
- Activity Feed reuses `tenants.AuditLog` (filtered by user) — no duplicate audit infra.
  Portal create/submit actions call `record_audit()` so the feed populates organically.
- Quick Requisition is self-contained (Module 3 can later integrate/supersede it).
- All views scope by `tenant` AND `user`; drafts are the only mutable requisition state.
