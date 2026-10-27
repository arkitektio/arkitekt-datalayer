"""Kulisse models: the datalayer's own reader of the GLB wire format, and the store that uses it on RustFS."""

import json
import math
import struct
from typing import Any

import pytest
from authentikate.models import Organization
from botocore.exceptions import ClientError

from arkitekt_datalayer import models
from arkitekt_datalayer.kulisse import KulissePolicy, KulisseRefused, read_model

REQUEST = "mutation($name: String!, $size: ByteCount!) { requestKulisseUpload(input: {originalFileName: $name, fileSize: $size}) { accessKey secretKey sessionToken bucket key store maxBytes uploadContentType } }"
FINISH = "mutation($id: String!) { finishKulisseUpload(input: {storeId: $id}) { id ref specVersion generator bounds nodes joints warnings sizeBytes stats { nodes triangles textures animations } } }"
ACCESS = "mutation($id: String!) { requestKulisseAccess(input: {storeId: $id}) { accessKey secretKey sessionToken bucket key } }"


def glb(document: dict[str, Any], binary: bytes = b"") -> bytes:
    """A GLB container around ``document`` and ``binary``, padded as the format requires."""
    payload = json.dumps(document).encode()
    payload += b" " * (-len(payload) % 4)
    binary += b"\0" * (-len(binary) % 4)
    chunks = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    if binary:
        chunks += struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks


def triangle(**extra: Any) -> tuple[dict[str, Any], bytes]:
    """One triangle on a node called ``stage_x``, its box declared, under a translated ``turret``."""
    binary = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "kulisse 1"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [{"name": "turret", "translation": [10, 0, 0], "children": [1]}, {"name": "stage_x", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
    }
    document.update(extra)
    return document, binary


def read(data: bytes, policy: KulissePolicy | None = None):  # noqa: ANN201
    return read_model(lambda start, length: data[start : start + length], len(data), policy)


def refused(data: bytes, policy: KulissePolicy | None = None, size: int | None = None) -> KulisseRefused:
    with pytest.raises(KulisseRefused) as caught:
        read_model(lambda start, length: data[start : start + length], size if size is not None else len(data), policy)
    return caught.value


JOINTS = {"version": 1, "joints": [{"name": "x", "node": "stage_x", "type": "prismatic", "axis": [1, 0, 0], "limit": {"lower": 0, "upper": 0.1}}]}


# --- the reader -----------------------------------------------------------------------------


def test_a_model_is_described_from_its_header_and_json():
    manifest = read(glb(*triangle(extras={"arkitekt": JOINTS})))

    assert (manifest.spec_version, manifest.generator) == ("2.0", "kulisse 1")
    assert manifest.nodes == ["stage_x", "turret"]
    assert manifest.stats == {"nodes": 2, "triangles": 1, "textures": 0, "animations": 0}
    assert manifest.joints[0]["name"] == "x"
    assert manifest.bounds == {"min": [10, 0, 0], "max": [11, 1, 0]}, "the box is carried through the parent's translation"


def test_the_box_follows_a_rotation():
    document, binary = triangle()
    document["nodes"][0] = {"name": "turret", "rotation": [0, 0, math.sin(math.pi / 4), math.cos(math.pi / 4)], "children": [1]}
    bounds = read(glb(document, binary)).bounds

    assert bounds is not None
    assert [round(v, 6) for v in bounds["min"]] == [-1, 0, 0] and [round(v, 6) for v in bounds["max"]] == [0, 1, 0]


def test_only_the_head_and_the_json_chunk_are_read():
    data = glb(*triangle())
    asked: list[tuple[int, int]] = []

    def reader(start: int, length: int) -> bytes:
        asked.append((start, length))
        return data[start : start + length]

    read_model(reader, len(data))
    json_length = struct.unpack_from("<I", data, 12)[0]
    assert asked == [(0, 20), (20, json_length), (20 + json_length, 8)], "header, JSON chunk, binary chunk header -- never the binary chunk"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"not a model at all, definitely not", "bad_header"),
        (struct.pack("<III", 0x46546C67, 1, 20) + b"\0" * 8, "bad_header"),
        (glb({"asset": {"version": "1.0"}}), "bad_structure"),
    ],
)
def test_what_is_not_a_glb_2_is_refused(data: bytes, code: str):
    assert refused(data).code == code


def test_a_truncated_upload_is_refused():
    data = glb(*triangle())
    assert refused(data[:-8], size=len(data) - 8).code == "bad_header"


def test_a_model_carries_all_its_data():
    document, binary = triangle()
    document["buffers"][0]["uri"] = "elsewhere.bin"
    assert refused(glb(document, binary)).code == "external_reference"


