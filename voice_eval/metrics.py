"""Trusted-reference WER and CER operations with declared normalization."""

from __future__ import annotations

import unicodedata

import jiwer

from voice_eval.domain import CharacterErrorRate, WordErrorRate


def normalize_string(text: str) -> str:
    """Apply Unicode NFC, lowercase, punctuation removal, and whitespace collapse."""
    normalized = unicodedata.normalize("NFC", text).lower()
    cleaned = "".join(
        character
        if character.isalnum()
        or character.isspace()
        or unicodedata.category(character).startswith("M")
        else " "
        for character in normalized
    )
    return " ".join(cleaned.split())


def normalize_text(text: str) -> list[str]:
    """Return normalized whitespace-delimited units used as the WER denominator."""
    return normalize_string(text).split()


def word_error_rate(reference: str | None, hypothesis: str | None) -> WordErrorRate | None:
    """Calculate WER counts, returning ``None`` without a non-empty reference."""
    if reference is None or hypothesis is None:
        return None
    expected = normalize_text(reference)
    if not expected:
        return None
    result = jiwer.process_words(normalize_string(reference), normalize_string(hypothesis))
    return WordErrorRate(
        value=result.wer,
        substitutions=result.substitutions,
        deletions=result.deletions,
        insertions=result.insertions,
        reference_units=len(expected),
        normalization_version="unicode-nfc-lower-whitespace-v1",
    )


def character_error_rate(
    reference: str | None, hypothesis: str | None
) -> CharacterErrorRate | None:
    """Calculate Unicode code-point CER, or ``None`` without a usable reference."""
    if reference is None or hypothesis is None:
        return None
    expected = list(normalize_string(reference))
    if not expected:
        return None
    result = jiwer.process_characters(normalize_string(reference), normalize_string(hypothesis))
    return CharacterErrorRate(
        value=result.cer,
        substitutions=result.substitutions,
        deletions=result.deletions,
        insertions=result.insertions,
        reference_units=len(expected),
        normalization_version="unicode-nfc-lower-whitespace-v1",
    )
