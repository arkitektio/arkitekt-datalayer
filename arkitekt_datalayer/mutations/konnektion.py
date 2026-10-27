"""Upload and read grants for konnektion stores.

The same four mutations every store type has, with one difference worth knowing: finishing a
konnektion upload is not bookkeeping. `fill_info` reads the store's manifest, so an interrupted
upload -- which presents as a prefix with no `konnektion.json`, because the writer lands it last
-- is refused here rather than registering as a store that a renderer later discovers is broken.
"""

from typing import cast

from kante.types import Info

from arkitekt_datalayer import base_models, inputs, models, types
from arkitekt_datalayer.context import caller
from arkitekt_datalayer.datalayer import get_current_datalayer


def request_konnektion_upload(info: Info) -> types.KonnektionUploadGrant:
    """Request temporary S3 upload credentials for a konnektion store's prefix."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    return types.KonnektionUploadGrant.from_pydantic(dl.generate_konnektion_upload_grant(organization_id, user=user))


def finish_konnektion_upload(info: Info, input: inputs.FinishKonnektionUploadInput) -> types.KonnektionStore:
    """Mark the KonnektionStore populated, reading its manifest to learn what was written."""
    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return cast(types.KonnektionStore, dl.finish_konnektion_upload(organization_id, input_model, user=user))


def refresh_konnektion_upload(info: Info, input: inputs.RefreshUploadInput) -> types.KonnektionUploadGrant:
    """Reissue upload credentials for a konnektion upload still in flight, to the same key."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    grant = dl.refresh_upload_grant(models.KonnektionStore, organization_id, input.to_pydantic().store_id, user=user)
    return types.KonnektionUploadGrant.from_pydantic(cast("base_models.KonnektionUploadGrant", grant))


def request_konnektion_access(info: Info, input: inputs.RequestKonnektionAccessInput) -> types.KonnektionAccessGrant:
    """Request temporary S3 read credentials covering a konnektion store's whole prefix."""
    dl = get_current_datalayer()

    model = input.to_pydantic()

    store = models.KonnektionStore.objects.get(id=model.store_id, organization=info.context.request.organization, populated=True, orphaned_at__isnull=True)
    return types.KonnektionAccessGrant.from_pydantic(dl.generate_konnektion_access_grant(store))


def request_general_konnektion_access(info: Info, input: inputs.RequestGeneralKonnektionAccessInput) -> types.GeneralKonnektionAccessGrant:
    """Request organization-wide temporary S3 read credentials for konnektion stores."""
    dl = get_current_datalayer()
    model = input.to_pydantic()

    organization_id, user = caller(info)
    return types.GeneralKonnektionAccessGrant.from_pydantic(dl.generate_general_konnektion_access_grant(organization_id, user.pk, expires_in=model.expires_in))
