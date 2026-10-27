"""Put the datalayer's multipart-cleanup lifecycle rule on every configured bucket.

The parts of an interrupted multipart upload are stored and billed, and no listing shows them.
Purging a store aborts the uploads open at its key, but a client killed mid-upload whose store is
never purged, or an object store that cannot list multipart uploads, leaves them behind. The
bucket rule is the backstop. Idempotent and merged by rule id, so it is safe as a setup job on
every build, and leaves another service's rules in a shared bucket alone.
"""

from django.core.management.base import BaseCommand

from arkitekt_datalayer.datalayer import get_current_datalayer


class Command(BaseCommand):
    """Ensure every configured bucket aborts incomplete multipart uploads."""

    help = "Put an AbortIncompleteMultipartUpload lifecycle rule on every configured datalayer bucket."

    def add_arguments(self, parser) -> None:  # noqa: ANN001 - Django's ArgumentParser
        """Declare the command's options."""
        parser.add_argument("--days", type=int, default=1, help="Abort multipart uploads this many days after they were started.")

    def handle(self, *args, **options) -> None:
        """Put the rule on each bucket."""
        buckets = get_current_datalayer().ensure_lifecycle(days=options["days"])
        self.stdout.write(self.style.SUCCESS(f"abort-incomplete-multipart rule ({options['days']} day(s)) on {', '.join(buckets) or 'no buckets'}"))
