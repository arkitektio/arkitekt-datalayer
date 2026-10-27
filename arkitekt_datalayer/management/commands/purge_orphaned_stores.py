"""Delete the S3 objects behind stores whose data was deleted, after a grace period.

Deleting a data row (mikro's `File` or `ArrayDataset`) does no S3 work -- a request must never block on a zarr with
a hundred thousand chunks, and bytes must never be destroyed inside a transaction that might
roll back. The delete flags the stores it orphaned; this collects them.

**Only ever purge rows with `orphaned_at` set.** Sweeping every *unreferenced* store would be
simpler and self-healing, and it would destroy live uploads: an upload grant creates the store
row before the client has uploaded and long before any data row attaches, so "unreferenced" is
the normal state of an upload in flight, not a sign of garbage. The flag is what separates
"nothing wants this any more" from "nothing wants this yet".

**Abandoned uploads are the other thing it collects.** An upload that was never finished and is
past its deadline (``upload_expires_at``: its last grant's expiry plus a grace, never more than
``max_upload_seconds`` after it started) cannot be finished any more -- finish and refresh refuse
it -- so nothing will ever reference it, and its bytes would otherwise stay forever. The deadline
is what makes this safe where "unreferenced" is not: an upload in flight is never past it.

Each store is purged inside a transaction holding a row lock on it. A data row that attaches the
store meanwhile takes a key-share lock on the same row, so it waits, and then fails on the
foreign key instead of silently losing its bytes.

Run it from cron. Nothing is freed until it runs.
"""

import datetime

from django.core.management.base import BaseCommand
from django.db import models, transaction
from django.utils import timezone

from arkitekt_datalayer import storage
from arkitekt_datalayer.datalayer import load_config
from arkitekt_datalayer.models import DatalayerStore


class Command(BaseCommand):
    """Purge the S3 objects behind stores that have been orphaned longer than the grace period."""

    help = "Delete S3 objects for stores orphaned longer than the grace period, and their rows."

    def add_arguments(self, parser) -> None:  # noqa: ANN001 - Django's ArgumentParser
        """Declare the command's options."""
        parser.add_argument("--dry-run", action="store_true", help="Report what would be purged without deleting anything.")
        parser.add_argument("--older-than", type=int, default=None, metavar="DAYS", help="Grace period in days, overriding `datalayer.store_grace_days`.")
        parser.add_argument("--limit", type=int, default=None, metavar="N", help="Purge at most N stores this run.")

    def handle(self, *args, **options) -> None:
        """Purge every eligible store, re-checking each for referrers first."""
        grace_days = options["older_than"] if options["older_than"] is not None else load_config().store_grace_days
        cutoff = timezone.now() - datetime.timedelta(days=grace_days)
        dry_run = options["dry_run"]

        candidates = DatalayerStore.objects.filter(orphaned_at__isnull=False, orphaned_at__lt=cutoff).order_by("orphaned_at")
        if options["limit"]:
            candidates = candidates[: options["limit"]]

        abandoned = DatalayerStore.objects.filter(populated=False, upload_expires_at__isnull=False, upload_expires_at__lt=timezone.now()).order_by("upload_expires_at")
        if options["limit"]:
            abandoned = abandoned[: options["limit"]]

        purged = objects_deleted = revived = failed = 0

        for store in abandoned:
            if dry_run:
                self.stdout.write(f"would purge abandoned {store.bucket}/{store.key} (deadline {store.upload_expires_at:%Y-%m-%d %H:%M})")
                purged += 1
                continue
            outcome = self._purge(store, reason="abandoned upload")
            if outcome is None:
                failed += 1
            elif outcome < 0:
                revived += 1
            else:
                purged += 1
                objects_deleted += outcome

        # The manager is polymorphic, so each row arrives as its real subclass and `is_prefix`
        # can be read straight off it -- a zarr knows to list-and-batch, everything else does
        # not have to care.
        for store in candidates:
            if dry_run:
                referrers = storage.referrers_of(store)
                if referrers:
                    revived += 1
                    continue
                kind = "prefix" if store.is_prefix else "object"
                self.stdout.write(f"would purge {kind} {store.bucket}/{store.key} (orphaned {store.orphaned_at:%Y-%m-%d})")
                purged += 1
                continue
            outcome = self._purge(store, reason="orphaned")
            if outcome is None:
                failed += 1
            elif outcome < 0:
                DatalayerStore.objects.filter(pk=store.pk).update(orphaned_at=None)
                revived += 1
            else:
                purged += 1
                objects_deleted += outcome

        verb = "would purge" if dry_run else "purged"
        self.stdout.write(self.style.SUCCESS(f"{verb} {purged} store(s), {objects_deleted} object(s); kept {revived} still-referenced; {failed} failed"))
        if not purged and not revived:
            self.stdout.write(f"nothing orphaned longer than {grace_days} day(s), and no abandoned uploads")

    def _purge(self, store: DatalayerStore, *, reason: str) -> int | None:
        """Purge one store under a row lock: the object count, -1 if it is still referenced, None on failure."""
        try:
            with transaction.atomic():
                # Locked on its own class, so the lock covers the subclass row data rows point
                # at as well as the base row.
                locked = type(store).objects.select_for_update().filter(pk=store.pk).first()
                if locked is None:
                    return 0
                referrers = storage.referrers_of(locked)
                if referrers:
                    # Re-attached, or shared with a row that outlived the deleted one. The flag
                    # was only ever a candidate marker; this is the check that makes it safe.
                    described = ", ".join(f"{name} x{count}" for name, count in referrers)
                    self.stdout.write(f"keep    {locked.bucket}/{locked.key} -- still referenced by {described}")
                    return -1
                # Bytes first, then the row. Bytes gone with the row left behind is retried
                # harmlessly next run; the row gone with bytes left is a leak nothing points at.
                count = locked.purge_bytes()
                locked._bytes_purged = True
                models.Model.delete(locked)
        except Exception as error:  # noqa: BLE001 - one bad store must not stop the sweep
            self.stderr.write(f"FAILED  {store.bucket}/{store.key}: {error}")
            return None
        kind = "prefix" if store.is_prefix else "object"
        self.stdout.write(f"purged  {kind} {store.bucket}/{store.key} ({count} object{'s' if count != 1 else ''}) -- {reason}")
        return count
