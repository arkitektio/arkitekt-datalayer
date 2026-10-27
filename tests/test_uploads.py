"""Uploads end to end against the stack's RustFS: a grant is a real STS session scoped by its policy."""

import datetime
import json

import pytest
from botocore.exceptions import ClientError
from django.utils import timezone

from arkitekt_datalayer import models

REQUEST_MEDIA = "mutation($name: String!, $size: ByteCount!) { requestMediaUpload(input: {originalFileName: $name, fileSize: $size}) { accessKey secretKey sessionToken bucket key store maxBytes } }"
FINISH_MEDIA = "mutation($id: String!) { finishMediaUpload(input: {storeId: $id}) { id sizeBytes } }"
MEDIA_ACCESS = "mutation($id: String!) { requestMediaAccess(input: {storeId: $id}) { accessKey secretKey sessionToken bucket key } }"
REQUEST_ZARR = "mutation { requestZarrUpload(input: {}) { accessKey secretKey sessionToken bucket key store } }"
FINISH_ZARR = "mutation($id: String!) { finishZarrUpload(input: {storeId: $id}) { id shape chunks dtype sizeBytes } }"
REFRESH_ZARR = "mutation($id: String!) { refreshZarrUpload(input: {storeId: $id}) { key store } }"
REQUEST_PARQUET = "mutation { requestParquetUpload(input: {}) { accessKey secretKey sessionToken bucket key store } }"
FINISH_PARQUET = "mutation($id: String!) { finishParquetUpload(input: {storeId: $id}) { id sizeBytes path } }"
REQUEST_FABRIKS = "mutation { requestFabriksUpload { accessKey secretKey sessionToken bucket key store } }"

ZARR_JSON = {
    "zarr_format": 3,
    "node_type": "array",
    "shape": [4, 4],
    "data_type": "uint8",
    "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": [2, 2]}},
    "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
    "fill_value": 0,
    "codecs": [{"name": "bytes"}],
}


async def test_a_media_upload_round_trips(aexecute, datalayer, client_s3):
    grant = (await aexecute(REQUEST_MEDIA, {"name": "cat.png", "size": 4})).data["requestMediaUpload"]
    assert grant["maxBytes"] == 4
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=b"meow")

    finished = (await aexecute(FINISH_MEDIA, {"id": grant["store"]})).data["finishMediaUpload"]

    assert finished["sizeBytes"] == 4
    store = await models.MediaStore.objects.aget(id=grant["store"])
    assert store.populated
    assert store.read_bytes(datalayer) == b"meow"


async def test_a_grant_writes_only_its_own_key(aexecute, datalayer, client_s3):
    grant = (await aexecute(REQUEST_MEDIA, {"name": "a.png", "size": 3})).data["requestMediaUpload"]
    s3 = client_s3(grant)

    with pytest.raises(ClientError):
        s3.put_object(Bucket=grant["bucket"], Key="someone-else", Body=b"x")
    s3.put_object(Bucket=grant["bucket"], Key=grant["key"], Body=b"abc")


async def test_a_read_grant_reads_its_store_and_nothing_else(aexecute, datalayer, client_s3):
    first = await datalayer_store(datalayer, b"one")
    second = await datalayer_store(datalayer, b"two")

    grant = (await aexecute(MEDIA_ACCESS, {"id": str(first.pk)})).data["requestMediaAccess"]
    s3 = client_s3(grant)

    assert s3.get_object(Bucket=grant["bucket"], Key=grant["key"])["Body"].read() == b"one"
    with pytest.raises(ClientError):
        s3.get_object(Bucket=grant["bucket"], Key=second.key)


async def datalayer_store(datalayer, payload: bytes) -> models.MediaStore:  # noqa: ANN001
    from asgiref.sync import sync_to_async
    from authentikate.models import Organization

    organization = await Organization.objects.aget(identifier="static_issuer#static_org")
    return await sync_to_async(datalayer.store_bytes)(models.MediaStore, organization.id, payload, content_type="image/png")


async def test_a_zarr_grant_covers_its_prefix_and_finish_reads_the_array(aexecute, datalayer, client_s3):
    grant = (await aexecute(REQUEST_ZARR)).data["requestZarrUpload"]
    s3 = client_s3(grant)
    prefix = grant["key"].rstrip("/")

    s3.put_object(Bucket=grant["bucket"], Key=f"{prefix}/zarr.json", Body=json.dumps(ZARR_JSON).encode())
    s3.put_object(Bucket=grant["bucket"], Key=f"{prefix}/c/0/0", Body=b"\x01\x02\x03\x04")
    # A prefix writer reads back and lists inside its own tree, and nowhere else.
    assert s3.get_object(Bucket=grant["bucket"], Key=f"{prefix}/zarr.json")["Body"].read()
    assert len(s3.list_objects_v2(Bucket=grant["bucket"], Prefix=f"{prefix}/")["Contents"]) == 2
    with pytest.raises(ClientError):
        s3.put_object(Bucket=grant["bucket"], Key=f"{prefix}-sibling/zarr.json", Body=b"{}")

    refreshed = (await aexecute(REFRESH_ZARR, {"id": grant["store"]})).data["refreshZarrUpload"]
    assert refreshed["key"] == grant["key"]

    finished = (await aexecute(FINISH_ZARR, {"id": grant["store"]})).data["finishZarrUpload"]
    assert finished["shape"] == [4, 4] and finished["chunks"] == [2, 2] and finished["dtype"] == "uint8"
    assert finished["sizeBytes"] > 4

    refused = await aexecute(REFRESH_ZARR, {"id": grant["store"]}, allow_errors=True)
    assert "already finished" in refused.errors[0].message


