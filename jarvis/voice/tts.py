"""
Text-to-speech via ElevenLabs.

Converts text to speech using the ElevenLabs streaming API and pipes it
to the server. Uses the ``eleven_flash_v2_5`` model by default for low
latency (~75ms).

Failures raise :class:`TTSError` with a short, human-readable reason
(derived from the ElevenLabs API error body) so the dashboard can show
exactly why the voice reply is unavailable instead of a stack trace.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from jarvis import config

log = logging.getLogger(__name__)


class TTSError(Exception):
    """Raised when text-to-speech fails. Message is safe to show to users."""


def _explain_error(exc: Exception) -> str:
    """Turn an ElevenLabs SDK exception into a short, actionable reason."""
    body = getattr(exc, "body", None)
    detail = body.get("detail", {}) if isinstance(body, dict) else {}
    status = getattr(exc, "status_code", None)

    if status == 401 or detail.get("status") == "missing_permissions":
        msg = detail.get("message", "")
        if "missing the permission" in msg:
            perm = msg.split("missing the permission", 1)[1].strip()
            perm = perm.replace(" to execute this operation.", "").strip(" .'")
            return (
                f"Your ElevenLabs API key lacks the '{perm}' permission. "
                "Edit the key at elevenlabs.io -> API Keys and enable it."
            )
        return (
            "ElevenLabs rejected the API key (401). Check ELEVENLABS_API_KEY "
            "in your .env file and its permissions at elevenlabs.io."
        )

    if status == 404:
        return (
            f"ElevenLabs voice not found (voice_id '{config.ELEVENLABS_VOICE_ID[:8]}...'). "
            "Check ELEVENLABS_VOICE_ID — it must belong to the key's account."
        )

    if status == 422 and detail.get("status") == "detected_unusual_activity":
        return "ElevenLabs blocked the request (unusual activity / free-tier restriction)."

    if status == 429:
        return "ElevenLabs quota exceeded (rate limit or character limit reached)."

    # Try to pull the real 'message' field out of the API error body before
    # falling back to a raw dump (which often leads with useless headers).
    import re
    text = str(exc).strip()
    m = re.search(r"[\"']message[\"']\s*:\s*[\"']([^\"']+)[\"']", text)
    if m:
        return f"TTS failed: {m.group(1)}"

    # Last resort: first meaningful line of the exception text.
    line = text.splitlines()[0][:200]
    return f"TTS failed: {line}"


async def stream_audio_bytes(text: str) -> AsyncGenerator[bytes, None]:
    """
    Stream audio bytes from ElevenLabs.

    Args:
        text: The text to synthesize.

    Yields:
        Chunks of audio bytes as they are generated.

    Raises:
        TTSError: With a user-safe reason if synthesis fails.
    """
    if not text or not text.strip():
        return

    if not config.ELEVENLABS_API_KEY:
        raise TTSError("ElevenLabs API key not set. Add ELEVENLABS_API_KEY to your .env file.")

    if not config.TTS_ENABLED:
        return

    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        raise TTSError("elevenlabs SDK not installed. Run: pip install elevenlabs")

    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

    try:
        audio_stream = client.text_to_speech.convert(
            text=text,
            voice_id=config.ELEVENLABS_VOICE_ID,
            model_id=config.ELEVENLABS_MODEL,
            output_format="pcm_16000",  # raw PCM for low-latency streaming
        )

        for chunk in audio_stream:
            if chunk:
                yield chunk

    except Exception as exc:
        reason = _explain_error(exc)
        log.warning("TTS streaming failed: %s", reason)
        raise TTSError(reason) from exc


def tts_disabled_reason() -> str | None:
    """Return None when TTS can run, otherwise a short reason it cannot."""
    if not config.ELEVENLABS_API_KEY:
        return "ElevenLabs API key not set in .env"
    if not config.TTS_ENABLED:
        return "TTS disabled (JARVIS_TTS=false)"
    try:
        import elevenlabs  # noqa: F401
    except ImportError:
        return "elevenlabs SDK not installed"
    return None


def is_tts_available() -> bool:
    """Check if TTS is configured and the SDK is installed."""
    return tts_disabled_reason() is None
