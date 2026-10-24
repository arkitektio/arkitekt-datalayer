"""The ``datalayer`` block of a service's config file.

A service embeds :class:`DatalayerSettings` in its own settings model and hands the dumped block
to Django as ``settings.DATALAYER``::

    DATALAYER = conf.datalayer.model_dump(exclude_none=True) if conf.datalayer else {}

Every bucket is optional here, because which ones a service needs is the service's business. A
service that cannot run without one narrows it in a subclass::

    class MikroDatalayerSettings(DatalayerSettings):
        zarr: DatalayerBucket = Field(description="Bucket for Zarr arrays.")

A bucket left unset makes every grant or write for its stores raise, naming the missing key; a
service with no block at all still installs the app and gets its tables.
"""

from pydantic import BaseModel, ByteSize, ConfigDict, Field

from arkitekt_datalayer.quota import QuotaConfig


class DatalayerBucket(BaseModel):
    """A single S3 bucket binding within the datalayer."""

    model_config = ConfigDict(extra="ignore")

    bucket: str = Field(description="S3 bucket name.")
    # Two logical buckets may point at one physical bucket, and the subpath is what keeps their
    # objects apart. It reaches the grant policy through `build_object_key`, so getting it wrong
    # widens or narrows what a client can read.
    subpath: str | None = Field(default=None, description="Optional key prefix within the bucket, so several logical buckets can share one physical bucket.")
    default_max_bytes: ByteSize | None = Field(default=None, description="Per-upload byte budget advertised on this bucket's grants when no quota sets `max_upload_bytes`. Accepts `500GiB`-style strings. Unset: 100 MiB.")


class DatalayerSettings(BaseModel):
    """S3 storage connection, buckets, upload roles and quotas."""

    model_config = ConfigDict(extra="ignore")

    access_key: str = Field(description="S3 access key. Secret -- must be set.")
    secret_key: str = Field(description="S3 secret key. Secret -- must be set.")
    host: str | None = Field(default=None, description="S3 endpoint host.")
    port: int | None = Field(default=None, description="S3 endpoint port.")
    protocol: str = Field(default="http", description="S3 endpoint protocol (http or https).")
    region: str = Field(default="us-east-1", description="S3 region name.")

    role_arn: str | None = Field(default=None, description="Role assumed to mint scoped credentials. Against an object store without IAM roles (RustFS, MinIO) any ARN-shaped string will do: the session is scoped by its inline policy alone.")
    external_id: str | None = Field(default=None, description="External id passed when assuming `role_arn`.")
    session_duration_seconds: int = Field(default=3600, description="Lifetime of a grant's credentials, clamped to what STS accepts (900 to 43200).")
    session_name: str = Field(default="datalayer", description="Prefix of every STS session this service assumes, so an object store's audit log names the service. Set it to the service name.")
    allow_unscoped_fallback: bool = Field(default=False, description="Hand out this service's own permanent credentials when no scoped session can be issued. Development only.")
    store_grace_days: int = Field(default=7, description="How long an orphaned store is kept before `purge_orphaned_stores` deletes its bytes.")

    media: DatalayerBucket | None = Field(default=None, description="Bucket for media files (MediaStore).")
    bigfile: DatalayerBucket | None = Field(default=None, description="Bucket for large binary files (BigFileStore).")
    zarr: DatalayerBucket | None = Field(default=None, description="Bucket for Zarr arrays and sparse matrices (ZarrStore, SparseStore).")
    parquet: DatalayerBucket | None = Field(default=None, description="Bucket for Parquet tables (ParquetStore).")
    fabriks: DatalayerBucket | None = Field(default=None, description="Bucket for fabriks stores: mesh collections stored as a prefix of Parquet files.")
    konnektion: DatalayerBucket | None = Field(default=None, description="Bucket for konnektion stores: network collections stored as a prefix of Parquet files.")

    upload_roles: list[str] = Field(default_factory=lambda: ["admin", "editor", "bot"], description="Organization roles allowed to request upload grants. Holding any one of them is enough.")
    quotas: QuotaConfig = Field(default_factory=QuotaConfig, description="Per-organization, per-user and per-upload byte quotas.")
