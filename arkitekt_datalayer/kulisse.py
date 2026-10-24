"""Reading a kulisse model -- one self-contained binary glTF -- without depending on kulisse.

`kulisse` is the library that *authors* this format (URDF import, the joint table, the client's
own copy of the rules). This module is the server's independent implementation of the same
contract, ``KULISSE.md`` in that package, for the reasons :mod:`arkitekt_datalayer.fabriks`
gives: a server that imports a writer inherits its dependencies (kulisse's importer needs numpy
and trimesh), a writer release must not be able to stop a server reading files it accepted, and
the format, not a shared module, is what both sides are held to.

**It reads by range, never the whole file.** A GLB is a 12-byte header, a JSON chunk and a binary
chunk. Everything a server checks or records is in the first two plus the binary chunk's 8-byte
header: the container, the structure, the joint table, the counts and the box the geometry
occupies (glTF requires ``min``/``max`` on every POSITION accessor). So a model of hundreds of
megabytes is registered by reading a few kilobytes of it. The binary chunk is measured, never
decoded, which is why texture sizes stay the client's check. The reference (the SHA-256 of the
exact bytes) is the one thing that needs every byte; the datalayer streams it separately.

Refusals raise :class:`KulisseRefused`, a ``ValueError`` carrying the code clients switch on.
"""

from __future__ import annotations

import json
import math
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

GLB_MAGIC = 0x46546C67  # "glTF"
CHUNK_JSON = 0x4E4F534A  # "JSON"
CHUNK_BIN = 0x004E4942  # "BIN\0"

#: The 12-byte header plus the first chunk's header.
HEAD_BYTES = 20

REF_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
NODE_NAME_PATTERN = re.compile(r"[a-z0-9_]+")
JOINT_TYPES = frozenset({"revolute", "continuous", "prismatic"})

#: Kept in step with ``KULISSE.md`` (the joint table's version) by the contract, not an import.
SUPPORTED_EXTRAS_VERSIONS = frozenset({1})

_COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}

DEFAULT_EXTENSIONS = frozenset(
    {
        "KHR_lights_punctual",
        "KHR_materials_emissive_strength",
        "KHR_materials_variants",
        "KHR_texture_transform",
        "KHR_mesh_quantization",
        "EXT_meshopt_compression",
        "KHR_draco_mesh_compression",
    }
)

Matrix = list[list[float]]
#: ``read(start, length)``: at most ``length`` bytes of the object from ``start``.
RangeReader = Callable[[int, int], bytes]


@dataclass(frozen=True)
class KulissePolicy:
    """The limits a model is held to when its store is finished."""

    max_size: int = 50 * 1024 * 1024
    max_json: int = 4 * 1024 * 1024
    max_nodes: int = 10_000
    max_triangles: int = 2_000_000
    max_animations: int = 64
    extensions: frozenset[str] = DEFAULT_EXTENSIONS


class KulisseRefused(ValueError):
    """A model that may not be registered, with the code clients switch on."""

    def __init__(self, code: str, message: str) -> None:
        """A refusal: ``code`` is what clients switch on, ``message`` what a person reads."""
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class KulisseManifest:
    """What a model says about itself, read off its header and JSON chunk."""

    spec_version: str
    generator: str | None
    #: ``{"min": [x, y, z], "max": [x, y, z]}`` of the default scene, or None when nothing declares a box.
    bounds: dict[str, list[float]] | None
    #: ``{"nodes", "triangles", "textures", "animations"}``.
    stats: dict[str, int]
    nodes: list[str]
    joints: list[dict[str, Any]]
    extensions_used: list[str]
    warnings: list[str] = field(default_factory=list)


def check_ref(ref: str) -> None:
    """Refuse a reference that is not ``sha256:`` and 64 lowercase hex digits."""
    if not REF_PATTERN.fullmatch(ref):
        raise KulisseRefused("bad_reference", f"a model reference is 'sha256:' and 64 lowercase hex characters, not {ref!r}")


