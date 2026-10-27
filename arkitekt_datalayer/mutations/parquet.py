from typing import cast

from kante.types import Info

from arkitekt_datalayer import base_models, inputs, models, types
from arkitekt_datalayer.context import caller
from arkitekt_datalayer.datalayer import get_current_datalayer


def request_parquet_upload(info: Info, input: inputs.RequestParquetUploadInput) -> types.ParquetUploadGrant:
    """Request temporary S3 upload credentials for a parquet store."""
    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return types.ParquetUploadGrant.from_pydantic(dl.generate_parquet_upload_grant(organization_id, input_model, user=user))


def finish_parquet_upload(info: Info, input: inputs.FinishParquetUploadInput) -> types.ParquetStore:
    """Mark the ParquetStore as populated after a successful upload."""
    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return cast(types.ParquetStore, dl.finish_parquet_upload(organization_id, input_model, user=user))


def refresh_parquet_upload(info: Info, input: inputs.RefreshUploadInput) -> types.ParquetUploadGrant:
    """Reissue upload credentials for a parquet upload still in flight, to the same key."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    grant = dl.refresh_upload_grant(models.ParquetStore, organization_id, input.to_pydantic().store_id, user=user)
    return types.ParquetUploadGrant.from_pydantic(cast("base_models.ParquetUploadGrant", grant))


def request_parquet_access(info: Info, input: inputs.RequestParquetAccessInput) -> types.ParquetAccessGrant:
    """Request temporary S3 read credentials for a parquet file."""
    dl = get_current_datalayer()

    model = input.to_pydantic()

    store = models.ParquetStore.objects.get(id=model.store_id, organization=info.context.request.organization, populated=True, orphaned_at__isnull=True)
    return types.ParquetAccessGrant.from_pydantic(dl.generate_parquet_access_grant(store))


def request_general_parquet_access(info: Info, input: inputs.RequestGeneralParquetAccessInput) -> types.GeneralParquetAccessGrant:
    """Request temporary S3 read credentials for a parquet file."""

    dl = get_current_datalayer()
    model = input.to_pydantic()

    organization_id, user = caller(info)
    return types.GeneralParquetAccessGrant.from_pydantic(dl.generate_general_parquet_access_grant(organization_id, user.pk, expires_in=model.expires_in))
