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
    return Organization.objects.create(identifier="static_issuer#static_org")


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


def test_an_abandoned_upload_is_purged_with_its_bytes(datalayer, organization):
    """Past its deadline an unfinished upload can never be finished or referenced: collect it."""
    store = models.ZarrStore.objects.create(organization=organization, key="1/abandoned", bucket="zarr", upload_expires_at=timezone.now() - datetime.timedelta(minutes=1))
    datalayer.put_file("zarr", "1/abandoned/zarr.json", b"{}")

    output = _purge()

    assert "abandoned upload" in output
    assert not models.DatalayerStore.objects.filter(pk=store.pk).exists()
    assert datalayer.measure_prefix_bytes("zarr", "1/abandoned") == 0


def test_an_upload_before_its_deadline_is_left_alone(datalayer, organization):
    store = models.ZarrStore.objects.create(organization=organization, key="1/running", bucket="zarr", upload_expires_at=timezone.now() + datetime.timedelta(minutes=30))

    _purge()

    assert models.DatalayerStore.objects.filter(pk=store.pk).exists()


def test_purging_a_store_aborts_its_unfinished_multipart_upload(datalayer, organization):
    """Parts are invisible to a listing, so a purge that only deletes objects would leave them."""
    store = models.BigFileStore.objects.create(organization=organization, key="1/parts", bucket="bigfile", upload_expires_at=timezone.now() - datetime.timedelta(minutes=1))
    bucket = datalayer.get_bucket_config("bigfile").bucket
    full_key = datalayer.build_object_key("bigfile", store.key)
    datalayer._s3.create_multipart_upload(Bucket=bucket, Key=full_key)

    _purge()

    open_uploads = datalayer._s3.list_multipart_uploads(Bucket=bucket, Prefix=full_key).get("Uploads", [])
    assert open_uploads == []


def test_a_bulk_delete_takes_the_bytes_with_the_rows(datalayer, organization):
    """A queryset delete (the admin's bulk action, an organization's cascade) runs no model
    method, so its bytes are purged after the commit instead of being left behind."""
    store = datalayer.store_bytes(models.BigFileStore, organization.id, b"bulk")

    models.BigFileStore.objects.filter(pk=store.pk).delete()

    with pytest.raises(FileNotFoundError):
        datalayer.read_object("bigfile", store.key)


def test_a_key_is_segmented_by_the_issuer_qualified_organization(datalayer, organization):
    """The segment comes from `identifier`, not the local pk: a local id names different tenants
    in different services, and services share buckets."""
    twin = Organization.objects.create(identifier="https://another-lok#static_org")

    key = datalayer._new_key(organization.id)

    assert key.startswith(datalayer.organization_segment(organization.id) + "/")
    assert datalayer.organization_segment(twin.id) != datalayer.organization_segment(organization.id), "the same org claim from another lok is another tenant"
    assert "#" not in key and ":" not in key, "the segment is key-safe"
