from django.apps import AppConfig


class DatalayerConfig(AppConfig):
    """The datalayer app: S3-backed stores, their grants, quotas and purge.

    Labelled ``datalayer`` rather than after its module, so table names (``datalayer_*``) and
    model references (``"datalayer.MediaStore"``) read the same in every service that installs it.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "arkitekt_datalayer"
    label = "datalayer"
    verbose_name = "Datalayer"

    def ready(self) -> None:
        """Purge a deleted store's bytes, whichever way its row went (see :mod:`arkitekt_datalayer.signals`)."""
        from arkitekt_datalayer import signals

        signals.connect()
