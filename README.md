# arkitekt-datalayer

The `datalayer` Django app shared by arkitekt services: S3-backed store rows (media, big file,
zarr, parquet, sparse, fabriks, konnektion), scoped upload and read grants minted as STS
sessions, per-organization/user/upload quotas, and an orphan purge.

Install it as `arkitekt_datalayer`; its app label is `datalayer`, so tables are `datalayer_*`
and models are referenced as `"datalayer.MediaStore"`.

```python
INSTALLED_APPS = [..., "polymorphic", "authentikate", "arkitekt_datalayer"]
DATALAYER = conf.datalayer.model_dump(exclude_none=True) if conf.datalayer else {}
```

Embed `arkitekt_datalayer.configuration.DatalayerSettings` in the service's config model (narrow
the buckets it needs in a subclass). Without a `DATALAYER` setting the app still installs; grants
and writes then raise, naming the missing bucket.

What a service wires itself: the GraphQL mutations it exposes (`arkitekt_datalayer.mutations`,
gated by `load_config().upload_roles`), `scalars.SCALAR_MAP` in its schema config, and the store
types it declares in its hub contract. Deleting data rows should straddle the delete with
`storage.stores_orphaned_by` / `storage.flag_orphaned`; `manage.py purge_orphaned_stores`
collects them after `store_grace_days`.

Tests run against a real postgres and RustFS via dokker: `uv run pytest`.
