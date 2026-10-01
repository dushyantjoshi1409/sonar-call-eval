"""Bounded local audio signature, metadata, and full-decode validation."""

from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

from pydantic import BaseModel


class MediaError(ValueError):
    """Uploaded media failed a safe validation boundary."""

    pass


class MediaMetadata(BaseModel):
    """Validated metadata used by transcript timing and browser playback."""

    duration_seconds: float
    channels: int
    sample_rate: int
    codec: str
    size_bytes: int
    format_name: str


class MediaValidator:
    """Validate local WAV, MP3, or M4A bytes using bounded subprocess calls."""

    def __init__(
        self,
        ffprobe_path: str = "ffprobe",
        ffmpeg_path: str = "ffmpeg",
        max_bytes: int = 100 * 1024 * 1024,
        max_duration_seconds: float = 1_200,
    ) -> None:
        self.ffprobe_path = ffprobe_path
        self.ffmpeg_path = ffmpeg_path
        self.max_bytes = max_bytes
        self.max_duration_seconds = max_duration_seconds

    def validate(self, path: Path, original_name: str) -> MediaMetadata:
        """Return metadata or raise ``MediaError`` without invoking a shell."""
        size = path.stat().st_size
        if size == 0 or size > self.max_bytes:
            raise MediaError(f"audio size must be between 1 byte and {self.max_bytes} bytes")
        suffix = Path(original_name).suffix.lower()
        if suffix not in {".wav", ".mp3", ".m4a"}:
            raise MediaError("supported audio formats are WAV, MP3, and M4A")
        with path.open("rb") as source:
            header = source.read(16)
        if not self._signature_matches(suffix, header):
            raise MediaError("audio signature does not match the declared format")
        if self.ffprobe_path == "internal-wave":
            if suffix != ".wav":
                raise MediaError("internal test probe supports WAV only")
            return self._probe_wave(path, size)
        metadata = self._probe_ffmpeg(path, size)
        if metadata.duration_seconds <= 0 or metadata.duration_seconds > self.max_duration_seconds:
            raise MediaError(f"audio duration must be in (0, {self.max_duration_seconds}] seconds")
        if metadata.channels not in {1, 2}:
            raise MediaError("audio must have one or two channels")
        return metadata

    @staticmethod
    def _signature_matches(suffix: str, header: bytes) -> bool:
        if suffix == ".wav":
            return header.startswith(b"RIFF") and header[8:12] == b"WAVE"
        if suffix == ".mp3":
            return header.startswith(b"ID3") or (
                len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
            )
        return len(header) >= 12 and header[4:8] == b"ftyp"

    def _probe_wave(self, path: Path, size: int) -> MediaMetadata:
        try:
            with wave.open(str(path), "rb") as audio:
                frames = audio.getnframes()
                sample_rate = audio.getframerate()
                metadata = MediaMetadata(
                    duration_seconds=frames / sample_rate,
                    channels=audio.getnchannels(),
                    sample_rate=sample_rate,
                    codec="pcm",
                    size_bytes=size,
                    format_name="wav",
                )
        except (wave.Error, EOFError) as error:
            raise MediaError("audio probe failed") from error
        if metadata.duration_seconds > self.max_duration_seconds:
            raise MediaError(f"audio duration must be in (0, {self.max_duration_seconds}] seconds")
        if metadata.channels not in {1, 2}:
            raise MediaError("audio must have one or two channels")
        return metadata

    def _probe_ffmpeg(self, path: Path, size: int) -> MediaMetadata:
        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=codec_name,codec_type,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
            payload = json.loads(result.stdout)
            stream = next(item for item in payload["streams"] if item["codec_type"] == "audio")
            metadata = MediaMetadata(
                duration_seconds=float(payload["format"]["duration"]),
                channels=int(stream["channels"]),
                sample_rate=int(stream["sample_rate"]),
                codec=str(stream["codec_name"]),
                size_bytes=size,
                format_name=str(payload["format"]["format_name"]),
            )
            subprocess.run(
                [self.ffmpeg_path, "-v", "error", "-i", str(path), "-f", "null", "-"],
                capture_output=True,
                timeout=60,
                check=True,
            )
            return metadata
        except FileNotFoundError as error:
            raise MediaError("FFmpeg/ffprobe is required and was not found") from error
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            KeyError,
            StopIteration,
            TypeError,
            ValueError,
        ) as error:
            raise MediaError("audio probe or bounded decode failed") from error
