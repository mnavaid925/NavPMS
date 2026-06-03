from django.apps import AppConfig


class PurchaseOrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.purchase_orders'
    label = 'purchase_orders'
    verbose_name = 'Purchase Order Management'