def read_model(read: RangeReader, size: int, policy: KulissePolicy | None = None, *, where: str = "the model") -> KulisseManifest:
    """Read and check the model whose object is ``size`` bytes, through ``read``.

    Raises:
        KulisseRefused: If the file is not a model this server registers.
    """
    policy = policy or KulissePolicy()
    if size > policy.max_size:
        raise KulisseRefused("too_large", f"{where} is {size} bytes, over the limit of {policy.max_size}")
    document, binary_length = _read_chunks(read, size, policy, where)
    warnings: list[str] = []
    _check_self_contained(document)
    _check_extensions(document, policy, warnings)
    _check_bounds(document, binary_length)
    node_names = _node_names(document, warnings)
    joints = _joints(document, node_names)
    stats = _stats(document)
    _check_counts(stats, policy)
    asset = document["asset"]
    generator = asset.get("generator")
    used = document.get("extensionsUsed", [])
    return KulisseManifest(
        spec_version=str(asset["version"]),
        generator=generator if isinstance(generator, str) else None,
        bounds=scene_bounds(document),
        stats=stats,
        nodes=sorted(node_names),
        joints=joints,
        extensions_used=sorted(str(name) for name in used),
        warnings=warnings,
    )


def _read_chunks(read: RangeReader, size: int, policy: KulissePolicy, where: str) -> tuple[dict[str, Any], int]:
    """The parsed JSON chunk and the length of the binary chunk (0 when there is none)."""
    if size < HEAD_BYTES:
        raise KulisseRefused("bad_header", f"{where} is shorter than a GLB header and one chunk header")
    head = read(0, HEAD_BYTES)
    if len(head) < HEAD_BYTES:
        raise KulisseRefused("bad_header", f"{where} is shorter than a GLB header and one chunk header")
    magic, version, declared = struct.unpack_from("<III", head, 0)
    if magic != GLB_MAGIC:
        raise KulisseRefused(
            "bad_header",
            f"{where} is not a binary glTF: it does not start with the glTF magic. Export it as a .glb -- a .gltf with separate buffers is several files, and a model is one.",
        )
    if version != 2:
        raise KulisseRefused("bad_header", f"{where} is a glTF {version} container; only 2 is read. Re-export it from a current exporter.")
    if declared != size:
        raise KulisseRefused("bad_header", f"{where} declares {declared} bytes but the stored object has {size}: the upload is truncated or the file is damaged")

    json_length, json_type = struct.unpack_from("<II", head, 12)
    if json_type != CHUNK_JSON:
        raise KulisseRefused("bad_structure", f"{where} does not begin with the JSON chunk")
    if json_length > policy.max_json:
        raise KulisseRefused("bad_structure", f"the JSON chunk of {where} is {json_length} bytes, over the limit of {policy.max_json}")
    json_end = HEAD_BYTES + json_length
    if json_end > size:
        raise KulisseRefused("bad_structure", f"the JSON chunk of {where} runs past the end of the file")
    try:
        document = json.loads(read(HEAD_BYTES, json_length).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise KulisseRefused("bad_structure", f"the JSON chunk of {where} does not parse: {error}") from error
    if not isinstance(document, dict):
        raise KulisseRefused("bad_structure", f"the JSON chunk of {where} is not an object")
    asset = document.get("asset")
    if not isinstance(asset, dict) or asset.get("version") != "2.0":
        raise KulisseRefused("bad_structure", "asset.version must be '2.0'")

    binary_length = 0
    if json_end < size:
        if json_end + 8 > size:
            raise KulisseRefused("bad_structure", "a chunk header is cut off after the JSON chunk")
        binary_length, binary_type = struct.unpack_from("<II", read(json_end, 8), 0)
        if binary_type != CHUNK_BIN:
            raise KulisseRefused("bad_structure", "the chunk after the JSON chunk is not the binary chunk")
        if json_end + 8 + binary_length > size:
            raise KulisseRefused("bad_structure", "the binary chunk runs past the end of the file")
    return document, binary_length


def _items(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise KulisseRefused("bad_structure", f"'{key}' must be a list of objects")
    return value


def _check_self_contained(document: dict[str, Any]) -> None:
    for key in ("buffers", "images"):
        for index, item in enumerate(_items(document, key)):
            if "uri" in item:
                raise KulisseRefused("external_reference", f"{key}[{index}] has a uri; a model carries all its data in its binary chunk")


def _check_extensions(document: dict[str, Any], policy: KulissePolicy, warnings: list[str]) -> None:
    required = document.get("extensionsRequired", [])
    used = document.get("extensionsUsed", [])
    if not isinstance(required, list) or not isinstance(used, list):
        raise KulisseRefused("bad_structure", "extensionsRequired and extensionsUsed must be lists")
    refused = sorted(set(required) - policy.extensions)
    if refused:
        raise KulisseRefused("unsupported_extension", f"the model requires extensions that are not allowed: {refused}")
    ignored = sorted(set(used) - set(required) - policy.extensions)
    if ignored:
        warnings.append(f"extensions used but not supported are ignored by viewers: {ignored}")


def _is_fallback_buffer(buffer: dict[str, Any]) -> bool:
    """A meshopt fallback buffer has a length but no data in the file."""
    extensions = buffer.get("extensions", {})
    extension = extensions.get("EXT_meshopt_compression") if isinstance(extensions, dict) else None
    return isinstance(extension, dict) and extension.get("fallback") is True


def _span(item: dict[str, Any], what: str) -> tuple[int, int]:
    offset, length = item.get("byteOffset", 0), item.get("byteLength")
    if not isinstance(offset, int) or not isinstance(length, int) or offset < 0 or length < 0:
        raise KulisseRefused("bad_structure", f"{what} needs a non-negative integer byteOffset and byteLength")
    return offset, length


def _check_bounds(document: dict[str, Any], binary_length: int) -> None:
    """Every buffer, view and accessor lies inside the bytes it claims, measured, never decoded."""
    buffers = _items(document, "buffers")
    views = _items(document, "bufferViews")
    for index, buffer in enumerate(buffers):
        if _is_fallback_buffer(buffer):
            continue
        if index != 0:
            raise KulisseRefused("bad_structure", f"buffers[{index}] has no data: only the first buffer is the binary chunk")
        _, length = _span(buffer, "buffers[0]")
        if length > binary_length:
            raise KulisseRefused("bad_structure", f"buffers[0] declares {length} bytes but the binary chunk has {binary_length}")

    def check_view(what: str, source: dict[str, Any]) -> None:
        buffer_index = source.get("buffer")
        if not isinstance(buffer_index, int) or not 0 <= buffer_index < len(buffers):
            raise KulisseRefused("bad_structure", f"{what} names a buffer that does not exist")
        offset, length = _span(source, what)
        if offset + length > _span(buffers[buffer_index], f"buffers[{buffer_index}]")[1]:
            raise KulisseRefused("bad_structure", f"{what} runs past the end of buffers[{buffer_index}]")

    for index, view in enumerate(views):
        check_view(f"bufferViews[{index}]", view)
        extensions = view.get("extensions", {})
        compressed = extensions.get("EXT_meshopt_compression") if isinstance(extensions, dict) else None
        if isinstance(compressed, dict):
            check_view(f"bufferViews[{index}] (compressed)", compressed)

    for index, accessor in enumerate(_items(document, "accessors")):
        count = accessor.get("count")
        if not isinstance(count, int) or count < 0:
            raise KulisseRefused("bad_structure", f"accessors[{index}] needs a non-negative integer count")
        view_index = accessor.get("bufferView")
        if view_index is None:
            continue
        if not isinstance(view_index, int) or not 0 <= view_index < len(views):
            raise KulisseRefused("bad_structure", f"accessors[{index}] names a bufferView that does not exist")
        component_type, kind = accessor.get("componentType"), accessor.get("type")
        component = _COMPONENT_BYTES.get(component_type) if isinstance(component_type, int) else None
        components = _TYPE_COMPONENTS.get(kind) if isinstance(kind, str) else None
        if component is None or components is None:
            raise KulisseRefused("bad_structure", f"accessors[{index}] has an unknown componentType or type")
        element = component * components
        view = views[view_index]
        stride = view.get("byteStride", element)
        offset = accessor.get("byteOffset", 0)
        if not isinstance(stride, int) or not isinstance(offset, int) or stride < 0 or offset < 0:
            raise KulisseRefused("bad_structure", f"accessors[{index}] has an invalid byteOffset or byteStride")
        needed = offset + (stride * (count - 1) + element if count else 0)
        if needed > _span(view, f"bufferViews[{view_index}]")[1]:
            raise KulisseRefused("bad_structure", f"accessors[{index}] runs past the end of bufferViews[{view_index}]")


def _node_names(document: dict[str, Any], warnings: list[str]) -> set[str]:
    """The names a blok can address. Unnamed nodes are fine; a repeated name is not addressable."""
    names: set[str] = set()
    repeated: set[str] = set()
    unconventional: set[str] = set()
    for node in _items(document, "nodes"):
        name = node.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name in names:
            repeated.add(name)
        names.add(name)
        if not NODE_NAME_PATTERN.fullmatch(name):
            unconventional.add(name)
    if repeated:
        warnings.append(f"node names used more than once cannot be bound reliably: {sorted(repeated)}")
    if unconventional:
        warnings.append(f"node names outside [a-z0-9_]+: {sorted(unconventional)}")
    return names


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _joints(document: dict[str, Any], node_names: set[str]) -> list[dict[str, Any]]:
    """The joint table of ``extras.arkitekt``, checked against the model; empty when it has none."""
    extras = document.get("extras")
    arkitekt = extras.get("arkitekt") if isinstance(extras, dict) else None
    if arkitekt is None:
        return []

    def fail(message: str) -> KulisseRefused:
        return KulisseRefused("bad_extras", f"extras.arkitekt: {message}")

    if not isinstance(arkitekt, dict):
        raise fail("must be an object")
    if arkitekt.get("version") not in SUPPORTED_EXTRAS_VERSIONS:
        raise fail(f"version {arkitekt.get('version')!r} is not supported, only {sorted(SUPPORTED_EXTRAS_VERSIONS)}")
    joints = arkitekt.get("joints", [])
    if not isinstance(joints, list):
        raise fail("joints must be a list")
    source = arkitekt.get("source")
    if source is not None and not (isinstance(source, str) and REF_PATTERN.fullmatch(source)):
        raise fail("source must be a sha256: reference")

    joint_names: set[str] = set()
    driven: set[str] = set()
    for index, joint in enumerate(joints):
        where = f"joints[{index}]"
        if not isinstance(joint, dict):
            raise fail(f"{where} must be an object")
        name, node, kind, axis = joint.get("name"), joint.get("node"), joint.get("type"), joint.get("axis")
        if not isinstance(name, str) or not name:
            raise fail(f"{where} needs a name")
        if name in joint_names:
            raise fail(f"joint {name!r} is defined twice")
        joint_names.add(name)
        if node not in node_names:
            raise fail(f"joint {name!r} drives node {node!r}, which the model does not have")
        if node in driven:
            raise fail(f"node {node!r} is driven by more than one joint")
        driven.add(node)
        if kind not in JOINT_TYPES:
            raise fail(f"joint {name!r} has type {kind!r}; supported are {sorted(JOINT_TYPES)}")
        if not (isinstance(axis, list) and len(axis) == 3 and all(_number(component) for component in axis)):
            raise fail(f"joint {name!r} needs an axis of three numbers")
        if abs(math.sqrt(sum(component * component for component in axis)) - 1.0) > 1e-3:
            raise fail(f"the axis of joint {name!r} is not a unit vector")
        limit = joint.get("limit")
        if kind == "continuous":
            if limit is not None:
                raise fail(f"continuous joint {name!r} has no limit")
        else:
            if not (isinstance(limit, dict) and _number(limit.get("lower")) and _number(limit.get("upper"))):
                raise fail(f"joint {name!r} needs a limit with lower and upper")
            if limit["lower"] > limit["upper"]:
                raise fail(f"the limit of joint {name!r} has lower above upper")

    for joint in joints:
        mimic = joint.get("mimic")
        if mimic is None:
            continue
        if not (isinstance(mimic, dict) and _number(mimic.get("multiplier", 1.0)) and _number(mimic.get("offset", 0.0))):
            raise fail(f"the mimic of joint {joint['name']!r} needs a numeric multiplier and offset")
        if mimic.get("joint") not in joint_names or mimic.get("joint") == joint["name"]:
            raise fail(f"joint {joint['name']!r} mimics {mimic.get('joint')!r}, which is not another joint of this model")
    return joints


def _stats(document: dict[str, Any]) -> dict[str, int]:
    accessors = _items(document, "accessors")

    def count_of(index: object) -> int:
        if not isinstance(index, int) or not 0 <= index < len(accessors):
            raise KulisseRefused("bad_structure", "a mesh primitive names an accessor that does not exist")
        return int(accessors[index].get("count", 0))

    triangles = 0
    for mesh in _items(document, "meshes"):
        primitives = mesh.get("primitives", [])
        if not isinstance(primitives, list):
            raise KulisseRefused("bad_structure", "mesh primitives must be a list")
        for primitive in primitives:
            if not isinstance(primitive, dict):
                raise KulisseRefused("bad_structure", "a mesh primitive must be an object")
            mode = primitive.get("mode", 4)
            if mode not in (4, 5, 6):
                continue
            attributes = primitive.get("attributes", {})
            if "indices" in primitive:
                vertices = count_of(primitive["indices"])
            elif isinstance(attributes, dict) and "POSITION" in attributes:
                vertices = count_of(attributes["POSITION"])
            else:
                continue
            triangles += vertices // 3 if mode == 4 else max(vertices - 2, 0)

    return {
        "nodes": len(_items(document, "nodes")),
        "triangles": triangles,
        "textures": len(_items(document, "images")),
        "animations": len(_items(document, "animations")),
    }


def _check_counts(stats: dict[str, int], policy: KulissePolicy) -> None:
    for what, key, limit in (
        ("nodes", "nodes", policy.max_nodes),
        ("triangles", "triangles", policy.max_triangles),
        ("animation clips", "animations", policy.max_animations),
    ):
        if stats[key] > limit:
            raise KulisseRefused("over_budget", f"the model has {stats[key]} {what}, over the limit of {limit}")


def _identity() -> Matrix:
    return [[1.0 if row == column else 0.0 for column in range(4)] for row in range(4)]


def _multiply(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[row][k] * b[k][column] for k in range(4)) for column in range(4)] for row in range(4)]


