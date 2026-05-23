"""Auth, user management, profile, and invite views."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, authenticate, logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.views import View
from django.views.generic import ListView

from apps.core.mixins import TenantAdminRequiredMixin
from .models import User, UserProfile, UserInvite
from .forms import (
    LoginForm, RegistrationForm, ForgotPasswordForm, ResetPasswordForm,
    AcceptInviteForm, UserForm, UserProfileForm, UserInviteForm,
    ChangePasswordForm,
)


# ---------- Auth ----------

class LoginView(View):
    template_name = 'auth/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(self._post_login_target(request.user))
        return render(request, self.template_name, {'form': LoginForm()})

    @staticmethod
    def _post_login_target(user):
        if getattr(user, 'is_vendor_user', False):
            return 'vendor_portal:dashboard'
        return 'dashboard'

    def post(self, request):
        form = LoginForm(request.POST)
        if form.is_valid():
            ident = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=ident, password=password)
            if user is None:
                found = User.objects.filter(email__iexact=ident).first()
                if found is not None:
                    user = authenticate(request, username=found.username, password=password)
            if user is not None and user.is_active:
                login(request, user)
                if not form.cleaned_data.get('remember_me'):
                    request.session.set_expiry(0)
                messages.success(
                    request,
                    f'Welcome back, {user.get_full_name() or user.username}!',
                )
                return redirect(self._post_login_target(user))
            messages.error(request, 'Invalid credentials or inactive account.')
        return render(request, self.template_name, {'form': form})


class LogoutView(View):
    def get(self, request):
        return self.post(request)

    def post(self, request):
        logout(request)
        messages.info(request, 'You have been logged out.')
        return redirect('accounts:login')


class RegisterView(View):
    template_name = 'auth/register.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, self.template_name, {'form': RegistrationForm()})

    def post(self, request):
        from apps.core.models import Tenant
        from apps.tenants.services import start_trial_for_new_tenant

        form = RegistrationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                tenant = Tenant.objects.create(
                    name=form.cleaned_data['company_name'],
                    email=form.cleaned_data['email'],
                )
                user = form.save(commit=False)
                user.tenant = tenant
                user.role = 'tenant_admin'
                user.is_tenant_admin = True
                user.set_password(form.cleaned_data['password1'])
                user.save()
                start_trial_for_new_tenant(tenant)

            login(request, user)
            messages.success(request, 'Account created. Welcome to NavPMS!')
            return redirect('dashboard')
        return render(request, self.template_name, {'form': form})


class ForgotPasswordView(View):
    template_name = 'auth/forgot_password.html'

    def get(self, request):
        return render(request, self.template_name, {'form': ForgotPasswordForm()})

    def post(self, request):
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].strip().lower()
            user = User.objects.filter(email__iexact=email).first()
            if user is not None:
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_url = request.build_absolute_uri(
                    reverse(
                        'accounts:reset_password',
                        kwargs={'uidb64': uid, 'token': token},
                    )
                )
                send_mail(
                    subject='Reset your NavPMS password',
                    message=(
                        f'Use this link to reset your password:\n\n{reset_url}\n\n'
                        'If you did not request this, ignore this email.'
                    ),
                    from_email=None,
                    recipient_list=[user.email],
                    fail_silently=True,
                )
            messages.success(
                request,
                'If that email is registered you will receive a reset link.',
            )
            return redirect('accounts:login')
        return render(request, self.template_name, {'form': form})


class ResetPasswordView(View):
    template_name = 'auth/reset_password.html'

    def _get_user(self, uidb64, token):
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return None
        if not default_token_generator.check_token(user, token):
            return None
        return user

    def get(self, request, uidb64, token):
        user = self._get_user(uidb64, token)
        if user is None:
            messages.error(request, 'This reset link is invalid or expired.')
            return redirect('accounts:forgot_password')
        return render(request, self.template_name, {'form': ResetPasswordForm()})

    def post(self, request, uidb64, token):
        user = self._get_user(uidb64, token)
        if user is None:
            messages.error(request, 'This reset link is invalid or expired.')
            return redirect('accounts:forgot_password')
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data['password1'])
            user.save()
            messages.success(request, 'Password updated. Please sign in.')
            return redirect('accounts:login')
        return render(request, self.template_name, {'form': form})


# ---------- User management ----------

class UserListView(TenantAdminRequiredMixin, ListView):
    model = User
    template_name = 'accounts/users/list.html'
    context_object_name = 'users'
    paginate_by = 20

    def get_queryset(self):
        qs = User.objects.filter(tenant=self.request.tenant)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
                | Q(username__icontains=q)
            )
        role = self.request.GET.get('role', '')
        if role:
            qs = qs.filter(role=role)
        active = self.request.GET.get('active', '')
        if active == 'active':
            qs = qs.filter(is_active=True)
        elif active == 'inactive':
            qs = qs.filter(is_active=False)
        return qs.order_by('first_name', 'last_name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['role_choices'] = User.ROLE_CHOICES
        return ctx


class UserCreateView(TenantAdminRequiredMixin, View):
    def get(self, request):
        return render(request, 'accounts/users/form.html', {
            'form': UserForm(), 'title': 'Add User',
        })

    def post(self, request):
        form = UserForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save(commit=False)
            user.tenant = request.tenant
            user.set_password('Welcome@123')
            user.save()
            messages.success(
                request,
                f'User {user} created. Temporary password: Welcome@123',
            )
            return redirect('accounts:user_list')
        return render(request, 'accounts/users/form.html', {
            'form': form, 'title': 'Add User',
        })


class UserDetailView(TenantAdminRequiredMixin, View):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk, tenant=request.tenant)
        return render(request, 'accounts/users/detail.html', {'user_obj': user})


class UserEditView(TenantAdminRequiredMixin, View):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk, tenant=request.tenant)
        return render(request, 'accounts/users/form.html', {
            'form': UserForm(instance=user),
            'title': 'Edit User',
            'edit_user': user,
        })

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk, tenant=request.tenant)
        form = UserForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f'{user} updated.')
            return redirect('accounts:user_list')
        return render(request, 'accounts/users/form.html', {
            'form': form, 'title': 'Edit User', 'edit_user': user,
        })


class UserDeleteView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk, tenant=request.tenant)
        if user == request.user:
            messages.error(request, 'You cannot delete your own account.')
            return redirect('accounts:user_list')
        user.delete()
        messages.success(request, 'User deleted.')
        return redirect('accounts:user_list')

    def get(self, request, pk):
        return redirect('accounts:user_list')


class UserToggleActiveView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk, tenant=request.tenant)
        if user == request.user:
            messages.error(request, 'You cannot deactivate your own account.')
            return redirect('accounts:user_list')
        user.is_active = not user.is_active
        user.save()
        state = 'activated' if user.is_active else 'deactivated'
        messages.success(request, f'User {state}.')
        return redirect('accounts:user_list')


# ---------- Profile ----------

class UserProfileView(LoginRequiredMixin, View):
    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return render(request, 'accounts/profile/view.html', {'profile': profile})


class UserProfileEditView(LoginRequiredMixin, View):
    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return render(request, 'accounts/profile/edit.html', {
            'user_form': UserForm(instance=request.user),
            'profile_form': UserProfileForm(instance=profile),
        })

    def post(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        user_form = UserForm(request.POST, request.FILES, instance=request.user)
        profile_form = UserProfileForm(request.POST, instance=profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Profile updated.')
            return redirect('accounts:profile')
        return render(request, 'accounts/profile/edit.html', {
            'user_form': user_form, 'profile_form': profile_form,
        })


class ChangePasswordView(LoginRequiredMixin, View):
    template_name = 'accounts/profile/security.html'

    def get(self, request):
        return render(request, self.template_name, {
            'form': ChangePasswordForm(user=request.user),
        })

    def post(self, request):
        form = ChangePasswordForm(request.POST, user=request.user)
        if form.is_valid():
            request.user.set_password(form.cleaned_data['password1'])
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Password changed successfully.')
            return redirect('accounts:profile')
        return render(request, self.template_name, {'form': form})


# ---------- Invites ----------

class UserInviteListView(TenantAdminRequiredMixin, ListView):
    model = UserInvite
    template_name = 'accounts/invites/list.html'
    context_object_name = 'invites'
    paginate_by = 20

    def get_queryset(self):
        qs = UserInvite.objects.filter(tenant=self.request.tenant)
        status = self.request.GET.get('status', '')
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = UserInvite.STATUS_CHOICES
        return ctx


class UserInviteSendView(TenantAdminRequiredMixin, View):
    def get(self, request):
        return render(request, 'accounts/invites/form.html', {
            'form': UserInviteForm(),
        })

    def post(self, request):
        form = UserInviteForm(request.POST)
        if form.is_valid():
            invite = form.save(commit=False)
            invite.tenant = request.tenant
            invite.invited_by = request.user
            invite.expires_at = timezone.now() + timedelta(days=7)
            invite.save()
            self._send_invite_email(request, invite)
            messages.success(request, f'Invitation sent to {invite.email}.')
            return redirect('accounts:invite_list')
        return render(request, 'accounts/invites/form.html', {'form': form})

    @staticmethod
    def _send_invite_email(request, invite):
        url = request.build_absolute_uri(
            reverse('accounts:accept_invite', kwargs={'token': invite.token})
        )
        send_mail(
            subject=f'You have been invited to {request.tenant.name} on NavPMS',
            message=(
                f'{request.user} invited you to join {request.tenant.name} on NavPMS.\n\n'
                f'Accept here: {url}\n\nThis link expires in 7 days.'
            ),
            from_email=None,
            recipient_list=[invite.email],
            fail_silently=True,
        )


class UserInviteCancelView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        invite = get_object_or_404(UserInvite, pk=pk, tenant=request.tenant)
        invite.status = 'cancelled'
        invite.save()
        messages.success(request, 'Invitation cancelled.')
        return redirect('accounts:invite_list')


class UserInviteResendView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        invite = get_object_or_404(UserInvite, pk=pk, tenant=request.tenant)
        invite.expires_at = timezone.now() + timedelta(days=7)
        invite.status = 'pending'
        invite.save()
        UserInviteSendView._send_invite_email(request, invite)
        messages.success(request, 'Invitation resent.')
        return redirect('accounts:invite_list')


class AcceptInviteView(View):
    template_name = 'auth/accept_invite.html'

    def _invite_or_none(self, request, token):
        invite = UserInvite.all_objects.filter(token=token, status='pending').first()
        if invite is None:
            messages.error(request, 'Invitation not found.')
            return None
        if invite.expires_at < timezone.now():
            invite.status = 'expired'
            invite.save()
            messages.error(request, 'This invitation has expired.')
            return None
        return invite

    def get(self, request, token):
        invite = self._invite_or_none(request, token)
        if invite is None:
            return redirect('accounts:login')
        return render(request, self.template_name, {
            'invite': invite, 'form': AcceptInviteForm(),
        })

    def post(self, request, token):
        invite = self._invite_or_none(request, token)
        if invite is None:
            return redirect('accounts:login')
        form = AcceptInviteForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = User.objects.create_user(
                    username=form.cleaned_data['username'],
                    email=invite.email,
                    password=form.cleaned_data['password1'],
                    first_name=form.cleaned_data['first_name'],
                    last_name=form.cleaned_data['last_name'],
                    tenant=invite.tenant,
                    role=invite.role,
                )
                invite.status = 'accepted'
                invite.accepted_at = timezone.now()
                invite.save()
            login(request, user)
            messages.success(request, 'Welcome! Your account has been created.')
            return redirect('dashboard')
        return render(request, self.template_name, {
            'invite': invite, 'form': form,
        })
