"""Fixtures: a real postgres and a real RustFS (tests/integration), two tenants, and a client-side upload.

* ``backend_stack`` -- brings the stack up and yields the host ports docker picked.
* ``datalayer`` -- points the datalayer at the stack's RustFS and creates every bucket.
* ``authenticated_context`` / ``viewer_context`` / ``other_org_context`` -- an editor of
  ``static_org``, a viewer of it (no upload role), and an editor of ``other_org``.
* ``aexecute`` -- runs a GraphQL document against ``test_project.schema``.
* ``client_s3`` -- an S3 client holding a grant's temporary credentials, as a client would.
"""

import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import boto3
import psycopg
import pytest
from authentikate.models import Client, Membership, Organization, User
from botocore.config import Config
from dokker import testing
from kante.context import HttpContext, UniversalRequest
from strawberry.http.temporal_response import TemporalResponse

from test_project.schema import schema

ROOT_KEY = "datalayerroot"
ROOT_SECRET = "datalayerrootsecret"


@dataclass
class Stack:
    """Where the test stack's services landed on this host."""

    db_port: int
    rustfs_port: int


def _wait(check: Callable[[], None], what: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            check()
            return
        except Exception:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{what} did not come up in {timeout}s")
            time.sleep(0.2)


@pytest.fixture(scope="session")
def backend_stack() -> Iterator[Stack]:
    """Bring up postgres + RustFS and yield their host ports.

    Ports are resolved inside the wait loop because ``up()`` may return before the containers
    publish them.
    """
    compose = Path(__file__).parent / "integration" / "docker-compose.yaml"
    with testing(str(compose)) as e:
        e.up()
        ports: dict[str, int] = {}

        def db_ready() -> None:
            if "db" not in ports:
                ports["db"] = e.get_port("db", 5432)
            with psycopg.connect(dbname="testdb", user="test", password="test", host="localhost", port=ports["db"], connect_timeout=1) as connection:
                connection.execute("SELECT 1")

        def rustfs_ready() -> None:
            if "rustfs" not in ports:
                ports["rustfs"] = e.get_port("rustfs", 9000)
            try:
                urllib.request.urlopen(f"http://localhost:{ports['rustfs']}/", timeout=1)
            except urllib.error.HTTPError:
                pass  # any S3 answer (403 to an anonymous request) means it is up

        _wait(db_ready, "postgres")
        _wait(rustfs_ready, "rustfs")
        yield Stack(db_port=ports["db"], rustfs_port=ports["rustfs"])


@pytest.fixture(scope="session")
def django_db_modify_db_settings(backend_stack: Stack) -> Iterator[None]:
    """Point Django at the stack's postgres before pytest-django creates the test database."""
    from django.conf import settings

    settings.DATABASES["default"]["PORT"] = str(backend_stack.db_port)
    yield


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker) -> Iterator[None]:  # noqa: ANN001
    """Kill asgiref's executor-thread connections before the test database is dropped."""
    yield
    from django.db import connections

    with django_db_blocker.unblock():
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()")
        connections.close_all()


def root_s3(port: int):  # noqa: ANN201 - boto3 client
    """An S3 client with the root keys: what the deployment's service account holds."""
    return boto3.client("s3", endpoint_url=f"http://localhost:{port}", aws_access_key_id=ROOT_KEY, aws_secret_access_key=ROOT_SECRET, region_name="us-east-1", config=Config(signature_version="s3v4"))


@pytest.fixture
def datalayer(backend_stack: Stack, settings):  # noqa: ANN001, ANN201
    """The datalayer pointed at the stack's RustFS, with every configured bucket created."""
    import arkitekt_datalayer.datalayer as dl_module

    settings.DATALAYER = {**settings.DATALAYER, "port": backend_stack.rustfs_port}
    dl_module.GLOBAL_DL = None
    s3 = root_s3(backend_stack.rustfs_port)
    existing = {bucket["Name"] for bucket in s3.list_buckets().get("Buckets", [])}
    for key in ("media", "bigfile", "zarr", "parquet", "fabriks", "konnektion", "kulisse"):
        bucket = settings.DATALAYER[key]["bucket"]
        if bucket not in existing:
            s3.create_bucket(Bucket=bucket)
            existing.add(bucket)
    yield dl_module.get_current_datalayer()
    dl_module.GLOBAL_DL = None


def _context(token: str, sub: str, org_slug: str, roles: list[str]) -> HttpContext:
    user, _ = User.objects.get_or_create(sub=sub, iss="static_issuer", defaults={"username": f"static_issuer_{sub}"})
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug=org_slug)
    membership, _ = Membership.objects.update_or_create(user=user, organization=org, defaults={"roles": roles})
    request = UniversalRequest(_extensions={"token": token}, _client=client, _user=user, _organization=org)  # type: ignore[arg-type]
    request.set_membership(membership)  # type: ignore[arg-type]
    return HttpContext(request=request, response=TemporalResponse(), headers={"Authorization": f"Bearer {token}"}, type="http")


@pytest.fixture
def authenticated_context(transactional_db) -> HttpContext:  # noqa: ANN001
    """An editor of ``static_org``: may upload."""
    return _context("test", "1", "static_org", ["editor"])


@pytest.fixture
def viewer_context(transactional_db) -> HttpContext:  # noqa: ANN001
    """A viewer of ``static_org``: holds no upload role."""
    return _context("viewer", "2", "static_org", ["viewer"])


@pytest.fixture
def other_org_context(transactional_db) -> HttpContext:  # noqa: ANN001
    """An editor of ``other_org``."""
    return _context("othertest", "9", "other_org", ["editor"])


@pytest.fixture
def aexecute(authenticated_context: HttpContext):  # noqa: ANN201
    """Run a GraphQL document as the editor (or ``context``); fails on GraphQL errors unless ``allow_errors``."""

    async def _run(query: str, variables: dict | None = None, context: HttpContext | None = None, allow_errors: bool = False):  # noqa: ANN202
        result = await schema.execute(query, variable_values=variables or {}, context_value=context or authenticated_context)
        if not allow_errors:
            assert not result.errors, result.errors
        return result

    return _run


@pytest.fixture
def client_s3(backend_stack: Stack):  # noqa: ANN201
    """Build an S3 client from a grant's temporary credentials, the way a client does."""

    def _client(grant: dict):  # noqa: ANN202
        return boto3.client(
            "s3",
            endpoint_url=f"http://localhost:{backend_stack.rustfs_port}",
            aws_access_key_id=grant["accessKey"],
            aws_secret_access_key=grant["secretKey"],
            aws_session_token=grant["sessionToken"],
            region_name="us-east-1",
            config=Config(signature_version="s3v4"),
        )

    return _client
