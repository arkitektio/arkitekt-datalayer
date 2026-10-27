from typing import cast

from kante.types import Info

from arkitekt_datalayer import base_models, inputs, models, types
from arkitekt_datalayer.context import caller
from arkitekt_datalayer.datalayer import get_current_datalayer


def request_media_upload(info: Info, input: inputs.RequestMediaUploadInput) -> types.MediaUploadGrant:
    """Request temporary S3 upload credentials for a media file."""

    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return types.MediaUploadGrant(**dl.generate_media_upload_grant(organization_id, input_model, user=user).model_dump())


def finish_media_upload(info: Info, input: inputs.FinishMediaUploadInput) -> types.MediaStore:
    """Mark the MediaStore as populated after a successful upload."""

    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return cast(types.MediaStore, dl.finish_media_upload(organization_id, input_model, user=user))


def refresh_media_upload(info: Info, input: inputs.RefreshUploadInput) -> types.MediaUploadGrant:
    """Reissue upload credentials for a media upload still in flight, to the same key."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    grant = dl.refresh_upload_grant(models.MediaStore, organization_id, input.to_pydantic().store_id, user=user)
    return types.MediaUploadGrant.from_pydantic(cast("base_models.MediaUploadGrant", grant))


def request_media_access(info: Info, input: inputs.RequestMediaAccessInput) -> types.MediaAccessGrant:
    """Request temporary S3 read credentials for a media file."""

    dl = get_current_datalayer()
    model = input.to_pydantic()

    store = models.MediaStore.objects.get(id=model.store_id, organization=info.context.request.organization, populated=True, orphaned_at__isnull=True)
    return types.MediaAccessGrant.from_pydantic(dl.generate_media_access_grant(store))


def request_general_media_access(info: Info, input: inputs.RequestGeneralMediaAccessInput) -> types.GeneralMediaAccessGrant:
    """Request temporary S3 read credentials for a media file."""

    dl = get_current_datalayer()
    model = input.to_pydantic()

    organization_id, user = caller(info)
    return types.GeneralMediaAccessGrant.from_pydantic(dl.generate_general_media_access_grant(organization_id, user.pk, expires_in=model.expires_in))
