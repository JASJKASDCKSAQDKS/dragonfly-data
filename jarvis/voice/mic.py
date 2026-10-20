"""
Microphone capture with push-to-talk support.

Uses ``sounddevice`` in callback mode for audio recording.

Two PTT modes are supported:

1. **Background PTT** (requires ``pynput``): Hold a key (default: Right Ctrl)
   to record. This runs a keyboard listener in a background thread.

2. **Command PTT** (always available): Type ``/s`` or ``/ptt`` in the REPL
   to start recording, then press Enter to stop.

If ``pynput`` cannot be imported (e.g. missing ``build-essential``), the
system gracefully falls back to command PTT mode.

Flow:
    1. User triggers recording (PTT key or /s command).
    2. Audio is captured via sounddevice callback.
    3. User stops recording (release key or press Enter).
    4. Raw WAV bytes are returned to the caller.
"""

from __future__ import annotations

import asyncio
import io
import logging
import sys
import threading
import wave
from typing import Callable

import numpy as np

from jarvis import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Check if pynput is available
# ---------------------------------------------------------------------------

_PYNPUT_AVAILABLE = False
try:
    from pynput.keyboard import Key, Listener as KeyboardListener
    _PYNPUT_AVAILABLE = True
except ImportError:
    log.info("pynput not available — using command-based PTT only")


# ---------------------------------------------------------------------------
# PTT key mapping (only used if pynput is available)
# ---------------------------------------------------------------------------

def _resolve_ptt_key():
    """Return the pynput Key object for the configured PTT key."""
    if not _PYNPUT_AVAILABLE:
        return None

    key_map = {
        "ctrl_r": Key.ctrl_r,
        "ctrl_l": Key.ctrl_l,
        "alt_r": Key.alt_r,
        "alt_l": Key.alt_l,
        "shift_r": Key.shift_r,
        "f5": Key.f5,
        "f6": Key.f6,
        "f7": Key.f7,
        "f8": Key.f8,
        "caps_lock": Key.caps_lock,
    }
    key_name = config.PTT_KEY.lower().strip()
    return key_map.get(key_name, Key.ctrl_r)


# ---------------------------------------------------------------------------
# Recording state
# ---------------------------------------------------------------------------

