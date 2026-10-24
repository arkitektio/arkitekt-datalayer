"""Upload quotas: how many bytes an organization, a user in it, and one upload may take.

Set by the hub owner in the ``datalayer.quotas`` config block -- there is deliberately no
GraphQL surface to change them. Each limit resolves most specific first: the user's entry in
their organization, then the organization's entry, then ``default``. A limit left unset at every
level is unlimited, except the per-upload one, which falls back to the bucket's
``default_max_bytes`` so a grant always advertises *some* budget.

Checked when a grant is issued, never while bytes move: a session policy bounds what a
credential may write, not how much (see ``DatalayerStore.max_bytes``). Usage is therefore what
has been *measured* -- ``size_bytes`` of stores still in use -- and a grant is refused when that
plus the size the client declared would pass a limit. In-flight uploads are not reserved: a zarr
grant cannot declare a size, and reserving its advertised 500 GiB budget would lock a user out
after two pyramids. The cost is that an overrun is caught on the next grant rather than
prevented, which is the most S3 allows anyway.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from django.db.models import Sum
from pydantic import BaseModel, ByteSize, ConfigDict, Field

if TYPE_CHECKING:
    from authentikate.models import User


class QuotaLimits(BaseModel):
    """Byte limits at one level of the quota tree. ``None`` inherits from the level above."""

    model_config = ConfigDict(extra="ignore")

    max_upload_bytes: ByteSize | None = Field(default=None, description="Largest single store (upload) a user may write. Advertised on the grant as `maxBytes`; a declared `fileSize` above it is refused.")
    max_user_bytes: ByteSize | None = Field(default=None, description="Total bytes one user may hold in one organization. A new upload grant is refused once it would pass this.")


class OrganizationQuota(QuotaLimits):
    """An organization's limits, plus overrides for users inside it keyed by token ``sub``."""

    max_org_bytes: ByteSize | None = Field(default=None, description="Total bytes the whole organization may hold.")
    users: dict[str, QuotaLimits] = Field(default_factory=dict, description="Per-user overrides in this organization, keyed by the user's token `sub`.")


class QuotaConfig(BaseModel):
    """The ``datalayer.quotas`` block."""

    model_config = ConfigDict(extra="ignore")

    default: OrganizationQuota = Field(default_factory=OrganizationQuota, description="Limits for every organization without its own entry (its `users` map is ignored).")
    organizations: dict[str, OrganizationQuota] = Field(default_factory=dict, description="Per-organization quotas, keyed by the token `org` claim -- the lok organization *id* as a string (e.g. `3`), not a readable name.")


@dataclass(frozen=True)
class Quota:
    """The limits that apply to one user acting in one organization. ``None`` is unlimited."""

    max_upload_bytes: int | None
    max_user_bytes: int | None
    max_org_bytes: int | None


class QuotaExceeded(PermissionError):
    """An upload grant was refused because it would pass a configured quota."""


def _first(*values: int | None) -> int | None:
    return next((int(value) for value in values if value is not None), None)


def resolve_quota(config: QuotaConfig, organization_slug: str, user_sub: str | None) -> Quota:
    """Resolve the effective limits for ``user_sub`` in ``organization_slug``.

    ``organization_slug`` is ``Organization.slug`` -- the token's ``org`` claim, which is the
    issuer's organization *id* as a string, not a readable name.
    """
    org = config.organizations.get(organization_slug)
    user = org.users.get(user_sub) if org is not None and user_sub is not None else None
    levels = [level for level in (user, org, config.default) if level is not None]

    return Quota(
        max_upload_bytes=_first(*(level.max_upload_bytes for level in levels)),
        max_user_bytes=_first(*(level.max_user_bytes for level in levels)),
        max_org_bytes=_first(org.max_org_bytes if org is not None else None, config.default.max_org_bytes),
    )


def _usage(**filters) -> int:
    """Measured bytes held by the stores matching ``filters`` that are still in use."""
    from arkitekt_datalayer import models

    live = models.DatalayerStore.objects.filter(orphaned_at__isnull=True, size_bytes__isnull=False, **filters)
    return live.aggregate(total=Sum("size_bytes"))["total"] or 0


def organization_usage(organization_id: int) -> int:
    """Bytes the organization holds, including stores that predate creator tracking."""
    return _usage(organization_id=organization_id)


def user_usage(organization_id: int, user: "User") -> int:
    """Bytes ``user`` holds in the organization."""
    return _usage(organization_id=organization_id, creator=user)


def _gib(value: int) -> str:
    return f"{value / 1024**3:.2f} GiB"


def check_upload(quota: Quota, organization_id: int, user: Optional["User"], declared: int | None) -> None:
    """Refuse an upload that the quota does not admit. Raises :class:`QuotaExceeded`.

    ``declared`` is the size the client said it is about to write, if it said one.
    """
    if declared is not None and quota.max_upload_bytes is not None and declared > quota.max_upload_bytes:
        raise QuotaExceeded(f"Upload of {_gib(declared)} exceeds the per-upload quota of {_gib(quota.max_upload_bytes)}.")

    requested = declared or 0
    if quota.max_org_bytes is not None:
        used = organization_usage(organization_id)
        if used + requested > quota.max_org_bytes or used >= quota.max_org_bytes:
            raise QuotaExceeded(f"Organization storage quota reached: {_gib(used)} used of {_gib(quota.max_org_bytes)}, {_gib(requested)} requested.")

    if quota.max_user_bytes is not None and user is not None:
        used = user_usage(organization_id, user)
        if used + requested > quota.max_user_bytes or used >= quota.max_user_bytes:
            raise QuotaExceeded(f"Your storage quota in this organization is reached: {_gib(used)} used of {_gib(quota.max_user_bytes)}, {_gib(requested)} requested.")
