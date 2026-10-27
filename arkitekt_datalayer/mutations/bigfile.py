from typing import cast

from kante.types import Info

from arkitekt_datalayer import base_models, inputs, models, types
from arkitekt_datalayer.context import caller
from arkitekt_datalayer.datalayer import get_current_datalayer


def request_bigfile_upload(info: Info, input: inputs.RequestBigFileUploadInput) -> types.BigFileUploadGrant:
    """Request temporary S3 upload credentials for a big file."""
    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return types.BigFileUploadGrant.from_pydantic(dl.generate_bigfile_upload_grant(organization_id, input_model, user=user))


def finish_bigfile_upload(info: Info, input: inputs.FinishBigFileUploadInput) -> types.BigFileStore:
    """Mark the BigFileStore as populated after a successful upload."""
    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return cast(types.BigFileStore, dl.finish_bigfile_upload(organization_id, input_model, user=user))


def refresh_bigfile_upload(info: Info, input: inputs.RefreshUploadInput) -> types.BigFileUploadGrant:
    """Reissue upload credentials for a bigfile upload still in flight, to the same key."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    grant = dl.refresh_upload_grant(models.BigFileStore, organization_id, input.to_pydantic().store_id, user=user)
    return types.BigFileUploadGrant.from_pydantic(cast("base_models.BigFileUploadGrant", grant))


def request_bigfile_access(info: Info, input: inputs.RequestBigFileAccessInput) -> types.BigFileAccessGrant:
    """Request temporary S3 read credentials for a big file."""
    dl = get_current_datalayer()
    model = input.to_pydantic()

    store = models.BigFileStore.objects.get(id=model.store_id, organization=info.context.request.organization, populated=True, orphaned_at__isnull=True)
    return types.BigFileAccessGrant.from_pydantic(dl.generate_bigfile_access_grant(store))