async def test_a_parquet_finish_reads_the_columns_off_the_file(aexecute, datalayer, client_s3, tmp_path):
    from arkitekt_datalayer.duck import DuckLayer

    target = tmp_path / "t.parquet"
    DuckLayer().connection.execute(f"COPY (SELECT 1::INTEGER AS a, 'x' AS b) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD);")
    grant = (await aexecute(REQUEST_PARQUET)).data["requestParquetUpload"]
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=target.read_bytes())

    finished = (await aexecute(FINISH_PARQUET, {"id": grant["store"]})).data["finishParquetUpload"]

    assert finished["path"] == f"s3://dl-parquet/{grant['key']}"
    store = await models.ParquetStore.objects.aget(id=grant["store"])
    assert [(column["name"], column["type"]) for column in store.columns] == [("a", "INTEGER"), ("b", "VARCHAR")]


async def test_a_bucket_subpath_keeps_two_logical_buckets_apart(aexecute, datalayer, client_s3):
    grant = (await aexecute(REQUEST_FABRIKS)).data["requestFabriksUpload"]
    s3 = client_s3(grant)

    assert grant["bucket"] == "dl-collections" and grant["key"].startswith("fabriks/")
    s3.put_object(Bucket=grant["bucket"], Key=f"{grant['key']}/fabriks.json", Body=b"{}")
    with pytest.raises(ClientError):
        s3.put_object(Bucket=grant["bucket"], Key=f"konnektion/{grant['key'].removeprefix('fabriks/')}/konnektion.json", Body=b"{}")


async def test_a_role_outside_upload_roles_cannot_upload(aexecute, datalayer, viewer_context):
    result = await aexecute(REQUEST_MEDIA, {"name": "a.png", "size": 3}, context=viewer_context, allow_errors=True)

    assert result.errors
    assert not await models.MediaStore.objects.aexists()


async def test_another_organization_can_neither_finish_nor_read_a_store(aexecute, datalayer, client_s3, other_org_context):
    grant = (await aexecute(REQUEST_MEDIA, {"name": "a.png", "size": 3})).data["requestMediaUpload"]
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=b"abc")

    finish = await aexecute(FINISH_MEDIA, {"id": grant["store"]}, context=other_org_context, allow_errors=True)
    access = await aexecute(MEDIA_ACCESS, {"id": grant["store"]}, context=other_org_context, allow_errors=True)

    assert finish.errors and access.errors
    assert not (await models.MediaStore.objects.aget(id=grant["store"])).populated


INVALIDATE_ZARR = "mutation($id: String!) { finishZarrUpload(input: {storeId: $id, valid: false}) { id } }"


async def _finished_zarr(aexecute, client_s3) -> str:  # noqa: ANN001
    grant = (await aexecute(REQUEST_ZARR)).data["requestZarrUpload"]
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=f"{grant['key']}/zarr.json", Body=json.dumps(ZARR_JSON).encode())
    await aexecute(FINISH_ZARR, {"id": grant["store"]})
    return grant["store"]


async def test_a_finished_store_cannot_be_reopened_for_writing(aexecute, datalayer, client_s3):
    """`valid=false` after the fact would unpopulate the store, and an unpopulated store is
    refreshable: write credentials for bytes something may already reference."""
    store = await _finished_zarr(aexecute, client_s3)

    invalidated = await aexecute(INVALIDATE_ZARR, {"id": store}, allow_errors=True)
    refreshed = await aexecute(REFRESH_ZARR, {"id": store}, allow_errors=True)

    assert invalidated.errors and "already finished" in str(invalidated.errors[0])
    assert refreshed.errors
    assert (await models.ZarrStore.objects.aget(id=store)).populated


async def test_a_second_finish_returns_the_store_as_it_was_recorded(aexecute, datalayer, client_s3):
    store = await _finished_zarr(aexecute, client_s3)
    before = await models.ZarrStore.objects.aget(id=store)

    again = (await aexecute(FINISH_ZARR, {"id": store})).data["finishZarrUpload"]

    assert again["shape"] == list(before.shape)
    assert (await models.ZarrStore.objects.aget(id=store)).populated


