"""Upload, finish and read access for kulisse stores: device and scene models, each one GLB."""

from typing import cast

from kante.types import Info

from arkitekt_datalayer import inputs, models, types
from arkitekt_datalayer.context import caller
from arkitekt_datalayer.datalayer import get_current_datalayer


def request_kulisse_upload(info: Info, input: inputs.RequestKulisseUploadInput) -> types.KulisseUploadGrant:
    """Request temporary S3 upload credentials for a kulisse model."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    return types.KulisseUploadGrant.from_pydantic(dl.generate_kulisse_upload_grant(organization_id, input.to_pydantic(), user=user))


def finish_kulisse_upload(info: Info, input: inputs.FinishKulisseUploadInput) -> types.KulisseStore:
    """Finish a kulisse upload: the model is read, checked and described, or refused."""
    dl = get_current_datalayer()
    organization_id, _ = caller(info)
    return cast(types.KulisseStore, dl.finish_kulisse_upload(organization_id, input.to_pydantic()))


def request_kulisse_access(info: Info, input: inputs.RequestKulisseAccessInput) -> types.KulisseAccessGrant:
    """Request temporary S3 read credentials for a kulisse model."""
    dl = get_current_datalayer()
    organization_id, _ = caller(info)
    store = models.KulisseStore.objects.get(id=input.to_pydantic().store_id, organization_id=organization_id)
    return types.KulisseAccessGrant.from_pydantic(dl.generate_kulisse_access_grant(store))


def request_general_kulisse_access(info: Info, input: inputs.RequestGeneralKulisseAccessInput) -> types.GeneralKulisseAccessGrant:
    """Request temporary S3 read credentials for the organization's kulisse models."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    return types.GeneralKulisseAccessGrant.from_pydantic(dl.generate_general_kulisse_access_grant(organization_id, user.pk, input.to_pydantic().expires_in))
