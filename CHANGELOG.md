# CHANGELOG

<!-- version list -->

## v3.0.1 (2026-11-23)

### Bug Fixes

- Every argument and return annotated, no Any; tests typed
  ([`4b14ce3`](https://github.com/arkitektio/arkitekt-datalayer/commit/4b14ce3965ed949cc3029706eefb5a50df2bd9ab))

### Build System

- **deps**: Lock koil 3.4.1
  ([`b3a67fc`](https://github.com/arkitektio/arkitekt-datalayer/commit/b3a67fc3af244652cbb670c0340a9dccc968a13a))

### Code Style

- Adopt the arkitekt Python standard (ruff format, safe fixes)
  ([`17a2192`](https://github.com/arkitektio/arkitekt-datalayer/commit/17a2192cad0915a2640f7231a11c1003abe35c98))

- Sort imports and drop noqa directives that suppress nothing
  ([`3a7de50`](https://github.com/arkitektio/arkitekt-datalayer/commit/3a7de50573ac9089b46a865cfe51644d02fe8887))

### Continuous Integration

- The shared quality workflow, required, with a type-check baseline
  ([`215f198`](https://github.com/arkitektio/arkitekt-datalayer/commit/215f198ce8423ffaa46fb6eaa1af96c5d004a349))

### Refactoring

- Adopt Python 3.11 typing (X | None, builtin generics, collections.abc)
  ([`05b2778`](https://github.com/arkitektio/arkitekt-datalayer/commit/05b27789e70beea9204b57b9770bbba7cdd8db02))

- Type-check clean again
  ([`44f4fdf`](https://github.com/arkitektio/arkitekt-datalayer/commit/44f4fdfb19da3c6cb3c63c18961f3bdc5aeaaa6c))


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