async def test_only_the_uploader_finishes_or_continues_an_upload(aexecute, datalayer, client_s3, colleague_context):
    """Same organization, different user: finish and refresh are steps of one person's upload."""
    grant = (await aexecute(REQUEST_ZARR)).data["requestZarrUpload"]
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=f"{grant['key']}/zarr.json", Body=json.dumps(ZARR_JSON).encode())

    finish = await aexecute(FINISH_ZARR, {"id": grant["store"]}, context=colleague_context, allow_errors=True)
    refresh = await aexecute(REFRESH_ZARR, {"id": grant["store"]}, context=colleague_context, allow_errors=True)

    assert finish.errors and refresh.errors
    assert not (await models.ZarrStore.objects.aget(id=grant["store"])).populated
    await aexecute(FINISH_ZARR, {"id": grant["store"]})


GENERAL_MEDIA = "mutation { requestGeneralMediaAccess(input: {}) { accessKey secretKey sessionToken bucket prefix } }"


async def test_a_general_grant_reads_its_own_organization_and_no_other(aexecute, datalayer, client_s3, other_org_context):
    """The prefix is the organization, so a general grant is a read of one organization's stores."""
    grant = (await aexecute(REQUEST_MEDIA, {"name": "a.png", "size": 3})).data["requestMediaUpload"]
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=b"abc")

    own = (await aexecute(GENERAL_MEDIA)).data["requestGeneralMediaAccess"]
    other = (await aexecute(GENERAL_MEDIA, context=other_org_context)).data["requestGeneralMediaAccess"]

    assert grant["key"].startswith(f"{own['prefix']}/")
    assert client_s3(own).get_object(Bucket=grant["bucket"], Key=grant["key"])["Body"].read() == b"abc"
    with pytest.raises(ClientError):
        client_s3(other).get_object(Bucket=grant["bucket"], Key=grant["key"])


REFRESH_MEDIA = "mutation($id: String!) { refreshMediaUpload(input: {storeId: $id}) { accessKey secretKey sessionToken bucket key store } }"


async def test_a_refreshed_grant_resumes_a_multipart_upload_on_the_same_key(aexecute, datalayer, client_s3):
    """The first session starts the upload and sends a part; a refreshed one lists it and completes."""
    part = b"x" * (5 * 1024 * 1024)
    grant = (await aexecute(REQUEST_MEDIA, {"name": "big.bin", "size": len(part) + 3})).data["requestMediaUpload"]
    first = client_s3(grant)
    upload_id = first.create_multipart_upload(Bucket=grant["bucket"], Key=grant["key"])["UploadId"]
    etag = first.upload_part(Bucket=grant["bucket"], Key=grant["key"], UploadId=upload_id, PartNumber=1, Body=part)["ETag"]

    refreshed = (await aexecute(REFRESH_MEDIA, {"id": grant["store"]})).data["refreshMediaUpload"]
    second = client_s3(refreshed)
    listed = second.list_parts(Bucket=refreshed["bucket"], Key=refreshed["key"], UploadId=upload_id)["Parts"]
    tail = second.upload_part(Bucket=refreshed["bucket"], Key=refreshed["key"], UploadId=upload_id, PartNumber=2, Body=b"end")["ETag"]
    second.complete_multipart_upload(Bucket=refreshed["bucket"], Key=refreshed["key"], UploadId=upload_id, MultipartUpload={"Parts": [{"PartNumber": 1, "ETag": etag}, {"PartNumber": 2, "ETag": tail}]})

    assert (refreshed["key"], refreshed["store"]) == (grant["key"], grant["store"])
    assert [p["PartNumber"] for p in listed] == [1]
    assert (await aexecute(FINISH_MEDIA, {"id": grant["store"]})).data["finishMediaUpload"]["sizeBytes"] == len(part) + 3


async def test_an_upload_cannot_be_refreshed_past_its_time(aexecute, datalayer, settings):
    grant = (await aexecute(REQUEST_MEDIA, {"name": "a.png", "size": 3})).data["requestMediaUpload"]
    await models.MediaStore.objects.filter(id=grant["store"]).aupdate(created_at=timezone.now() - datetime.timedelta(days=2))

    refused = await aexecute(REFRESH_MEDIA, {"id": grant["store"]}, allow_errors=True)

    assert "has run for its whole" in str(refused.errors[0])


async def test_an_abandoned_upload_can_be_neither_finished_nor_refreshed(aexecute, datalayer, client_s3):
    grant = (await aexecute(REQUEST_MEDIA, {"name": "a.png", "size": 3})).data["requestMediaUpload"]
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=b"abc")
    await models.MediaStore.objects.filter(id=grant["store"]).aupdate(upload_expires_at=timezone.now() - datetime.timedelta(seconds=1))

    finish = await aexecute(FINISH_MEDIA, {"id": grant["store"]}, allow_errors=True)
    refresh = await aexecute(REFRESH_MEDIA, {"id": grant["store"]}, allow_errors=True)

    assert "abandoned" in str(finish.errors[0]) and "abandoned" in str(refresh.errors[0])
