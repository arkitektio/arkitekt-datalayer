from django.apps import AppConfig


class TestAppConfig(AppConfig):
    """Data rows that reference stores, the way a service's domain models do."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "test_app"
