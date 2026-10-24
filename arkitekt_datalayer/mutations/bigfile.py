from typing import cast

from kante.types import Info

from arkitekt_datalayer import inputs, models, types
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
    return cast(types.BigFileStore, dl.finish_bigfile_upload(info.context.request.organization.id, input_model))


def request_bigfile_access(info: Info, input: inputs.RequestBigFileAccessInput) -> types.BigFileAccessGrant:
    """Request temporary S3 read credentials for a big file."""
    dl = get_current_datalayer()
    model = input.to_pydantic()

    store = models.BigFileStore.objects.get(id=model.store_id, organization=info.context.request.organization)
    return types.BigFileAccessGrant.from_pydantic(dl.generate_bigfile_access_grant(store))
