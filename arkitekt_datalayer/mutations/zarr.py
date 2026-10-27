from typing import cast

from kante.types import Info

from arkitekt_datalayer import base_models, inputs, models, types
from arkitekt_datalayer.context import caller
from arkitekt_datalayer.datalayer import get_current_datalayer


def request_zarr_upload(info: Info, input: inputs.RequestZarrUploadInput) -> types.ZarrUploadGrant:
    """Request temporary S3 upload credentials for a Zarr store."""
    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return types.ZarrUploadGrant.from_pydantic(dl.generate_zarr_upload_grant(organization_id, input_model, user=user))


def finish_zarr_upload(info: Info, input: inputs.FinishZarrUploadInput) -> types.ZarrStore:
    """Mark the ZarrStore as populated after a successful upload."""
    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return cast(types.ZarrStore, dl.finish_zarr_upload(organization_id, input_model, user=user))


def refresh_zarr_upload(info: Info, input: inputs.RefreshUploadInput) -> types.ZarrUploadGrant:
    """Reissue upload credentials for a zarr upload still in flight, to the same key."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    grant = dl.refresh_upload_grant(models.ZarrStore, organization_id, input.to_pydantic().store_id, user=user)
    return types.ZarrUploadGrant.from_pydantic(cast("base_models.ZarrUploadGrant", grant))


def request_zarr_access(info: Info, input: inputs.RequestZarrAccessInput) -> types.ZarrAccessGrant:
    """Request temporary S3 read credentials for a Zarr store."""
    dl = get_current_datalayer()

    model = input.to_pydantic()

    store = models.ZarrStore.objects.get(id=model.store_id, organization=info.context.request.organization, populated=True, orphaned_at__isnull=True)
    return types.ZarrAccessGrant.from_pydantic(dl.generate_zarr_access_grant(store))


def request_general_zarr_access(info: Info, input: inputs.RequestGeneralZarrAccessInput) -> types.GeneralZarrAccessGrant:
    """Request temporary S3 read credentials for a media file."""

    dl = get_current_datalayer()
    model = input.to_pydantic()

    organization_id, user = caller(info)
    return types.GeneralZarrAccessGrant.from_pydantic(dl.generate_general_zarr_access_grant(organization_id, user.pk, expires_in=model.expires_in))
