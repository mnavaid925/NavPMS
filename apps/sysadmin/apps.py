from django.apps import AppConfig


class SysadminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sysadmin'
    label = 'sysadmin'
    verbose_name = 'System Administration & Security'
