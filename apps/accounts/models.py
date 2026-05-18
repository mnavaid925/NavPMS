"""Custom User (tenant-bound), UserProfile (theme prefs), UserInvite."""
import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.core.models import Tenant, TenantAwareModel, TimeStampedModel


class User(AbstractUser):
    """Tenant-bound user. tenant=NULL only for the Django superuser."""

    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('tenant_admin', 'Tenant Admin'),
        ('procurement_manager', 'Procurement Manager'),
        ('buyer', 'Buyer'),
        ('approver', 'Approver'),
        ('requester', 'Requester'),
        ('vendor_portal', 'Vendor Portal'),
        ('viewer', 'Viewer'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='users',
        null=True,
        blank=True,
    )
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='requester')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    is_tenant_admin = models.BooleanField(default=False)

    class Meta:
        ordering = ['first_name', 'last_name']

    def __str__(self):
        return self.get_full_name() or self.username

    def get_initials(self):
        if self.first_name and self.last_name:
            return f'{self.first_name[0]}{self.last_name[0]}'.upper()
        return (self.username[:2] or 'U').upper()


class UserProfile(TimeStampedModel):
    """Per-user UI preferences + biographical info."""

    THEME_CHOICES = [('light', 'Light'), ('dark', 'Dark')]
    LAYOUT_CHOICES = [
        ('vertical', 'Vertical'),
        ('horizontal', 'Horizontal'),
        ('detached', 'Detached'),
    ]
    SIDEBAR_SIZE_CHOICES = [
        ('default', 'Default'),
        ('compact', 'Compact'),
        ('small', 'Small Icon'),
        ('hover', 'Icon Hover'),
    ]
    SIDEBAR_COLOR_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('brand', 'Brand'),
    ]
    TOPBAR_COLOR_CHOICES = [('light', 'Light'), ('dark', 'Dark')]
    LAYOUT_WIDTH_CHOICES = [('fluid', 'Fluid'), ('boxed', 'Boxed')]
    LAYOUT_POSITION_CHOICES = [('fixed', 'Fixed'), ('scrollable', 'Scrollable')]
    DIRECTION_CHOICES = [('ltr', 'LTR'), ('rtl', 'RTL')]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)

    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default='light')
    layout = models.CharField(max_length=20, choices=LAYOUT_CHOICES, default='vertical')
    sidebar_color = models.CharField(
        max_length=20, choices=SIDEBAR_COLOR_CHOICES, default='light',
    )
    sidebar_size = models.CharField(
        max_length=20, choices=SIDEBAR_SIZE_CHOICES, default='default',
    )
    topbar_color = models.CharField(
        max_length=20, choices=TOPBAR_COLOR_CHOICES, default='light',
    )
    layout_width = models.CharField(
        max_length=20, choices=LAYOUT_WIDTH_CHOICES, default='fluid',
    )
    layout_position = models.CharField(
        max_length=20, choices=LAYOUT_POSITION_CHOICES, default='fixed',
    )
    direction = models.CharField(
        max_length=5, choices=DIRECTION_CHOICES, default='ltr',
    )

    def __str__(self):
        return f'Profile of {self.user}'


class UserInvite(TenantAwareModel, TimeStampedModel):
    """Email invitation, redeemable via UUID token."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    email = models.EmailField()
    role = models.CharField(
        max_length=30, choices=User.ROLE_CHOICES, default='requester',
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invited_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_invites',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending',
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Invite {self.email} ({self.status})'
