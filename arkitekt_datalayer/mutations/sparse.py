"""Upload, finish, refresh and read-access for sparse stores.

The same quartet every store kind has, plus a refresh: a sparse matrix is written as a prefix
of three chunked arrays, and a write that outlives its session token dies partway through --
the problem `refreshZarrUpload` exists for, met sooner here because the matrices are large.
"""

from typing import cast

from kante.types import Info

from arkitekt_datalayer import base_models, inputs, models, types
from arkitekt_datalayer.context import caller
from arkitekt_datalayer.datalayer import get_current_datalayer


def request_sparse_upload(info: Info) -> types.SparseUploadGrant:
    """Request temporary S3 upload credentials for a sparse store."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    return types.SparseUploadGrant.from_pydantic(dl.generate_sparse_upload_grant(organization_id, user=user))


def finish_sparse_upload(info: Info, input: inputs.FinishSparseUploadInput) -> types.SparseStore:
    """Mark the SparseStore as populated after a successful upload.

    This is where the group's own metadata is read, and where a half-written tree is refused:
    a missing encoding, a missing array, or an `indptr` that contradicts the declared shape all
    fail here rather than surviving as a store a reader later discovers is broken.
    """
    dl = get_current_datalayer()
    input_model = input.to_pydantic()
    organization_id, user = caller(info)
    return cast(types.SparseStore, dl.finish_sparse_upload(organization_id, input_model, user=user))


def refresh_sparse_upload(info: Info, input: inputs.RefreshUploadInput) -> types.SparseUploadGrant:
    """Reissue upload credentials for a sparse upload still in flight, to the same key."""
    dl = get_current_datalayer()
    organization_id, user = caller(info)
    grant = dl.refresh_upload_grant(models.SparseStore, organization_id, input.to_pydantic().store_id, user=user)
    return types.SparseUploadGrant.from_pydantic(cast("base_models.SparseUploadGrant", grant))


def request_sparse_access(info: Info, input: inputs.RequestSparseAccessInput) -> types.SparseAccessGrant:
    """Request temporary S3 read credentials for a sparse store."""
    dl = get_current_datalayer()
    model = input.to_pydantic()
    store = models.SparseStore.objects.get(id=model.store_id, organization=info.context.request.organization, populated=True, orphaned_at__isnull=True)
    return types.SparseAccessGrant.from_pydantic(dl.generate_sparse_access_grant(store))


def request_general_sparse_access(info: Info, input: inputs.RequestGeneralSparseAccessInput) -> types.GeneralSparseAccessGrant:
    """Request temporary S3 read credentials for sparse stores in the organization."""
    dl = get_current_datalayer()
    model = input.to_pydantic()
    organization_id, user = caller(info)
    return types.GeneralSparseAccessGrant.from_pydantic(dl.generate_general_sparse_access_grant(organization_id, user.pk, expires_in=model.expires_in))
