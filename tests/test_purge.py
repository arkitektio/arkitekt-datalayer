"""Orphan flagging and the purge: bytes go only after their last referrer and the grace period."""

import datetime
from io import StringIO

import pytest
from authentikate.models import Organization
from django.core.management import call_command
from django.utils import timezone

from arkitekt_datalayer import models, storage
from test_app.models import Document, Image


@pytest.fixture
def organization(transactional_db) -> Organization:  # noqa: ANN001
    return Organization.objects.create(slug="static_org")


def _delete(row) -> None:  # noqa: ANN001
    """Delete a data row the way a service's delete mutation does: collect, delete, flag."""
    orphaned = storage.stores_orphaned_by(row)
    row.delete()
    storage.flag_orphaned(orphaned)


def _purge(*args: str) -> str:
    out = StringIO()
    call_command("purge_orphaned_stores", *args, stdout=out)
    return out.getvalue()


def _age(store: models.DatalayerStore, days: int) -> None:
    models.DatalayerStore.objects.filter(pk=store.pk).update(orphaned_at=timezone.now() - datetime.timedelta(days=days))


def test_deleting_a_row_flags_its_store_and_the_purge_deletes_bytes_then_row(datalayer, organization):
    store = datalayer.store_bytes(models.BigFileStore, organization.id, b"statement")
    _delete(Document.objects.create(store=store))
    _age(store, 8)

    output = _purge()

    assert "purged  object" in output
    assert not models.DatalayerStore.objects.filter(pk=store.pk).exists()
    with pytest.raises(FileNotFoundError):
        datalayer.read_object("bigfile", store.key)


def test_a_prefix_store_is_purged_as_a_tree(datalayer, organization):
    zarr = models.ZarrStore.objects.create(organization=organization, key="tree", bucket="zarr")
    for name in ("zarr.json", "c/0/0", "c/0/1"):
        datalayer.put_file("zarr", f"tree/{name}", b"x")
    _delete(Image.objects.create(data=zarr))
    _age(zarr, 8)

    assert "(3 objects)" in _purge()
    assert datalayer.measure_prefix_bytes("zarr", "tree") == 0


def test_a_store_another_row_still_holds_is_kept_and_unflagged(datalayer, organization):
    store = datalayer.store_bytes(models.BigFileStore, organization.id, b"shared")
    first = Document.objects.create(store=store)
    Document.objects.create(store=store)
    _delete(first)
    _age(store, 8)

    assert "still referenced by documents x1" in _purge()
    store.refresh_from_db()
    assert store.orphaned_at is None
    assert datalayer.read_object("bigfile", store.key) == b"shared"


def test_an_upload_in_flight_is_never_touched(datalayer, organization):
    """Unreferenced is the normal state of an upload in progress: only a flag makes a store collectable."""
    store = models.MediaStore.objects.create(organization=organization, key="in-flight", bucket="media")

    assert "nothing orphaned" in _purge("--older-than", "0")
    assert models.DatalayerStore.objects.filter(pk=store.pk).exists()


def test_the_grace_period_holds_and_dry_run_deletes_nothing(datalayer, organization, settings):
    store = datalayer.store_bytes(models.BigFileStore, organization.id, b"recent")
    _delete(Document.objects.create(store=store))
    _age(store, 2)

    assert "nothing orphaned longer than 7 day(s)" in _purge()
    settings.DATALAYER = {**settings.DATALAYER, "store_grace_days": 1}
    assert "would purge object" in _purge("--dry-run")
    assert datalayer.read_object("bigfile", store.key) == b"recent"


def test_a_nullable_reference_orphans_nothing_when_it_is_already_empty(datalayer, organization):
    zarr = models.ZarrStore.objects.create(organization=organization, key="no-thumb", bucket="zarr")
    image = Image.objects.create(data=zarr, thumbnail=None)

    assert [store.pk for store in storage.stores_orphaned_by(image)] == [zarr.pk]
