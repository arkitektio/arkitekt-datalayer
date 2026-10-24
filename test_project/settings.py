"""Settings for the package's test suite: postgres and RustFS from tests/integration, ports set by conftest."""

import logging
import os

SECRET_KEY = "django-insecure-datalayer-tests-only"
DEBUG = True
ALLOWED_HOSTS: list[str] = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "polymorphic",
    "authentikate",
    "arkitekt_datalayer",
    "test_app",
]

AUTH_USER_MODEL = "authentikate.User"

AUTHENTIKATE = {
    "issuers": [{"kind": "jwks_dict", "iss": "placeholder_issuer", "jwks": {"keys": []}}],
    "audience": "datalayer",
    "allow_static_tokens_in_production": True,
    "static_tokens": {
        "test": {"sub": "1", "roles": ["editor"]},
        "viewer": {"sub": "2", "roles": ["viewer"]},
        "othertest": {"sub": "9", "org": "other_org", "roles": ["editor"]},
    },
}

# `conftest.backend_stack` overwrites the port with the one docker picked, before pytest-django
# creates the test database.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "testdb",
        "USER": "test",
        "PASSWORD": "test",
        "HOST": "localhost",
        "PORT": os.environ.get("DATALAYER_TEST_DB_PORT", "5432"),
    }
}

# S3 is the stack's RustFS; `conftest.datalayer` fills in its port and creates the buckets.
DATALAYER = {
    "access_key": "datalayerroot",
    "secret_key": "datalayerrootsecret",
    "host": "localhost",
    "port": 0,
    "protocol": "http",
    "region": "us-east-1",
    "role_arn": "arn:aws:iam::000000000000:role/datalayer",
    "session_name": "datalayer-tests",
    "media": {"bucket": "dl-media"},
    "bigfile": {"bucket": "dl-bigfile"},
    "zarr": {"bucket": "dl-zarr"},
    "parquet": {"bucket": "dl-parquet"},
    # Two logical buckets in one physical bucket, kept apart by their subpaths.
    "fabriks": {"bucket": "dl-collections", "subpath": "fabriks"},
    "konnektion": {"bucket": "dl-collections", "subpath": "konnektion"},
    "kulisse": {"bucket": "dl-kulisse"},
    "upload_roles": ["admin", "editor"],
}

USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "test_project.urls"

logging.disable(logging.CRITICAL)
