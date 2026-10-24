"""Every datalayer mutation, wired the way a service wires them: uploads gated by ``upload_roles``."""

import kante
import strawberry
from authentikate.strawberry.directives import AuthExtension
from authentikate.strawberry.extension import AuthentikateExtension
from strawberry.schema.config import StrawberryConfig

from arkitekt_datalayer import mutations, scalars, types
from arkitekt_datalayer.datalayer import load_config


def upload_mutation(**kwargs) -> strawberry.mutation:  # noqa: ANN003
    """A mutation that hands out or finishes upload credentials, for ``datalayer.upload_roles`` only."""
    return kante.django_mutation(extensions=[AuthExtension(any_role_of=load_config().upload_roles)], **kwargs)


def mutation(**kwargs) -> strawberry.mutation:  # noqa: ANN003
    """A mutation for any authenticated member."""
    return kante.django_mutation(extensions=[AuthExtension()], **kwargs)


@strawberry.type
class Query:
    @strawberry.field
    def ping(self) -> str:
        """A query, because a schema needs one."""
        return "pong"


@strawberry.type
class Mutation:
    request_media_upload = upload_mutation(resolver=mutations.request_media_upload)
    finish_media_upload = upload_mutation(resolver=mutations.finish_media_upload)
    request_media_access = mutation(resolver=mutations.request_media_access)
    request_general_media_access = mutation(resolver=mutations.request_general_media_access)

    request_bigfile_upload = upload_mutation(resolver=mutations.request_bigfile_upload)
    finish_bigfile_upload = upload_mutation(resolver=mutations.finish_bigfile_upload)
    request_bigfile_access = mutation(resolver=mutations.request_bigfile_access)

    request_zarr_upload = upload_mutation(resolver=mutations.request_zarr_upload)
    finish_zarr_upload = upload_mutation(resolver=mutations.finish_zarr_upload)
    refresh_zarr_upload = upload_mutation(resolver=mutations.refresh_zarr_upload)
    request_zarr_access = mutation(resolver=mutations.request_zarr_access)
    request_general_zarr_access = mutation(resolver=mutations.request_general_zarr_access)

    request_parquet_upload = upload_mutation(resolver=mutations.request_parquet_upload)
    finish_parquet_upload = upload_mutation(resolver=mutations.finish_parquet_upload)
    request_parquet_access = mutation(resolver=mutations.request_parquet_access)

    request_sparse_upload = upload_mutation(resolver=mutations.request_sparse_upload)
    finish_sparse_upload = upload_mutation(resolver=mutations.finish_sparse_upload)
    refresh_sparse_upload = upload_mutation(resolver=mutations.refresh_sparse_upload)

    request_fabriks_upload = upload_mutation(resolver=mutations.request_fabriks_upload)
    finish_fabriks_upload = upload_mutation(resolver=mutations.finish_fabriks_upload)

    request_konnektion_upload = upload_mutation(resolver=mutations.request_konnektion_upload)
    finish_konnektion_upload = upload_mutation(resolver=mutations.finish_konnektion_upload)


schema = strawberry.federation.Schema(
    query=Query,
    mutation=Mutation,
    types=[types.BigFileStore, types.MediaStore, types.ZarrStore],
    config=StrawberryConfig(scalar_map={**scalars.SCALAR_MAP}),
    extensions=[AuthentikateExtension],
)
