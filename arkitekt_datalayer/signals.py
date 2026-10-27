"""Bytes follow their store row out, however the row went.

``DatalayerStore.delete()`` and ``purge_orphaned_stores`` delete the bytes themselves. Every other
way a store row disappears -- an organization deleted and its stores cascading, a queryset
``delete()``, the admin's bulk action -- runs no model method, and used to leave bytes nothing
pointed at any more. This catches those.

**After the commit, never inside the transaction**, which is the rule ``storage`` is built on: a
delete that rolls back must find its bytes where it left them. A purge that fails after the
commit leaks, and says so in the log; it cannot be retried from a row that no longer exists.
"""

import logging
from typing import Any

from django.db import transaction
from django.db.models.signals import post_delete

logger = logging.getLogger(__name__)


def _purge_after_commit(sender: type, instance: Any, **kwargs: Any) -> None:  # noqa: ANN401 - Django's signal signature
    from arkitekt_datalayer.models import DatalayerStore

    # A store is always a subclass; the base row goes as its parent, and is the same bytes.
    if type(instance) is DatalayerStore or not isinstance(instance, DatalayerStore):
        return
    if getattr(instance, "_bytes_purged", False):
        return

    def purge() -> None:
        try:
            instance.purge_bytes()
        except Exception:  # noqa: BLE001 - the row is gone; the log is all that is left
            logger.exception("Could not delete the bytes of %s %s (%s/%s) after its row was deleted; they are now unreferenced.", type(instance).__name__, instance.pk, instance.bucket, instance.key)

    transaction.on_commit(purge)


def connect() -> None:
    """Connect the receiver to every store class (a polymorphic delete sends per concrete class)."""
    post_delete.connect(_purge_after_commit, dispatch_uid="arkitekt_datalayer.purge_after_commit")
