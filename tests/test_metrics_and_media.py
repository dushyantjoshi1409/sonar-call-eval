from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from voice_eval.domain import Segment
from voice_eval.media import MediaError, MediaValidator
from voice_eval.metrics import character_error_rate, word_error_rate


def test_wer_boundaries_and_missing_reference() -> None:
    result = word_error_rate("order nahi mila", "order mila")
    assert result is not None
    assert result.substitutions == 0
    assert result.deletions == 1
    assert result.insertions == 0
    assert result.reference_units == 3
    assert result.value == pytest.approx(1 / 3)
    assert word_error_rate(None, "anything") is None
    assert word_error_rate("", "anything") is None
    insertion = word_error_rate("order mila", "order abhi mila")
    assert insertion is not None
    assert insertion.insertions == 1
    assert insertion.value == pytest.approx(0.5)
    characters = character_error_rate("नहीं", "नही")
    assert characters is not None
    assert characters.deletions == 1
    assert characters.reference_units == 4


def test_media_size_and_signature_limits(tmp_path: Path, wav_bytes: bytes) -> None:
    validator = MediaValidator(ffprobe_path="internal-wave", max_bytes=len(wav_bytes))
    path = tmp_path / "ok.wav"
    path.write_bytes(wav_bytes)
    metadata = validator.validate(path, "ok.wav")
    assert metadata.duration_seconds == pytest.approx(8.0)

    oversized = tmp_path / "large.wav"
    oversized.write_bytes(wav_bytes + b"x")
    with pytest.raises(MediaError, match="100 MiB|size"):
        validator.validate(oversized, "large.wav")

    bad = tmp_path / "fake.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(MediaError, match="signature|probe"):
        validator.validate(bad, "../../fake.mp3")


def test_segments_reject_non_finite_timestamps() -> None:
    with pytest.raises(ValidationError):
        Segment(id="bad", speaker="agent", start=float("nan"), end=1, text="hello")
    with pytest.raises(ValidationError):
        Segment(id="bad", speaker="agent", start=0, end=float("inf"), text="hello")
