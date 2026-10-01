"""Routes for trusted-reference transcription accuracy metrics."""

from fastapi import APIRouter

from voice_eval.api.schemas import MetricsReason, MetricsRequest, MetricsResponse
from voice_eval.metrics import character_error_rate, word_error_rate

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.post("/wer")
async def calculate_wer(body: MetricsRequest) -> MetricsResponse:
    """Calculate WER/CER only when both required texts support an observation."""
    result = word_error_rate(body.trusted_reference, body.hypothesis)
    character_result = character_error_rate(body.trusted_reference, body.hypothesis)
    if result is None or character_result is None:
        if body.trusted_reference is None:
            reason: MetricsReason = "MISSING_REFERENCE"
        elif body.hypothesis is None:
            reason = "MISSING_HYPOTHESIS"
        else:
            reason = "EMPTY_REFERENCE"
        return MetricsResponse(status="UNKNOWN", reason=reason, wer=None, cer=None)
    return MetricsResponse(
        status="OBSERVED",
        reason="THRESHOLD_NOT_DEFINED",
        wer=result,
        cer=character_result,
    )
