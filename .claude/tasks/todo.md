# NavPMS — Procurement Management System: Foundation + Module 1 Build Plan

**Created:** 2026-05-19
**Scope:** Foundation (Django scaffold, multi-tenancy, auth, user management, themed dashboard) + Module 1 (Tenant & Subscription Management — all 5 sub-modules)
**Reference:** Replicate UI/architecture patterns from `C:\xampp\htdocs\NavMSM`
**Theme:** Blue (#3b5de7) + White, Bootstrap 5.3 + RemixIcon
**Database:** MySQL via XAMPP (host=127.0.0.1, port=3306, user=root, password=, db=navpms)
**Payment Gateway:** Mock (pluggable interface, swappable for Stripe/PayPal later)

---

## PHASE 0 — Pre-flight (1 file)
- [ ] Update `.gitignore` to ignore venv/, *.pyc, __pycache__/, .env, db.sqlite3, media/, staticfiles/, .pytest_cache/

## PHASE 1 — Project Setup (8 files)
- [ ] `requirements.txt` — Django 4.2, mysqlclient, python-decouple, django-crispy-forms, crispy-bootstrap5, Pillow, Faker
- [ ] `.env.example` — placeholder env values
- [ ] `.env` — actual XAMPP defaults
- [ ] `manage.py` — standard Django entry
- [ ] `config/__init__.py`
- [ ] `config/settings.py` — INSTALLED_APPS, MIDDLEWARE (incl. TenantMiddleware), MySQL via decouple, AUTH_USER_MODEL='accounts.User', LOGIN_URL, STATIC/MEDIA, crispy_forms, context processors
- [ ] `config/urls.py` — root URL mounts: '/' → dashboard, '/accounts/' → auth+users, '/tenants/' → Module 1, '/admin/'
- [ ] `config/wsgi.py` + `config/asgi.py` (2 files actually = 9 in phase)

## PHASE 2 — Core App (Multi-tenancy infrastructure) (12 files)
- [ ] `apps/__init__.py`
- [ ] `apps/core/__init__.py`
- [ ] `apps/core/apps.py`
- [ ] `apps/core/models.py` — `TimeStampedModel` (abstract), `Tenant` (name, slug, domain, is_active, plan FK lazy ref, created_at), `TenantManager` (auto-filter by thread-local), `TenantAwareModel` (abstract with tenant FK + TenantManager + all_objects)
- [ ] `apps/core/middleware.py` — `TenantMiddleware` sets `request.tenant` + thread-local
- [ ] `apps/core/context_processors.py` — passes `tenant`, `branding`, `theme_settings` (from user profile defaults) to all templates
- [ ] `apps/core/mixins.py` — `TenantRequiredMixin`, `TenantAdminRequiredMixin`, `SuperAdminRequiredMixin`
- [ ] `apps/core/utils.py` — thread-local set/get current tenant, slug helpers
- [ ] `apps/core/views.py` — dashboard view (renders home with stats widgets)
- [ ] `apps/core/urls.py` — '/' → dashboard
- [ ] `apps/core/admin.py` — register Tenant
- [ ] `apps/core/migrations/__init__.py`

## PHASE 3 — Accounts App (Custom User, Auth, User Management) (16 files)
- [ ] `apps/accounts/__init__.py`
- [ ] `apps/accounts/apps.py`
- [ ] `apps/accounts/models.py` — `User(AbstractUser)` with tenant FK, role choices (super_admin/tenant_admin/manager/buyer/approver/viewer), avatar, phone, job_title, is_tenant_admin; `UserProfile` (1-to-1 to User) with theme/layout/sidebar_color/sidebar_size/topbar_color/layout_width/layout_position/direction; `UserInvite` (tenant FK, email, role, token UUID, status, expires_at, invited_by)
- [ ] `apps/accounts/forms.py` — LoginForm, RegisterForm (creates tenant + super-admin), ForgotPasswordForm, ResetPasswordForm, UserCreateForm, UserEditForm, UserInviteForm, AcceptInviteForm, ProfileForm, ChangePasswordForm
- [ ] `apps/accounts/views.py` — login_view, logout_view, register_view, forgot_password_view, reset_password_view, user_list, user_create, user_detail, user_edit, user_delete, invite_list, invite_create, invite_resend, invite_cancel, accept_invite, profile_view, profile_edit, profile_security, profile_appearance (saves theme settings)
- [ ] `apps/accounts/urls.py` — all auth + user/invite/profile routes
- [ ] `apps/accounts/admin.py` — register User, UserProfile, UserInvite
- [ ] `apps/accounts/signals.py` — auto-create UserProfile on User save (post_save)
- [ ] `apps/accounts/mixins.py` — UserAdminRequiredMixin (optional)
- [ ] `apps/accounts/migrations/__init__.py`
- [ ] `apps/accounts/management/__init__.py`
- [ ] `apps/accounts/management/commands/__init__.py`
- [ ] `apps/accounts/management/commands/seed_users.py` — creates super_admin user, demo tenant admins, demo staff users with Faker

## PHASE 4 — Tenants App (Module 1: Tenant & Subscription Management) (14 files)
- [ ] `apps/tenants/__init__.py`
- [ ] `apps/tenants/apps.py`
- [ ] `apps/tenants/models.py` —
  - `Plan` (name, slug, price, billing_cycle [monthly/yearly], max_users, max_storage_gb, features JSON, is_active, sort_order)
  - `Subscription` (tenant FK, plan FK, status [trial/active/past_due/cancelled/expired], started_at, current_period_start, current_period_end, trial_ends_at, cancel_at_period_end, auto_renew)
  - `Invoice` (tenant FK, subscription FK, number auto-gen INV-00001, amount, tax, total, status [draft/sent/paid/overdue/void], issued_at, due_at, paid_at, line_items JSON)
  - `Transaction` (tenant FK, invoice FK, gateway_ref, amount, status [pending/succeeded/failed/refunded], gateway, method, created_at)
  - `BrandingSettings` (tenant 1-to-1, logo image, logo_dark, favicon, primary_color, secondary_color, login_bg image, email_from_name, email_from_address, email_signature)
  - `SecuritySettings` (tenant 1-to-1, password_min_length, password_require_special, mfa_required, session_timeout_minutes, ip_whitelist text, allowed_login_domains)
  - `AuditLog` (tenant FK, user FK, action, target_type, target_id, ip_address, user_agent, payload JSON, created_at)
  - `HealthMetric` (tenant FK, metric_type [user_count/storage_mb/api_calls/active_sessions], value, recorded_at)
- [ ] `apps/tenants/forms.py` — PlanForm, SubscriptionAssignForm, BrandingForm (with image uploads), SecurityForm, OnboardingCompanyForm, OnboardingPlanForm
- [ ] `apps/tenants/gateways.py` — `PaymentGateway` abstract base, `MockGateway` (sleeps 0.5s then returns success, generates fake gateway_ref)
- [ ] `apps/tenants/services.py` — `create_invoice_for_subscription`, `mark_invoice_paid`, `charge_subscription`, `record_audit_log`, `record_health_metric`, `compute_tenant_usage_stats`
- [ ] `apps/tenants/views.py` —
  - Plans: plan_list, plan_create, plan_detail, plan_edit, plan_delete (super-admin only)
  - Subscriptions: subscription_list (super-admin sees all, tenant_admin sees own), subscription_detail, subscription_assign, subscription_cancel
  - Invoices: invoice_list, invoice_detail, invoice_pay (calls gateway), invoice_download_pdf (stub)
  - Onboarding: onboarding_start, onboarding_company, onboarding_plan, onboarding_complete (wizard saves session, creates tenant + subscription + super-admin in final step)
  - Branding: branding_edit
  - Security: security_edit
  - Monitoring: monitoring_dashboard (usage charts), audit_log_list (with filters)
- [ ] `apps/tenants/urls.py` — all routes namespaced under `tenants:`
- [ ] `apps/tenants/admin.py` — register all models
- [ ] `apps/tenants/migrations/__init__.py`
- [ ] `apps/tenants/management/__init__.py`
- [ ] `apps/tenants/management/commands/__init__.py`
- [ ] `apps/tenants/management/commands/seed_plans.py` — creates Free, Starter, Professional, Enterprise plans
- [ ] `apps/tenants/management/commands/seed_tenants.py` — creates 3 demo tenants (Acme, Globex, Stark) with subscriptions, invoices, branding, audit logs, health metrics
- [ ] `apps/core/management/__init__.py` + `apps/core/management/commands/__init__.py` + `apps/core/management/commands/seed_data.py` (master orchestrator that calls seed_plans → seed_tenants → seed_users) — counted in PHASE 2/4 above

## PHASE 5 — Base Templates + Partials + Auth Templates (16 files)
- [ ] `templates/base.html` — html with all data-* attributes (data-layout, data-theme, data-topbar, data-sidebar, data-sidebar-size, data-layout-width, data-layout-position, dir), Bootstrap 5 + RemixIcon CDN, includes preloader/topbar/sidebar/footer/theme_settings
- [ ] `templates/base_auth.html` — minimal auth shell (centered card, branding logo)
- [ ] `templates/partials/preloader.html`
- [ ] `templates/partials/topbar.html` — logo, hamburger, search, notifications dropdown, user dropdown, theme toggle (light/dark), settings cog
- [ ] `templates/partials/sidebar.html` — logo, vertical menu: Dashboard / Tenants (Plans, Subscriptions, Invoices, Onboarding, Branding, Security, Monitoring) / Users (Users, Invites) / Profile — with role-based visibility
- [ ] `templates/partials/footer.html`
- [ ] `templates/partials/theme_settings.html` — offcanvas with radio buttons for layout/topbar/sidebar/sidebar-size/layout-width/layout-position/direction + "Reset Defaults" button
- [ ] `templates/partials/_pagination.html` — reusable pagination component
- [ ] `templates/partials/_messages.html` — Django messages framework alerts
- [ ] `templates/auth/login.html`
- [ ] `templates/auth/register.html` (tenant-creating registration → first user becomes tenant_admin)
- [ ] `templates/auth/forgot_password.html`
- [ ] `templates/auth/reset_password.html`
- [ ] `templates/auth/reset_password_done.html`
- [ ] `templates/auth/reset_password_complete.html`
- [ ] `templates/auth/accept_invite.html`

## PHASE 6 — Dashboard + User Management Templates (9 files)
- [ ] `templates/dashboard/index.html` — welcome card, stats widgets (active subs, MRR, pending invoices, user count), recent activity feed, quick actions
- [ ] `templates/accounts/users/list.html` — search, role filter, active filter, table with action column (view/edit/delete)
- [ ] `templates/accounts/users/form.html` — create/edit (one template)
- [ ] `templates/accounts/users/detail.html`
- [ ] `templates/accounts/invites/list.html` — pending/accepted/expired filter, actions (resend/cancel)
- [ ] `templates/accounts/invites/form.html`
- [ ] `templates/accounts/profile/view.html`
- [ ] `templates/accounts/profile/edit.html`
- [ ] `templates/accounts/profile/security.html` — change password

## PHASE 7 — Module 1 Templates (15 files)
- [ ] `templates/tenants/onboarding/start.html` — wizard step 1 (welcome + start)
- [ ] `templates/tenants/onboarding/company.html` — step 2 (company name, slug, domain, contact)
- [ ] `templates/tenants/onboarding/plan.html` — step 3 (pick a plan, optional trial)
- [ ] `templates/tenants/onboarding/complete.html` — finish (creates tenant + super-admin user + initial subscription)
- [ ] `templates/tenants/plans/list.html` — public pricing-like cards + admin CRUD table toggle
- [ ] `templates/tenants/plans/form.html`
- [ ] `templates/tenants/plans/detail.html`
- [ ] `templates/tenants/subscriptions/list.html`
- [ ] `templates/tenants/subscriptions/detail.html`
- [ ] `templates/tenants/subscriptions/form.html` — assign/change plan
- [ ] `templates/tenants/invoices/list.html`
- [ ] `templates/tenants/invoices/detail.html` — line items, Pay Now button (mock gateway)
- [ ] `templates/tenants/branding/edit.html` — logo/favicon uploads, color pickers, email branding
- [ ] `templates/tenants/security/edit.html` — password policy, MFA, IP whitelist, session timeout
- [ ] `templates/tenants/monitoring/dashboard.html` — usage charts (Chart.js CDN), tenant health summary
- [ ] `templates/tenants/monitoring/audit_logs.html` — searchable/filterable audit log table

## PHASE 8 — Static Files (7 files)
- [ ] `static/css/style.css` — CSS variables for theme (light/dark, blue/white palette), sidebar variants (default/compact/small/hover), topbar variants, layout-width (fluid/boxed), layout-position (fixed/scrollable), RTL overrides, custom components (cards, badges, tables, buttons)
- [ ] `static/css/auth.css` — auth page background, centered card
- [ ] `static/js/app.js` — theme manager (load from localStorage → set data-* attrs, sync radios in offcanvas, save on change), sidebar toggle, dropdown init
- [ ] `static/js/auth.js` — password show/hide, form validation hints
- [ ] `static/images/logo.svg` — wordmark + icon (blue)
- [ ] `static/images/logo-dark.svg` — same wordmark for dark sidebar
- [ ] `static/images/favicon.png`

## PHASE 9 — Documentation (2 files)
- [ ] `README.md` — full canonical docs: setup, env vars, MySQL XAMPP database creation, migrations, seeding, login credentials, screenshots placeholders, module list with roadmap, management commands table, project structure
- [ ] `.claude/tasks/lessons.md` — empty initially, will populate as session corrections arrive

## TOTAL FILE COUNT: ~99 files
(Each gets its own `git add` + `git commit` snippet per CLAUDE.md rules)

---

## Implementation Order
1. **Phase 0–1** first (project scaffolding) — gets the Django app bootable
2. **Phase 2** (core multi-tenancy) — load-bearing for everything
3. **Phase 3** (accounts) — needed before any view requires auth
4. **Phase 8** (static CSS/JS) — done early so templates can reference them
5. **Phase 5** (base + auth templates) — base.html depends on context processors
6. **Phase 4** (tenants app backend) — Module 1 backend
7. **Phase 6 + 7** (templates) — UI for users + Module 1
8. **Phase 9** (README + lessons) — final
9. **Run migrations & seed** — verify everything works
10. **Hand off git commit snippets** — one per file, PowerShell-safe

---

## Verification Checklist (run after build)
- [ ] `python manage.py makemigrations` — clean
- [ ] `python manage.py migrate` — clean
- [ ] `python manage.py seed_data` — creates plans + tenants + users + invoices
- [ ] `python manage.py runserver` — boots without error
- [ ] Login as `admin_acme / Welcome@123` → dashboard shows tenant data
- [ ] Theme toggle in offcanvas works (layout/sidebar/dark mode persist)
- [ ] CRUD on Plans/Users/Invites end-to-end
- [ ] Onboarding wizard creates a fresh tenant + super-admin
- [ ] Mock gateway "pays" an invoice and marks it paid
- [ ] Audit log records actions

---

## Out of Scope (not in this build)
- Real Stripe/PayPal integration (mock only — pluggable for later)
- Modules 2–20 (User Dashboard widgets, Requisitions, Approval Workflow, Vendors, Sourcing, RFx, E-Auction, Contracts, Catalog, PO, Fulfillment, GR, Invoicing, Spend Analytics, Budget, Supplier Performance, Risk/Compliance, Inventory, Document Mgmt, System Admin)
- True schema-per-tenant isolation (shared schema with `tenant_id` FK — same as NavMSM)
- SSO / LDAP / OAuth (only username+password auth)
- Email sending (console backend in dev)
- PDF invoice generation (stub button only)
- Real-time WebSockets / notifications
- Test suite (manual verification only this round)