def test_a_broken_joint_table_is_refused():
    table = {"version": 1, "joints": [{"name": "x", "node": "nowhere", "type": "prismatic", "axis": [1, 0, 0], "limit": {"lower": 0, "upper": 1}}]}
    assert refused(glb(*triangle(extras={"arkitekt": table}))).code == "bad_extras"
    assert refused(glb(*triangle(extras={"arkitekt": {"version": 2}}))).code == "bad_extras"


def test_the_policy_bounds_size_and_counts():
    data = glb(*triangle())
    assert refused(data, KulissePolicy(max_size=len(data) - 1)).code == "too_large"
    assert refused(data, KulissePolicy(max_triangles=0)).code == "over_budget"
    assert refused(glb(*triangle(extensionsRequired=["EXT_unknown"]))).code == "unsupported_extension"


def test_unconventional_names_and_ignored_extensions_are_warnings():
    document, binary = triangle(extensionsUsed=["EXT_unknown"])
    document["nodes"][1]["name"] = "Stage X"
    warnings = read(glb(document, binary)).warnings

    assert any("outside [a-z0-9_]+" in warning for warning in warnings)
    assert any("ignored by viewers" in warning for warning in warnings)


# --- the store on RustFS --------------------------------------------------------------------


async def test_a_model_upload_is_read_and_described_when_it_is_finished(aexecute, datalayer, client_s3):
    data = glb(*triangle(extras={"arkitekt": JOINTS}))
    grant = (await aexecute(REQUEST, {"name": "stage.glb", "size": len(data)})).data["requestKulisseUpload"]
    assert grant["uploadContentType"] == "model/gltf-binary"
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=data)

    finished = (await aexecute(FINISH, {"id": grant["store"]})).data["finishKulisseUpload"]

    import hashlib

    assert finished["ref"] == "sha256:" + hashlib.sha256(data).hexdigest()
    assert finished["bounds"] == {"min": [10, 0, 0], "max": [11, 1, 0]}
    assert finished["nodes"] == ["stage_x", "turret"] and finished["joints"][0]["node"] == "stage_x"
    assert finished["stats"] == {"nodes": 2, "triangles": 1, "textures": 0, "animations": 0}
    assert finished["sizeBytes"] == len(data)

    access = (await aexecute(ACCESS, {"id": grant["store"]})).data["requestKulisseAccess"]
    assert client_s3(access).get_object(Bucket=access["bucket"], Key=access["key"])["Body"].read() == data


async def test_a_file_that_is_not_a_model_fails_its_finish(aexecute, datalayer, client_s3):
    grant = (await aexecute(REQUEST, {"name": "notes.txt", "size": 28})).data["requestKulisseUpload"]
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=b"definitely not a binary glTF")

    result = await aexecute(FINISH, {"id": grant["store"]}, allow_errors=True)

    assert "not a binary glTF" in result.errors[0].message
    assert not (await models.KulisseStore.objects.aget(id=grant["store"])).populated


async def test_a_declared_size_over_the_policy_gets_no_grant(aexecute, datalayer, settings):
    settings.DATALAYER = {**settings.DATALAYER, "kulisse_policy": {"max_size": 100}}
    import arkitekt_datalayer.datalayer as dl_module

    dl_module.GLOBAL_DL = None
    result = await aexecute(REQUEST, {"name": "big.glb", "size": 101}, allow_errors=True)

    assert "over the limit of 100" in result.errors[0].message
    assert not await models.KulisseStore.objects.aexists()


async def test_another_organization_cannot_read_a_model(aexecute, datalayer, client_s3, other_org_context):
    data = glb(*triangle())
    grant = (await aexecute(REQUEST, {"name": "stage.glb", "size": len(data)})).data["requestKulisseUpload"]
    client_s3(grant).put_object(Bucket=grant["bucket"], Key=grant["key"], Body=data)
    await aexecute(FINISH, {"id": grant["store"]})

    assert (await aexecute(ACCESS, {"id": grant["store"]}, context=other_org_context, allow_errors=True)).errors
    with pytest.raises(ClientError):
        client_s3(grant).put_object(Bucket=grant["bucket"], Key=f"{grant['key']}-sibling", Body=data)


@pytest.fixture
def organization(transactional_db) -> Organization:  # noqa: ANN001
    return Organization.objects.create(identifier="static_issuer#static_org")


def test_a_model_the_server_writes_is_checked_too(datalayer, organization):
    store = datalayer.store_bytes(models.KulisseStore, organization.id, glb(*triangle()), original_file_name="stage.glb", content_type="model/gltf-binary")

    store.refresh_from_db()
    assert store.populated and store.nodes == ["stage_x", "turret"] and store.ref and store.ref.startswith("sha256:")

    with pytest.raises(KulisseRefused):
        datalayer.store_bytes(models.KulisseStore, organization.id, b"not a model, refused and gone")
    assert models.KulisseStore.objects.count() == 1, "a refused model leaves no row behind"
