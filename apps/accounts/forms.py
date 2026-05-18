"""Auth, user, profile and invite forms."""
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User, UserProfile, UserInvite


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150, label='Username or email')
    password = forms.CharField(widget=forms.PasswordInput)
    remember_me = forms.BooleanField(required=False, initial=True)


class RegistrationForm(forms.ModelForm):
    """Tenant-creating registration: first user becomes tenant_admin."""

    company_name = forms.CharField(max_length=255)
    password1 = forms.CharField(widget=forms.PasswordInput, label='Password')
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm password')
    terms = forms.BooleanField(required=True, label='I agree to the Terms of Service')

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name')

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is taken.')
        return username

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2:
            if p1 != p2:
                raise ValidationError({'password2': 'Passwords do not match.'})
            try:
                validate_password(p1)
            except ValidationError as e:
                raise ValidationError({'password1': list(e.messages)})
        return cleaned


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField()


class ResetPasswordForm(forms.Form):
    password1 = forms.CharField(widget=forms.PasswordInput, label='New password')
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm new password')

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2:
            if p1 != p2:
                raise ValidationError({'password2': 'Passwords do not match.'})
            try:
                validate_password(p1)
            except ValidationError as e:
                raise ValidationError({'password1': list(e.messages)})
        return cleaned


class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(widget=forms.PasswordInput, label='Current password')
    password1 = forms.CharField(widget=forms.PasswordInput, label='New password')
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm new password')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_old_password(self):
        old = self.cleaned_data.get('old_password')
        if self.user is None or not self.user.check_password(old):
            raise ValidationError('Current password is incorrect.')
        return old

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2:
            if p1 != p2:
                raise ValidationError({'password2': 'Passwords do not match.'})
            try:
                validate_password(p1, user=self.user)
            except ValidationError as e:
                raise ValidationError({'password1': list(e.messages)})
        return cleaned


class AcceptInviteForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    username = forms.CharField(max_length=150)
    password1 = forms.CharField(widget=forms.PasswordInput, label='Password')
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm password')

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is taken.')
        return username

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2:
            if p1 != p2:
                raise ValidationError({'password2': 'Passwords do not match.'})
            try:
                validate_password(p1)
            except ValidationError as e:
                raise ValidationError({'password1': list(e.messages)})
        return cleaned


class UserForm(forms.ModelForm):
    """Tenant admin create/edit form for users."""

    class Meta:
        model = User
        fields = (
            'username', 'email', 'first_name', 'last_name',
            'role', 'phone', 'job_title', 'avatar', 'is_active',
        )


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = (
            'bio', 'date_of_birth', 'address', 'city', 'state',
            'country', 'zip_code',
            'theme', 'layout', 'sidebar_color', 'sidebar_size',
            'topbar_color', 'layout_width', 'layout_position', 'direction',
        )
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'bio': forms.Textarea(attrs={'rows': 3}),
            'address': forms.Textarea(attrs={'rows': 2}),
        }


class UserInviteForm(forms.ModelForm):
    class Meta:
        model = UserInvite
        fields = ('email', 'role')
