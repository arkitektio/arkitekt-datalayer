"""A DuckDB connection configured against the datalayer's S3 credentials.

**Lives here because it never depended on core.** It was written in mikro's ``core/duck.py`` and imported
nothing from the domain apps -- only settings and duckdb -- which is the description of a
storage backend. The move is what lets ``ParquetStore.fill_info`` read its own schema: a store
that has to ask ``core`` how to describe itself would invert the one dependency rule between
the two apps (core may import datalayer, never the reverse), and the rule is right -- every
other store reads its own metadata without leaving this app.

The queries themselves stay out of here. This class owns the *connection* -- the S3 secret and
nothing else -- while what to ask a parquet lives on :class:`~arkitekt_datalayer.datalayer.Datalayer`
beside ``get_zarr_metadata`` and ``get_sparse_metadata``, so all three store kinds answer the
same question in the same place.
"""

from functools import cached_property
from urllib.parse import urlparse

import duckdb

from arkitekt_datalayer.datalayer import load_config


class DuckLayer:
    """A DuckDB connection holding one S3 secret: the datalayer's own credentials."""

    @cached_property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """A DuckDB connection with the datalayer's S3 endpoint and credentials as its secret."""
        # The endpoint comes from the configured datalayer, not a literal: the host moved from
        # `minio` to `rustfs` and a hardcoded name resolves to nothing, so every parquet read
        # failed the HEAD with a DNS error. `netloc` (not `hostname`) because DuckDB's ENDPOINT
        # wants host:port bare -- no scheme, and dropping the port sends it to :80. USE_SSL is
        # read off the parsed scheme, since the datalayer may speak plain http.
        config = load_config()
        parsed = urlparse(config.endpoint_url or "")
        use_ssl = "true" if parsed.scheme == "https" else "false"

        secret_query = f"""
        CREATE SECRET secret1 (
            TYPE S3,
            KEY_ID '{config.access_key or ""}',
            SECRET '{config.secret_key or ""}',
            REGION '{config.region}',
            ENDPOINT '{parsed.netloc}',
            USE_SSL {use_ssl},
            URL_STYLE 'path'
        );
        """

        connection = duckdb.connect()
        connection.execute(secret_query)
        return connection

    def sql(self, query: str, params: dict[str, object] | None = None) -> duckdb.DuckDBPyRelation:
        """Run a query against the S3-configured connection and return the relation.

        Anything that came from outside -- a location, a path a manifest named -- goes in
        ``params`` and is referenced as ``$name``, never formatted into ``query``: this
        connection holds the datalayer's own S3 keys, so a quote smuggled into the text is a
        query run with them.
        """
        return self.connection.sql(query, params=params)


def get_current_duck() -> DuckLayer:
    """A fresh S3-configured DuckDB layer. Bind it to a name: the relation needs it alive."""
    return DuckLayer()
