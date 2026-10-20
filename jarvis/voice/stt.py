"""
Speech-to-text via Deepgram.

Sends recorded audio (WAV bytes) to the Deepgram pre-recorded API
and returns the transcript.  Uses the ``nova-3`` model by default
for best accuracy.

This module only imports ``deepgram`` when called, so it won't
break the app if the SDK isn't installed or the key is missing.
"""

from __future__ import annotations

import asyncio
import logging

from jarvis import config

log = logging.getLogger(__name__)


class STTError(Exception):
    """Raised when speech-to-text fails."""


async def transcribe(audio_bytes: bytes) -> str:
    """Transcribe WAV audio bytes to text using Deepgram.

    Args:
        audio_bytes: WAV-encoded audio data.

    Returns:
        The transcribed text, or an empty string if nothing was detected.

    Raises:
        STTError: On configuration or API errors.
    """
    if not audio_bytes:
        return ""

    if not config.DEEPGRAM_API_KEY:
        raise STTError(
            "Deepgram API key not set. "
            "Add DEEPGRAM_API_KEY to your .env file."
        )

    try:
        from deepgram import DeepgramClient, PrerecordedOptions
    except ImportError:
        try:
            from deepgram import DeepgramClient
            # For some versions of the SDK, options are passed as a dict or a different object
            PrerecordedOptions = None
        except ImportError:
            raise STTError(
                "deepgram-sdk not installed. "
                "Run: pip install deepgram-sdk"
            )

    try:
        client = DeepgramClient(api_key=config.DEEPGRAM_API_KEY)

        log.debug("Sending %d bytes to Deepgram (%s)", len(audio_bytes), config.STT_MODEL)

        # The v3 SDK transcribe_file is synchronous — run it in an executor
        # so we don't block the event loop.
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.listen.v1.media.transcribe_file(
                request=audio_bytes,
                model=config.STT_MODEL,
                smart_format=True,
                language="en",
            ),
        )

        # Navigate the response structure.
        transcript = (
            response.results
            .channels[0]
            .alternatives[0]
            .transcript
        )

        log.debug("Deepgram transcript: %r", transcript)
        return transcript.strip() if transcript else ""

    except STTError:
        raise
    except Exception as exc:
        log.exception("Deepgram transcription failed")
        raise STTError(f"Transcription failed: {exc}")


def is_stt_available() -> bool:
    """Check if STT is configured and the SDK is installed."""
    if not config.DEEPGRAM_API_KEY:
        return False
    try:
        import deepgram  # noqa: F401
        return True
    except ImportError:
        return False
