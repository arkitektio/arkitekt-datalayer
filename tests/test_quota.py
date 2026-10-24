"""Quotas against measured usage: what a grant advertises and when one is refused."""

from arkitekt_datalayer import models
from arkitekt_datalayer.quota import QuotaConfig, resolve_quota

REQUEST_MEDIA = "mutation($name: String!, $size: ByteCount) { requestMediaUpload(input: {originalFileName: $name, fileSize: $size}) { store maxBytes } }"
FINISH_MEDIA = "mutation($id: String!) { finishMediaUpload(input: {storeId: $id}) { id sizeBytes } }"


def _quotas(settings, quotas: dict) -> None:  # noqa: ANN001
    import arkitekt_datalayer.datalayer as dl_module

    settings.DATALAYER = {**settings.DATALAYER, "quotas": quotas}
    dl_module.GLOBAL_DL = None


async def _upload(aexecute, client_s3, payload: bytes, context=None) -> str:  # noqa: ANN001
    grant_query = "mutation($name: String!, $size: ByteCount) { requestMediaUpload(input: {originalFileName: $name, fileSize: $size}) { accessKey secretKey sessionToken bucket key store } }"
    grant = (await aexecute(grant_query, {"name": "f", "size": len(payload)}, context=context)).data["requestMediaUpload"]
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=payload)
    await aexecute(FINISH_MEDIA, {"id": grant["store"]}, context=context)
    return grant["store"]


async def test_without_quotas_the_bucket_default_is_advertised(aexecute, datalayer):
    grant = (await aexecute(REQUEST_MEDIA, {"name": "f"})).data["requestMediaUpload"]

    assert grant["maxBytes"] == 100 * 1024 * 1024


async def test_the_per_upload_quota_is_advertised_and_enforced(aexecute, datalayer, settings):
    _quotas(settings, {"default": {"max_upload_bytes": 10}})

    assert (await aexecute(REQUEST_MEDIA, {"name": "f"})).data["requestMediaUpload"]["maxBytes"] == 10
    refused = await aexecute(REQUEST_MEDIA, {"name": "f", "size": 11}, allow_errors=True)
    assert "per-upload quota" in refused.errors[0].message


async def test_the_user_quota_counts_what_the_user_has_stored(aexecute, datalayer, client_s3, settings, other_org_context):
    _quotas(settings, {"default": {"max_user_bytes": 8}})
    await _upload(aexecute, client_s3, b"12345")

    refused = await aexecute(REQUEST_MEDIA, {"name": "f", "size": 4}, allow_errors=True)
    assert "Your storage quota" in refused.errors[0].message
    # Another organization's user holds nothing yet.
    assert not (await aexecute(REQUEST_MEDIA, {"name": "f", "size": 4}, context=other_org_context)).errors


async def test_an_organization_override_beats_the_default(aexecute, datalayer, client_s3, settings):
    _quotas(settings, {"default": {"max_org_bytes": 4}, "organizations": {"static_org": {"max_org_bytes": 100}}})

    await _upload(aexecute, client_s3, b"123456")
    assert not (await aexecute(REQUEST_MEDIA, {"name": "f", "size": 6})).errors


async def test_an_orphaned_store_frees_its_bytes(aexecute, datalayer, client_s3, settings):
    from django.utils import timezone

    _quotas(settings, {"default": {"max_org_bytes": 8}})
    store_id = await _upload(aexecute, client_s3, b"12345678")
    assert (await aexecute(REQUEST_MEDIA, {"name": "f", "size": 1}, allow_errors=True)).errors

    await models.DatalayerStore.objects.filter(id=store_id).aupdate(orphaned_at=timezone.now())

    assert not (await aexecute(REQUEST_MEDIA, {"name": "f", "size": 1})).errors


def test_resolution_is_most_specific_first():
    config = QuotaConfig.model_validate(
        {
            "default": {"max_upload_bytes": 1, "max_user_bytes": 10, "max_org_bytes": 100},
            "organizations": {"3": {"max_user_bytes": 20, "users": {"alice": {"max_upload_bytes": 5}}}},
        }
    )

    alice = resolve_quota(config, "3", "alice")
    bob = resolve_quota(config, "3", "bob")
    elsewhere = resolve_quota(config, "4", "alice")

    assert (alice.max_upload_bytes, alice.max_user_bytes, alice.max_org_bytes) == (5, 20, 100)
    assert (bob.max_upload_bytes, bob.max_user_bytes) == (1, 20)
    assert (elsewhere.max_upload_bytes, elsewhere.max_user_bytes) == (1, 10)
