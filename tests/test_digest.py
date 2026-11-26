"""The digest and the sample as definitions: what every client must compute the same way."""

import base64
import hashlib
import os

import pytest

from arkitekt_datalayer import digest

MiB = digest.MiB


def s3_composite(parts: list[bytes]) -> str:
    """The ``ChecksumSHA256`` S3 reports for a multipart upload of ``parts`` with SHA-256 checksums."""
    inner = b"".join(hashlib.sha256(part).digest() for part in parts)
    return base64.b64encode(hashlib.sha256(inner).digest()).decode() + f"-{len(parts)}"


def test_the_part_size_starts_at_the_floor_and_doubles_to_fit_the_part_ceiling() -> (
    None
):
    floor = digest.PART_FLOOR
    assert digest.part_size_for(0) == floor
    assert digest.part_size_for(floor * digest.MAX_PARTS) == floor
    assert digest.part_size_for(floor * digest.MAX_PARTS + 1) == 2 * floor
    five_tib = 5 * 1024**4
    assert -(-five_tib // digest.part_size_for(five_tib)) <= digest.MAX_PARTS


def test_an_empty_object_has_one_part() -> None:
    assert digest.part_count(0) == 1
    assert digest.composite_of_bytes(b"") == digest.composite_of(
        [hashlib.sha256(b"").digest()]
    )


def test_streaming_in_any_chunks_gives_the_digest_of_the_whole() -> None:
    data = os.urandom(2 * digest.PART_FLOOR + 12345)
    whole = digest.composite_of_bytes(data)
    hasher = digest.CompositeHasher(len(data))
    for start in range(0, len(data), 3 * MiB + 7):
        hasher.update(data[start : start + 3 * MiB + 7])
    assert hasher.hexdigest() == whole


def test_a_stream_of_the_wrong_length_refuses_to_name_a_digest() -> None:
    hasher = digest.CompositeHasher(10)
    hasher.update(b"short")
    with pytest.raises(ValueError, match="not the 10"):
        hasher.hexdigest()


def test_the_store_composite_of_the_advertised_parts_is_the_digest() -> None:
    data = os.urandom(2 * digest.PART_FLOOR + 1000)
    part = digest.part_size_for(len(data))
    parts = [data[i : i + part] for i in range(0, len(data), part)]
    assert len(parts) == 3
    assert digest.digest_from_checksum(
        s3_composite(parts), len(data)
    ) == digest.composite_of_bytes(data)


def test_a_composite_of_other_parts_is_not_taken_for_the_digest() -> None:
    data = os.urandom(2 * digest.PART_FLOOR + 1000)
    five = 5 * MiB
    parts = [data[i : i + five] for i in range(0, len(data), five)]
    assert digest.digest_from_checksum(s3_composite(parts), len(data)) is None


def test_a_single_request_checksum_is_the_digest_of_an_object_of_one_part() -> None:
    data = os.urandom(1000)
    plain = base64.b64encode(hashlib.sha256(data).digest()).decode()
    assert digest.digest_from_checksum(plain, len(data)) == digest.composite_of_bytes(
        data
    )
    # The same object uploaded as a one-part multipart says the same.
    assert digest.digest_from_checksum(
        s3_composite([data]), len(data)
    ) == digest.composite_of_bytes(data)


def test_a_single_request_checksum_of_an_object_of_many_parts_says_nothing() -> None:
    size = digest.PART_FLOOR + 1
    plain = base64.b64encode(hashlib.sha256(b"x").digest()).decode()
    assert digest.digest_from_checksum(plain, size) is None


@pytest.mark.parametrize("checksum", [None, "", "not base64!", "AAAA", "AAAA-x"])
def test_a_missing_or_malformed_checksum_says_nothing(checksum: str | None) -> None:
    assert digest.digest_from_checksum(checksum, 10) is None


def test_the_sample_reads_three_windows_of_a_large_object() -> None:
    window = digest.SAMPLE_WINDOW
    size = 10 * window + 3
    ranges = digest.sample_ranges(size)
    assert ranges == [
        (0, window),
        ((size - window) // 2, window),
        (size - window, window),
    ]


def test_the_sample_is_the_size_then_the_windows() -> None:
    data = os.urandom(3 * digest.SAMPLE_WINDOW + 17)
    expected = hashlib.sha256(f"{len(data)}\n".encode())
    for start, length in digest.sample_ranges(len(data)):
        expected.update(data[start : start + length])
    assert digest.sample_of_bytes(data) == expected.hexdigest()


def test_a_small_object_is_sampled_whole() -> None:
    data = b"hello"
    assert digest.sample_of_bytes(data) == hashlib.sha256(b"5\nhello").hexdigest()
    assert digest.sample_of_bytes(b"") == hashlib.sha256(b"0\n").hexdigest()


def test_files_that_differ_outside_the_windows_share_a_sample_but_not_a_digest() -> (
    None
):
    data = bytearray(os.urandom(5 * digest.SAMPLE_WINDOW))
    other = bytearray(data)
    other[digest.SAMPLE_WINDOW + 10] ^= 0xFF
    assert digest.sample_of_bytes(bytes(data)) == digest.sample_of_bytes(bytes(other))
    assert digest.composite_of_bytes(bytes(data)) != digest.composite_of_bytes(
        bytes(other)
    )
