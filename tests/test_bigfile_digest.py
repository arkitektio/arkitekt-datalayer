"""A big file's digest end to end against the stack's RustFS: vouched for by the store, hashed inline, or owed to the job."""

import json
import os
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from arkitekt_datalayer import digest, models
from arkitekt_datalayer.datalayer import Datalayer
from tests.conftest import Execute, S3ClientFactory

REQUEST = "mutation($name: String!, $size: ByteCount!) { requestBigfileUpload(input: {originalFileName: $name, fileSize: $size}) { accessKey secretKey sessionToken bucket key store partSize checksumAlgorithm } }"
FINISH = "mutation($id: String!) { finishBigfileUpload(input: {storeId: $id}) { id sizeBytes digest digestAlgorithm sample } }"


def upload_in_advertised_parts(
    s3: "object", grant: dict[str, str], data: bytes
) -> None:
    """Upload as a client following the grant does: its part size, a SHA-256 checksum on every part."""
    part_size = int(grant["partSize"])
    bucket, key = grant["bucket"], grant["key"]
    upload_id = s3.create_multipart_upload(  # type: ignore[attr-defined]
        Bucket=bucket, Key=key, ChecksumAlgorithm="SHA256"
    )["UploadId"]
    parts = []
    for number, start in enumerate(range(0, len(data), part_size), 1):
        response = s3.upload_part(  # type: ignore[attr-defined]
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            PartNumber=number,
            Body=data[start : start + part_size],
            ChecksumAlgorithm="SHA256",
        )
        parts.append(
            {
                "PartNumber": number,
                "ETag": response["ETag"],
                "ChecksumSHA256": response["ChecksumSHA256"],
            }
        )
    s3.complete_multipart_upload(  # type: ignore[attr-defined]
        Bucket=bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
    )


async def answer(
    aexecute: Execute, query: str, variables: dict[str, object], field: str
) -> dict[str, Any]:
    """The ``field`` of a document's answer, which must have one."""
    result = await aexecute(query, variables)
    assert result.data is not None
    return result.data[field]


@pytest.fixture
def no_inline_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A finish reads no object whole: what it records then came from the store's checksum."""
    monkeypatch.setattr(models.BigFileStore, "inline_digest_bytes", 0)


async def test_the_grant_advertises_the_digest_parts(
    aexecute: Execute, datalayer: Datalayer
) -> None:
    grant = await answer(
        aexecute, REQUEST, {"name": "a.czi", "size": 10}, "requestBigfileUpload"
    )
    assert grant["partSize"] == digest.part_size_for(10)
    assert grant["checksumAlgorithm"] == "SHA256"


async def test_an_upload_in_the_advertised_parts_is_digested_without_reading_it(
    aexecute: Execute,
    datalayer: Datalayer,
    client_s3: S3ClientFactory,
    no_inline_hashing: None,
) -> None:
    data = os.urandom(digest.PART_FLOOR + 4321)
    grant = await answer(
        aexecute, REQUEST, {"name": "a.czi", "size": len(data)}, "requestBigfileUpload"
    )
    upload_in_advertised_parts(client_s3(grant), grant, data)

    finished = await answer(
        aexecute, FINISH, {"id": grant["store"]}, "finishBigfileUpload"
    )

    assert finished["digest"] == digest.composite_of_bytes(data)
    assert finished["digestAlgorithm"] == digest.ALGORITHM
    assert finished["sample"] == digest.sample_of_bytes(data)


async def test_a_small_upload_without_checksums_is_hashed_when_it_is_finished(
    aexecute: Execute, datalayer: Datalayer, client_s3: S3ClientFactory
) -> None:
    data = os.urandom(1000)
    grant = await answer(
        aexecute, REQUEST, {"name": "b.tif", "size": len(data)}, "requestBigfileUpload"
    )
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=data)

    finished = await answer(
        aexecute, FINISH, {"id": grant["store"]}, "finishBigfileUpload"
    )

    assert finished["digest"] == digest.composite_of_bytes(data)


async def test_a_large_upload_without_checksums_is_owed_to_the_job(
    aexecute: Execute,
    datalayer: Datalayer,
    client_s3: S3ClientFactory,
    no_inline_hashing: None,
) -> None:
    data = os.urandom(digest.PART_FLOOR + 10)
    grant = await answer(
        aexecute, REQUEST, {"name": "c.nd2", "size": len(data)}, "requestBigfileUpload"
    )
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=data)

    finished = await answer(
        aexecute, FINISH, {"id": grant["store"]}, "finishBigfileUpload"
    )
    assert finished["digest"] is None
    assert finished["sample"] == digest.sample_of_bytes(data)

    def backlog() -> dict[str, int]:
        out = StringIO()
        call_command("digest_bigfiles", "--backlog", stdout=out)
        return json.loads(out.getvalue())

    from asgiref.sync import sync_to_async

    assert await sync_to_async(backlog)() == {"items": 1, "bytes": len(data)}
    await sync_to_async(call_command)("digest_bigfiles", stdout=StringIO())
    store = await models.BigFileStore.objects.aget(id=grant["store"])
    assert store.digest == digest.composite_of_bytes(data)
    assert store.digested_at is not None
    assert await sync_to_async(backlog)() == {"items": 0, "bytes": 0}
    # Run again, it has nothing to do.
    await sync_to_async(call_command)("digest_bigfiles", stdout=StringIO())


async def test_the_job_starts_nothing_after_its_deadline(
    aexecute: Execute,
    datalayer: Datalayer,
    client_s3: S3ClientFactory,
    no_inline_hashing: None,
) -> None:
    """A scheduled run is told its window's end: what it did not reach stays owed for the next."""
    data = os.urandom(digest.PART_FLOOR + 10)
    grant = await answer(
        aexecute, REQUEST, {"name": "d.nd2", "size": len(data)}, "requestBigfileUpload"
    )
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=data)
    await answer(aexecute, FINISH, {"id": grant["store"]}, "finishBigfileUpload")

    from asgiref.sync import sync_to_async

    out = StringIO()
    await sync_to_async(call_command)(
        "digest_bigfiles", "--until", "2000-01-01T00:00:00+00:00", stdout=out
    )

    store = await models.BigFileStore.objects.aget(id=grant["store"])
    assert store.digest is None
    assert "Reached the deadline" in out.getvalue()
