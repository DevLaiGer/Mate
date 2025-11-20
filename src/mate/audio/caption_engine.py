"""Live caption engine built on faster-whisper (with placeholder fallback)."""

from __future__ import annotations

import random
import threading
import time
from ctypes import POINTER, cast

from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from mate.audio.capture import AudioCapture
from mate.audio.realtime_stt_processor import RealtimeSTTProcessor
from mate.config import CaptionSettings
from mate.core.events import EventBus
from mate.core.state import CaptionFrame
from mate.logging import get_logger

_PROMPTS = [
    "captions are coming soon",
    "listening for voices",
    "mate base engine ready",
]


class CaptionEngine:
    """Transforms audio frames into caption frames (Whisper or placeholder)."""

    def __init__(self, settings: CaptionSettings, capture: AudioCapture, events: EventBus) -> None:
        self.settings = settings
        self.capture = capture
        self.events = events
        self.logger = get_logger("caption-engine")
        self._running = False
        self._placeholder_thread: threading.Thread | None = None
        self._speaker_monitor_thread: threading.Thread | None = None
        self._speaker_monitor_stop: threading.Event | None = None
        self._speaker_endpoint: POINTER(IAudioEndpointVolume) | None = None
        self._stt_processor: RealtimeSTTProcessor | None = None
        self._using_stt = False

    def start(self) -> None:
        if self._running:
            return
        self.logger.info("Starting caption engine ({} mode)", self.settings.engine)
        self._running = True
        self.capture.clear_level_callbacks()
        self.capture.register_level_callback(self._handle_levels)
        
        if self.settings.engine == "whisper":
            self._using_stt = self._start_stt_processor()
            self.logger.debug("faster-whisper mode active: {}", self._using_stt)
            if not self._using_stt:
                self.logger.error(
                    "faster-whisper failed to start. No captions will be shown. "
                    "Please install: pip install faster-whisper"
                )
        elif self.settings.engine == "placeholder":
            # Only start placeholder thread if explicitly set to placeholder mode AND enabled
            if self.settings.show_placeholder_captions:
                self.logger.warning("Running in placeholder caption mode")
                self._start_placeholder_thread()
            else:
                self.logger.info("Placeholder captions disabled. No captions will be shown.")
        else:
            self.logger.warning("Unknown engine mode: {}", self.settings.engine)
        
        self._publish_device_info()
        self._start_speaker_monitor()

    def stop(self) -> None:
        if not self._running:
            return
        self.logger.info("Stopping caption engine")
        self._running = False
        
        if self._using_stt and self._stt_processor:
            self._stt_processor.stop()
        
        self.capture.clear_level_callbacks()
        self.logger.debug(
            "Caption engine stopped; placeholder thread={}",
            self._placeholder_thread is not None,
        )
        self._stop_speaker_monitor()
        self._using_stt = False
        self._stt_processor = None
        self._placeholder_thread = None
        self._publish_device_info()

    def _start_stt_processor(self) -> bool:
        """Start faster-whisper processor for mic and speaker transcription."""
        try:
            self._stt_processor = RealtimeSTTProcessor(
                self.settings,
                self.capture,
                self.events,
            )
            success = self._stt_processor.start()
            if success:
                self.logger.info("faster-whisper processor started - capturing mic and speaker audio")
            return success
        except Exception as exc:
            self.logger.exception("Failed to start faster-whisper processor: {}", exc)
            return False

    def _start_placeholder_thread(self) -> None:
        if self._placeholder_thread and self._placeholder_thread.is_alive():
            return
        self._placeholder_thread = threading.Thread(target=self._emit_placeholder, daemon=True)
        self._placeholder_thread.start()

    def _emit_placeholder(self) -> None:
        while self._running:
            text = random.choice(_PROMPTS)
            frame = CaptionFrame(text=text, speaker="mate", channel="mic", confidence=0.5)
            self.events.emit("caption.frame", frame)
            time.sleep(self.settings.mock_interval_ms / 1000)

    def _publish_device_info(self) -> None:
        info = self.capture.describe_devices()
        self.events.emit("audio.devices", info)

    def _handle_levels(self, channel: str, rms: float) -> None:
        self.events.emit("audio.level", {"channel": channel, "rms": rms})
        self.logger.debug("Level update: {} -> {:.3f}", channel, rms)

    def _start_speaker_monitor(self) -> None:
        if self._speaker_monitor_thread and self._speaker_monitor_thread.is_alive():
            return
        self._speaker_monitor_stop = threading.Event()
        self._speaker_monitor_thread = threading.Thread(
            target=self._speaker_monitor_loop, daemon=True
        )
        self._speaker_monitor_thread.start()

    def _stop_speaker_monitor(self) -> None:
        if self._speaker_monitor_stop is not None:
            self._speaker_monitor_stop.set()
            self._speaker_monitor_stop = None
        self._speaker_monitor_thread = None

    def _speaker_monitor_loop(self) -> None:
        endpoint = self._get_speaker_endpoint()
        if endpoint is None:
            return
        while self._speaker_monitor_stop and not self._speaker_monitor_stop.is_set():
            try:
                level = float(endpoint.GetMasterVolumeLevelScalar())
            except Exception:  # pragma: no cover - COM errors depend on host
                self.logger.warning("Unable to read speaker volume; stopping monitor")
                break
            self._handle_levels("speaker", level)
            time.sleep(0.2)
        self._speaker_monitor_thread = None

    def _get_speaker_endpoint(self) -> POINTER(IAudioEndpointVolume) | None:
        if self._speaker_endpoint is not None:
            return self._speaker_endpoint
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            self._speaker_endpoint = cast(interface, POINTER(IAudioEndpointVolume))
        except Exception as exc:  # pragma: no cover - COM errors depend on host
            self.logger.warning("Speaker endpoint unavailable: {}", exc)
            self._speaker_endpoint = None
        return self._speaker_endpoint
