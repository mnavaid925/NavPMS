from django.apps import AppConfig


class AuctionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.auctions'
    label = 'auctions'
    verbose_name = 'E-Auction Management'