def _node_matrix(node: dict[str, Any]) -> Matrix:
    """A node's local transform: its ``matrix`` (column-major), or its translation · rotation · scale."""
    if "matrix" in node:
        m = node["matrix"]
        return [[float(m[column * 4 + row]) for column in range(4)] for row in range(4)]
    tx, ty, tz = node.get("translation", [0.0, 0.0, 0.0])
    qx, qy, qz, qw = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    sx, sy, sz = node.get("scale", [1.0, 1.0, 1.0])
    rotation = [
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ]
    scale = (sx, sy, sz)
    out = _identity()
    for row in range(3):
        for column in range(3):
            out[row][column] = rotation[row][column] * scale[column]
    out[0][3], out[1][3], out[2][3] = tx, ty, tz
    return out


def scene_bounds(document: dict[str, Any]) -> dict[str, list[float]] | None:
    """The box the default scene's geometry occupies, in the file's own coordinates, or None.

    Each primitive's POSITION accessor box is carried through its node's world transform --
    corner by corner, so a rotated part is boxed where it is drawn rather than where its
    vertices were written. None when nothing in the scene declares a box: glTF requires the
    bounds, but an exporter that skips them has said nothing this can repeat.
    """
    nodes = document.get("nodes", [])
    meshes = document.get("meshes", [])
    accessors = document.get("accessors", [])
    scenes = document.get("scenes", [])
    if scenes:
        roots = scenes[document.get("scene", 0)].get("nodes", [])
    else:
        # No scene: every node no other node names as a child is a root.
        children = {child for node in nodes for child in node.get("children", [])}
        roots = [index for index in range(len(nodes)) if index not in children]

    low = [math.inf] * 3
    high = [-math.inf] * 3
    stack: list[tuple[int, Matrix]] = [(root, _identity()) for root in roots]
    seen: set[int] = set()
    while stack:
        index, parent = stack.pop()
        if index in seen or index >= len(nodes):
            continue
        seen.add(index)
        node = nodes[index]
        world = _multiply(parent, _node_matrix(node))
        mesh_index = node.get("mesh")
        if mesh_index is not None and mesh_index < len(meshes):
            for primitive in meshes[mesh_index].get("primitives", []):
                position = primitive.get("attributes", {}).get("POSITION")
                if position is None or position >= len(accessors):
                    continue
                accessor = accessors[position]
                if "min" not in accessor or "max" not in accessor:
                    continue
                lo, hi = accessor["min"], accessor["max"]
                for corner in range(8):
                    point = [hi[axis] if corner >> axis & 1 else lo[axis] for axis in range(3)]
                    for axis in range(3):
                        value = sum(world[axis][k] * point[k] for k in range(3)) + world[axis][3]
                        low[axis] = min(low[axis], value)
                        high[axis] = max(high[axis], value)
        stack.extend((child, world) for child in node.get("children", []))

    if not all(math.isfinite(value) for value in (*low, *high)):
        return None
    return {"min": low, "max": high}
