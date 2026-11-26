"""Record the digest of every finished big file that does not have one yet.

A finish records the digest when that is cheap: the object store vouched for it (the upload
used the parts and the SHA-256 checksums its grant advertised), or the object is small. Every
other store owes it -- a file uploaded before digests were recorded, by a client that sent no
checksums, or one too large to read during a finish -- and this pays it, by streaming each
object once.

Long-running on a hub with much data (it reads every byte it owes), so it is not a setup job:
the service serves meanwhile, and a store without a digest is simply one not known yet. Safe
to interrupt and to run again: each store is recorded as soon as it is hashed, and a run
starts with what is still owed. ``--backlog`` reads only the database and says what is owed.
"""

import json
from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Count, Q, Sum

from arkitekt_datalayer.datalayer import get_current_datalayer
from arkitekt_datalayer.models import BigFileStore


def owed() -> "Any":  # noqa: ANN401 - a QuerySet of BigFileStore
    """The finished, live stores whose digest or sample is not recorded yet, smallest first."""
    return BigFileStore.objects.filter(
        Q(digest__isnull=True) | Q(sample__isnull=True),
        populated=True,
        orphaned_at__isnull=True,
    ).order_by("size_bytes", "pk")


class Command(BaseCommand):
    """Hash the big files whose digest is still owed."""

    help = "Record the digest of every finished big file that has none yet, streaming each object once. Long-running; safe to interrupt and run again."

    def add_arguments(self, parser) -> None:  # noqa: ANN001 - Django's ArgumentParser
        """Declare the command's options."""
        parser.add_argument(
            "--backlog",
            action="store_true",
            help="Print what is owed as JSON ({items, bytes}) and change nothing. Reads only the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            metavar="N",
            help="Hash at most N stores this run.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Hash what is owed, smallest first, and report what is left."""
        if options["backlog"]:
            totals = owed().aggregate(items=Count("pk"), bytes=Sum("size_bytes"))
            self.stdout.write(
                json.dumps({"items": totals["items"], "bytes": totals["bytes"] or 0})
            )
            return

        layer = get_current_datalayer()
        stores = owed()
        if options["limit"]:
            stores = stores[: options["limit"]]

        recorded = failed = 0
        for store in stores.iterator():
            try:
                store.record_digest(layer, stream=True)
            except Exception as error:  # one unreadable object must not stop the rest
                failed += 1
                self.stderr.write(
                    f"BigFileStore {store.pk} ({store.size_bytes} bytes): not hashed -- {error}"
                )
                continue
            recorded += 1
            self.stdout.write(
                f"BigFileStore {store.pk}: {store.digest} ({store.size_bytes} bytes)"
            )

        left = owed().count()
        self.stdout.write(
            f"Recorded {recorded} digest(s); {failed} failed; {left} still owed."
        )
        if failed:
            raise SystemExit(1)
