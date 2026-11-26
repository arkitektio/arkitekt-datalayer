"""What a single-object store's bytes are: its canonical digest, and the sampled fingerprint.

Two values, for two questions, and both computed the same way by every party -- the server,
the app, the Python client -- so this module is the reference they are written against.

**The digest** answers "are these the same bytes?". It is the SHA-256 *composite* S3 itself
computes for a multipart upload: the SHA-256 of the concatenated SHA-256s of the parts, with
the parts cut at :func:`part_size_for` the object's size. That definition is chosen so the
object store verifies it for free: a client that uploads in those parts with SHA-256
checksums has every part checked on arrival (a mismatch is refused with ``BadDigest``), and
the composite S3 reports on ``HeadObject`` is then this digest, trusted without reading a
byte. Anything else -- no checksum, another algorithm, other part sizes -- is still given the
same digest, by streaming the object once (:class:`CompositeHasher`). The part size follows
from the size alone, so two uploads of the same bytes always agree, and it grows with the
object so a part count never passes S3's 10,000.

A client that cut its parts differently is not refused and cannot make a false duplicate: its
composite is simply not this digest, and the store is hashed again.

**The sample** answers "might this be one I already have?", before an upload, cheaply: the
SHA-256 of the size (ASCII decimal and a newline) followed by three windows of the object --
the first, the middle and the last :data:`SAMPLE_WINDOW` bytes, or the whole object when it is
no larger than three windows. A match is a candidate, not a proof: two files that agree in
size and in those windows are almost always the same file, and the digest settles it.
"""

import base64
import binascii
import hashlib
from collections.abc import Callable, Iterable

MiB = 1024 * 1024

#: The smallest part a digest is cut into. Above S3's 5 MiB floor for every part but the last.
PART_FLOOR = 8 * MiB

#: S3's ceiling on the parts of one multipart upload.
MAX_PARTS = 10_000

#: How much of the object each of the sample's three windows reads.
SAMPLE_WINDOW = 4 * MiB

#: The name the digest is stored under: S3's SHA-256 composite over :func:`part_size_for` parts.
ALGORITHM = "sha256-composite"


def part_size_for(size: int) -> int:
    """The part size a digest of ``size`` bytes is cut at: :data:`PART_FLOOR`, doubled until the parts fit S3's ceiling."""
    part = PART_FLOOR
    while size > part * MAX_PARTS:
        part *= 2
    return part


def part_count(size: int) -> int:
    """How many parts a digest of ``size`` bytes has: at least one, an empty object's included."""
    part = part_size_for(size)
    return max(1, -(-size // part))


def composite_of(part_digests: Iterable[bytes]) -> str:
    """The hex digest over parts whose raw SHA-256 digests are ``part_digests``, in order."""
    outer = hashlib.sha256()
    for digest in part_digests:
        outer.update(digest)
    return outer.hexdigest()


def composite_of_bytes(data: bytes) -> str:
    """The digest of ``data``, held whole in memory: a reference for tests and small objects."""
    hasher = CompositeHasher(len(data))
    hasher.update(data)
    return hasher.hexdigest()


class CompositeHasher:
    """Computes the digest of an object streamed through it in chunks of any size.

    Args:
        size: The object's size, which fixes where its parts are cut.
    """

    def __init__(self, size: int) -> None:
        self.size = size
        self.part_size = part_size_for(size)
        self._parts: list[bytes] = []
        self._current = hashlib.sha256()
        self._filled = 0
        self._seen = 0

    def update(self, chunk: bytes) -> None:
        """Feed the next bytes of the object."""
        view = memoryview(chunk)
        while view:
            room = self.part_size - self._filled
            take = view[:room]
            self._current.update(take)
            self._filled += len(take)
            self._seen += len(take)
            view = view[len(take) :]
            if self._filled == self.part_size:
                self._parts.append(self._current.digest())
                self._current = hashlib.sha256()
                self._filled = 0

    def hexdigest(self) -> str:
        """The digest, once every byte has been fed.

        Raises:
            ValueError: If more or fewer bytes were fed than the size promised -- the object
                changed under the read, or the size was wrong.
        """
        if self._seen != self.size:
            raise ValueError(
                f"The object was {self._seen} bytes, not the {self.size} it was measured at, so its digest would describe other bytes."
            )
        parts = list(self._parts)
        if self._filled or not parts:
            parts.append(self._current.digest())
        return composite_of(parts)


def digest_from_checksum(checksum_sha256: str | None, size: int) -> str | None:
    """The digest an object store's own SHA-256 checksum already says, or ``None`` when it says none.

    The store verified the checksum against the bytes as they arrived, so what it reports is
    trusted. Two shapes are read: a composite ``<base64>-N`` whose ``N`` is the part count the
    digest's parts would have (the parts themselves cannot be seen; one cut differently gives a
    composite that is not the digest, and the object is hashed again), and a plain checksum of
    an object written in one request, which is the digest's single part when the object fits
    in one.

    Args:
        checksum_sha256: ``ChecksumSHA256`` as ``HeadObject`` returns it, if it returned one.
        size: The object's size.
    """
    if not checksum_sha256:
        return None
    encoded, _, count = checksum_sha256.partition("-")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) != hashlib.sha256().digest_size:
        return None
    if count:
        if not count.isdigit() or int(count) != part_count(size):
            return None
        return raw.hex()
    if part_count(size) != 1:
        return None
    return composite_of([raw])


def sample_ranges(size: int) -> list[tuple[int, int]]:
    """The ``(start, length)`` windows the sample reads: the whole object, or its first, middle and last window."""
    if size <= 3 * SAMPLE_WINDOW:
        return [(0, size)] if size else []
    return [
        (0, SAMPLE_WINDOW),
        ((size - SAMPLE_WINDOW) // 2, SAMPLE_WINDOW),
        (size - SAMPLE_WINDOW, SAMPLE_WINDOW),
    ]


def sample_of(size: int, read: Callable[[int, int], bytes]) -> str:
    """The sample of an object of ``size`` bytes, reading its windows through ``read(start, length)``.

    Raises:
        ValueError: If a window came back shorter than asked: the object is smaller than ``size``.
    """
    digest = hashlib.sha256(f"{size}\n".encode())
    for start, length in sample_ranges(size):
        window = read(start, length)
        if len(window) != length:
            raise ValueError(
                f"The window at {start} held {len(window)} bytes, not {length}: the object is not the {size} bytes it was measured at."
            )
        digest.update(window)
    return digest.hexdigest()


def sample_of_bytes(data: bytes) -> str:
    """The sample of ``data`` held whole in memory."""
    return sample_of(len(data), lambda start, length: data[start : start + length])
