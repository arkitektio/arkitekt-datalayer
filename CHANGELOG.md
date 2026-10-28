# CHANGELOG

<!-- version list -->

## v3.0.0 (2026-10-28)

### Features

- Upload_roles default to the service's own editor role
  ([`835c9e3`](https://github.com/arkitektio/arkitekt-datalayer/commit/835c9e3aedba0107554cf32bed674a7c7a2d1892))

### Breaking Changes

- A service that relied on the generic default has to fall back to its own role when `upload_roles`
  is empty.


## v2.0.0 (2026-10-27)

### Features

- Org-scoped keys, uploader-only uploads, abandoned-upload sweep, resumable refresh
  ([`61b3e87`](https://github.com/arkitektio/arkitekt-datalayer/commit/61b3e8775b15b73bdec6872e3627b665056d7cc6))

### Breaking Changes

- Requires authentikate>=6. Migrations restart at one 0001: every hub database and bucket must be
  reset. RefreshZarrUploadInput/RefreshSparseUploadInput are replaced by RefreshUploadInput;
  refresh_zarr_upload_grant/refresh_sparse_upload_grant by refresh_upload_grant; general access
  grants lose `path`/`store` and gain `prefix`; finish_* and refresh_* take the calling user.


## v1.1.0 (2026-10-24)

### Features

- KulisseStore, device and scene models as one self-contained GLB
  ([`6aba057`](https://github.com/arkitektio/arkitekt-datalayer/commit/6aba057324e1272cc13f9fe122169d6b13415f4d))


## v1.0.0 (2026-10-24)

- Initial Release