class _RecordingState:
    """Thread-safe state shared between the keyboard listener and the
    asyncio event loop."""

    def __init__(self) -> None:
        self.is_recording = False
        self.frames: list[np.ndarray] = []
        self.lock = threading.Lock()
        self._start_event: asyncio.Event | None = None
        self._stop_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._start_event = asyncio.Event()
        self._stop_event = asyncio.Event()

    def signal_start(self) -> None:
        with self.lock:
            if self.is_recording:
                return
            self.is_recording = True
            self.frames.clear()
        if self._loop and self._start_event:
            self._loop.call_soon_threadsafe(self._start_event.set)

    def signal_stop(self) -> None:
        with self.lock:
            if not self.is_recording:
                return
            self.is_recording = False
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def add_frame(self, data: np.ndarray) -> None:
        with self.lock:
            if self.is_recording:
                self.frames.append(data.copy())

    def get_audio(self) -> bytes:
        """Return the recorded audio as WAV bytes."""
        with self.lock:
            if not self.frames:
                return b""
            audio = np.concatenate(self.frames, axis=0)

        # Convert float32 [-1.0, 1.0] to int16 PCM.
        pcm = (audio * 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(config.AUDIO_CHANNELS)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(config.AUDIO_SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    async def wait_for_start(self) -> None:
        if self._start_event:
            self._start_event.clear()
            await self._start_event.wait()

    async def wait_for_stop(self) -> None:
        if self._stop_event:
            self._stop_event.clear()
            await self._stop_event.wait()


# Global recording state
_state = _RecordingState()


# ---------------------------------------------------------------------------
# Background keyboard listener (requires pynput)
# ---------------------------------------------------------------------------

_listener_started = False
_listener = None


def start_keyboard_listener() -> bool:
    """Start the global PTT keyboard listener (idempotent).

    Returns True if the listener was started, False if pynput is unavailable.
    """
    global _listener_started, _listener

    if not _PYNPUT_AVAILABLE:
        return False

    if _listener_started:
        return True

    ptt_key = _resolve_ptt_key()

    def on_press(key):
        if key == ptt_key:
            _state.signal_start()

    def on_release(key):
        if key == ptt_key:
            _state.signal_stop()

    _listener = KeyboardListener(on_press=on_press, on_release=on_release)
    _listener.daemon = True
    _listener.start()
    _listener_started = True
    log.info("PTT keyboard listener started (key: %s)", config.PTT_KEY)
    return True


def stop_keyboard_listener() -> None:
    """Stop the global PTT keyboard listener."""
    global _listener_started, _listener
    if _listener:
        _listener.stop()
        _listener = None
    _listener_started = False


# ---------------------------------------------------------------------------
# Command-based recording (always available, no pynput needed)
# ---------------------------------------------------------------------------

async def record_command(
    on_start: Callable[[], None] | None = None,
    on_stop: Callable[[], None] | None = None,
) -> bytes:
    """Record audio until the user presses Enter.

    This is the fallback PTT mode when pynput is not available.

    Args:
        on_start: Callback fired when recording starts.
        on_stop: Callback fired when recording stops.

    Returns:
        WAV-encoded audio bytes.
    """
    import sounddevice as sd

    if on_start:
        on_start()

    # Reset state.
    with _state.lock:
        _state.is_recording = True
        _state.frames.clear()

    stream = sd.InputStream(
        samplerate=config.AUDIO_SAMPLE_RATE,
        channels=config.AUDIO_CHANNELS,
        dtype="float32",
        blocksize=1024,
        callback=lambda indata, frames, time, status: _state.add_frame(indata),
    )
    stream.start()

    # Wait for the user to press Enter.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: input(""))

    # Stop recording.
    with _state.lock:
        _state.is_recording = False
    stream.stop()
    stream.close()

    if on_stop:
        on_stop()

    return _state.get_audio()


# ---------------------------------------------------------------------------
# Background PTT recording (requires pynput)
# ---------------------------------------------------------------------------

async def record_ptt(
    on_start: Callable[[], None] | None = None,
    on_stop: Callable[[], None] | None = None,
) -> bytes:
    """Wait for the user to press and release the PTT key, then return WAV audio.

    Falls back to ``record_command()`` if pynput is not available.

    Args:
        on_start: Callback fired when recording starts.
        on_stop: Callback fired when recording stops.

    Returns:
        WAV-encoded audio bytes.
    """
    if not _PYNPUT_AVAILABLE:
        return await record_command(on_start=on_start, on_stop=on_stop)

    import sounddevice as sd

    loop = asyncio.get_running_loop()
    _state.bind_loop(loop)

    # Ensure the keyboard listener is running.
    start_keyboard_listener()

    # Wait for the user to press the PTT key.
    await _state.wait_for_start()

    if on_start:
        on_start()

    # Start the audio stream.
    stream = sd.InputStream(
        samplerate=config.AUDIO_SAMPLE_RATE,
        channels=config.AUDIO_CHANNELS,
        dtype="float32",
        blocksize=1024,
        callback=lambda indata, frames, time, status: _state.add_frame(indata),
    )
    stream.start()

    # Record until the PTT key is released.
    await _state.wait_for_stop()

    stream.stop()
    stream.close()

    if on_stop:
        on_stop()

    return _state.get_audio()


# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------

def has_pynput() -> bool:
    """Return True if background PTT (pynput) is available."""
    return _PYNPUT_AVAILABLE


def is_mic_available() -> bool:
    """Check if microphone recording is possible (sounddevice + input device)."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default_in = sd.default.device[0]
        return default_in is not None and default_in >= 0
    except Exception:
        return False
