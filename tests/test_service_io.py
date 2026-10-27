"""What a server writes and reads with its own credentials, and a service with no datalayer at all."""

import pytest
from authentikate.models import Organization
from django.db import connection

from arkitekt_datalayer import models
from arkitekt_datalayer.datalayer import Datalayer, is_configured


@pytest.fixture
def organization(transactional_db) -> Organization:  # noqa: ANN001
    return Organization.objects.create(identifier="static_issuer#static_org")


def test_stored_bytes_come_back_finished_and_measured(datalayer, organization):
    store = datalayer.store_bytes(models.BigFileStore, organization.id, b"From: a@b\n\nhi", original_file_name="mail.eml", content_type="message/rfc822")

    store.refresh_from_db()
    assert store.populated and store.size_bytes == 13 and store.bucket == "bigfile"
    assert datalayer.read_object("bigfile", store.key) == b"From: a@b\n\nhi"
    assert store.read_bytes(datalayer, max_bytes=4) == b"From"
    assert store.measure_bytes(datalayer) == 13


def test_a_prefix_store_is_not_one_object(datalayer, organization):
    with pytest.raises(ValueError, match="prefix store"):
        datalayer.store_bytes(models.ZarrStore, organization.id, b"x")


def test_reading_what_was_never_uploaded_says_so(datalayer):
    with pytest.raises(FileNotFoundError, match="nothing to read"):
        datalayer.read_object("bigfile", "never-uploaded")


def test_deleting_a_store_deletes_its_bytes_first(datalayer, organization):
    store = datalayer.store_bytes(models.MediaStore, organization.id, b"bye")
    key = store.key

    store.delete()

    with pytest.raises(FileNotFoundError):
        datalayer.read_object("media", key)


def test_a_store_row_inserted_by_raw_sql_is_unpopulated(organization):
    """takt inserts with raw SQL, which never sees a Python default."""
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO datalayer_datalayerstore (organization_id, key, bucket) VALUES (%s, 'raw', 'media') RETURNING populated", [organization.id])
        assert cursor.fetchone() == (False,)


def test_without_a_datalayer_the_app_installs_and_grants_name_what_is_missing(settings, organization):
    settings.DATALAYER = None

    assert not is_configured()
    layer = Datalayer()
    with pytest.raises(ValueError, match="`datalayer.media`"):
        layer.store_bytes(models.MediaStore, organization.id, b"x")

