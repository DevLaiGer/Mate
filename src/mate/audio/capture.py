"""Audio capture abstractions."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import numpy as np
import sounddevice as sd

from mate.config import AudioSettings
from mate.logging import get_logger


@dataclass(slots=True)
class AudioFrame:
    samples: np.ndarray
    channel: str


class AudioCapture:
    """Wraps sounddevice streams for mic and loopback capture."""

    def __init__(self, settings: AudioSettings) -> None:
        self.settings = settings
        self._queue: queue.Queue[AudioFrame] = queue.Queue(maxsize=8)
        self._lock = threading.RLock()
        self._running = False
        self._mic_stream: sd.InputStream | None = None
        self._speaker_stream: sd.InputStream | None = None
        self._callbacks: list[Callable[[AudioFrame], None]] = []
        self.logger = get_logger("audio-capture")
        self._active_mic_label = self._initial_label("input")
        self._active_speaker_label = self._initial_label("output")
        self._level_callbacks: list[Callable[[str, float], None]] = []
        self._last_sound_log: dict[str, float] = {"mic": 0.0, "speaker": 0.0}
        self._wasapi_capture = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        stream_kwargs: dict[str, Any] = {}
        if self.settings.mic_device is not None:
            stream_kwargs["device"] = self.settings.mic_device
        self.logger.debug(
            "Starting mic capture: device={} sample_rate={} block={}",
            stream_kwargs.get("device", "default"),
            self.settings.sample_rate,
            self.settings.block_size,
        )
        self._mic_stream = sd.InputStream(
            samplerate=self.settings.sample_rate,
            blocksize=self.settings.block_size,
            dtype="float32",
            channels=1,
            callback=self._handle_mic,
            **stream_kwargs,
        )
        self._mic_stream.start()
        self._active_mic_label = self._describe_stream_device(self._mic_stream, "input")
        self.logger.info("Mic stream started on {}", self._active_mic_label)
        self._start_speaker_stream()
        threading.Thread(target=self._pump_queue, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        if self._mic_stream is not None:
            with suppress(Exception):
                self._mic_stream.stop()
                self._mic_stream.close()
            self._mic_stream = None
        self.logger.info("Mic stream stopped")
        self._active_mic_label = f"{self._initial_label('input')} (stopped)"
        if self._speaker_stream is not None:
            with suppress(Exception):
                self._speaker_stream.stop()
                self._speaker_stream.close()
            self._speaker_stream = None
        if self._wasapi_capture is not None:
            with suppress(Exception):
                self._wasapi_capture.stop()
            self._wasapi_capture = None
        self.logger.info("Speaker stream stopped")
        self._active_speaker_label = f"{self._initial_label('output')} (stopped)"
        self.clear_level_callbacks()

    def register(self, callback: Callable[[AudioFrame], None]) -> None:
        self._callbacks.append(callback)

    def _handle_mic(self, indata, frames, time, status) -> None:  # type: ignore[override]
        if not self._running:
            return
        samples = np.copy(indata[:, 0])
        if not np.any(samples):
            self.logger.debug("Mic callback received silence frame")
        frame = AudioFrame(samples=samples, channel="mic")
        with suppress(queue.Full):
            self._queue.put_nowait(frame)
        self._emit_level("mic", samples)

    def _handle_wasapi_frame(self, samples: np.ndarray) -> None:
        """Handle audio frame from WASAPI loopback capture."""
        if not self._running:
            return
        frame = AudioFrame(samples=samples, channel="speaker")
        with suppress(queue.Full):
            self._queue.put_nowait(frame)
        self._emit_level("speaker", samples)

    def _handle_speaker(self, indata, frames, time, status) -> None:  # type: ignore[override]
        """Handle audio frame from sounddevice speaker stream."""
        if not self._running:
            return
        samples = np.copy(indata[:, 0])
        if not np.any(samples):
            self.logger.debug("Speaker callback received silence frame")
        frame = AudioFrame(samples=samples, channel="speaker")
        with suppress(queue.Full):
            self._queue.put_nowait(frame)
        self._emit_level("speaker", samples)

    def _pump_queue(self) -> None:
        while self._running:
            try:
                frame = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            for callback in list(self._callbacks):
                callback(frame)

    def describe_devices(self) -> dict[str, str]:
        return {
            "mic": self._active_mic_label,
            "speaker": self._active_speaker_label,
        }

    def register_level_callback(self, callback: Callable[[str, float], None]) -> None:
        self._level_callbacks.append(callback)

    def clear_level_callbacks(self) -> None:
        self._level_callbacks.clear()

    def _initial_label(self, kind: str) -> str:
        if kind == "input":
            return self.settings.mic_device or "System default mic"
        return self.settings.speaker_device or "Speaker loopback disabled"

    def _describe_stream_device(self, stream: sd.InputStream | None, kind: str) -> str:
        if stream is None:
            return self._initial_label(kind)
        try:
            device_spec = stream.device
            if isinstance(device_spec, tuple):
                device_spec = device_spec[0 if kind == "input" else 1]
            if device_spec is None:
                device_spec = sd.default.device[0 if kind == "input" else 1]
            if device_spec is None:
                return self._initial_label(kind)
            info = sd.query_devices(device_spec, kind)
            return info.get("name", self._initial_label(kind))
        except Exception as exc:  # pragma: no cover - hardware dependent
            self.logger.warning("Unable to resolve {} device: {}", kind, exc)
            return self._initial_label(kind)

    def _emit_level(self, channel: str, samples: np.ndarray) -> None:
        if not self._level_callbacks:
            return
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        for callback in list(self._level_callbacks):
            callback(channel, min(rms, 1.0))
        self._maybe_log_audio_event(channel, rms)

    def _start_speaker_stream(self) -> None:
        if self._speaker_stream is not None or self._wasapi_capture is not None:
            return
        
        # Try pure Python WASAPI loopback first (Windows only)
        try:
            from mate.audio.wasapi_loopback import WasapiLoopbackCapture
            
            self.logger.info("=== Attempting pure Python WASAPI loopback capture ===")
            # Pass target_rate but WASAPI will not resample to avoid distortion
            # Audio will be captured at native device sample rate
            self._wasapi_capture = WasapiLoopbackCapture(
                target_rate=self.settings.sample_rate,  # For reference only
                callback=self._handle_wasapi_frame,
            )
            self._wasapi_capture.start()
            actual_rate = self._wasapi_capture._sample_rate
            self._active_speaker_label = f"WASAPI Loopback ({actual_rate}Hz)"
            self.logger.info("✓ SUCCESS: Speaker loopback started via pure Python WASAPI at {}Hz", actual_rate)
            return
        except ImportError as exc:
            self.logger.warning("WASAPI loopback module not available: {}", exc)
        except Exception as exc:
            error_type = type(exc).__name__
            error_msg = str(exc)
            self.logger.error(
                "✗ FAILED: Pure Python WASAPI capture failed - {}: {}",
                error_type,
                error_msg,
            )
            self.logger.exception("Full WASAPI error traceback:")
            self._wasapi_capture = None
        
        # Fallback to sounddevice WASAPI
        wasapi_settings_cls = getattr(sd, "WasapiSettings", None)
        if wasapi_settings_cls is None:
            self.logger.warning("Speaker loopback requires WASAPI; skipping speaker capture")
            self._active_speaker_label = "WASAPI not available (Windows only)"
            return
        
        # DIAGNOSTIC: Log system capabilities
        self.logger.info("=== SPEAKER LOOPBACK DIAGNOSTICS ===")
        try:
            default_host_api_idx = sd.default.hostapi
            if isinstance(default_host_api_idx, (list, tuple)):
                default_host_api_idx = default_host_api_idx[0]
            default_host_api = sd.query_hostapis(default_host_api_idx)
            wasapi_name = default_host_api.get("name", "")
            self.logger.info("Default host API: {}", wasapi_name)
            
            # Handle both tuple and int device formats
            default_device = sd.default.device
            if isinstance(default_device, (list, tuple)) and len(default_device) > 1:
                default_output_idx = default_device[1]
            elif isinstance(default_device, int):
                # Single device index - try to find output devices
                default_output_idx = None
            else:
                default_output_idx = None
            
            if default_output_idx is not None:
                default_output = sd.query_devices(default_output_idx)
                self.logger.info("Default output device: {}", default_output.get("name", "Unknown"))
        except Exception as exc:
            self.logger.warning("Could not query default devices: {}", exc)
        
        # First, find WASAPI loopback devices
        loopback_device = None
        try:
            devices = sd.query_devices(kind="input")
            default_host_api = sd.query_hostapis(sd.default.hostapi[0])
            wasapi_name = default_host_api.get("name", "").lower()
            
            self.logger.info("Scanning {} input devices for WASAPI loopback...", len(devices))
            wasapi_input_devices = []
            
            # Look for WASAPI loopback devices
            for idx, dev in enumerate(devices):
                dev_host_api = sd.query_hostapis(dev.get("hostapi", 0))
                if wasapi_name in dev_host_api.get("name", "").lower():
                    dev_name = dev.get("name", "Unknown")
                    wasapi_input_devices.append((idx, dev_name))
                    name_lower = dev_name.lower()
                    # WASAPI loopback devices often contain these keywords
                    loopback_keywords = ["loopback", "stereo mix", "what u hear"]
                    if any(keyword in name_lower for keyword in loopback_keywords):
                        loopback_device = idx
                        self.logger.info(
                            "✓ Found WASAPI loopback device: {} (index {})",
                            dev_name,
                            idx,
                        )
                        break
            
            # Log all WASAPI input devices for diagnostics
            if wasapi_input_devices:
                self.logger.info("WASAPI input devices found:")
                for idx, name in wasapi_input_devices:
                    self.logger.info("  [{}] {}", idx, name)
            else:
                self.logger.warning("No WASAPI input devices found!")
            
            # If no explicit loopback device found, try to find default output's loopback
            if loopback_device is None:
                try:
                    # Get default output device
                    default_output_idx = sd.default.device[1]  # output device index
                    if default_output_idx is not None:
                        default_output = sd.query_devices(default_output_idx)
                        if default_output:
                            # WASAPI loopback devices are typically input devices
                            # that mirror outputs. Try to find a device that matches.
                            output_name = default_output.get("name", "").lower()
                            for idx, dev in enumerate(devices):
                                dev_host_api = sd.query_hostapis(dev.get("hostapi", 0))
                                if wasapi_name in dev_host_api.get("name", "").lower():
                                    # Some systems expose loopback as input with similar name
                                    if output_name in dev.get("name", "").lower():
                                        loopback_device = idx
                                        dev_name = dev.get("name")
                                        self.logger.info(
                                            "Using output-matching device as loopback: {}",
                                            dev_name,
                                        )
                                        break
                except Exception:
                    pass
        except Exception as exc:
            self.logger.debug("Could not query devices for loopback: {}", exc)
        
        # Check if WasapiSettings supports loopback parameter
        supports_loopback = False
        try:
            # Try to create WasapiSettings with loopback to check if it's supported
            wasapi_settings_cls(loopback=True)
            supports_loopback = True
            self.logger.info("WasapiSettings supports 'loopback' parameter")
        except (TypeError, AttributeError):
            self.logger.info(
                "WasapiSettings does NOT support 'loopback' parameter - "
                "using alternative method"
            )
        
        # Try different approaches to create WASAPI loopback stream
        attempts = []
        
        # Method 1: If loopback parameter is supported, use it
        if supports_loopback:
            if loopback_device is not None:
                attempts.append(
                    (
                        "loopback=True with device",
                        lambda: wasapi_settings_cls(loopback=True),
                        loopback_device,
                    )
                )
            attempts.append(
                (
                    "loopback=True (auto device)",
                    lambda: wasapi_settings_cls(loopback=True),
                    None,
                )
            )
            attempts.append(
                (
                    "exclusive=False, loopback=True",
                    lambda: wasapi_settings_cls(exclusive=False, loopback=True),
                    None,
                )
            )
        
        # Method 2: Try using output devices as input (WASAPI loopback approach)
        try:
            output_devices = sd.query_devices(kind="output")
            default_host_api_idx = sd.default.hostapi
            if isinstance(default_host_api_idx, (list, tuple)):
                default_host_api_idx = default_host_api_idx[0]
            default_host_api = sd.query_hostapis(default_host_api_idx)
            wasapi_name = default_host_api.get("name", "").lower()
            
            for idx, dev in enumerate(output_devices):
                dev_host_api = sd.query_hostapis(dev.get("hostapi", 0))
                if wasapi_name in dev_host_api.get("name", "").lower():
                    # Try using this output device as an input device (loopback)
                    # Use default parameter to capture idx safely
                    def make_settings(device_idx=idx):
                        return wasapi_settings_cls()
                    
                    attempts.append(
                        (
                            f"output device {idx} as input (loopback)",
                            make_settings,
                            idx,  # Use output device index
                        )
                    )
                    break  # Just try the first WASAPI output device
        except Exception as exc:
            self.logger.debug("Could not query output devices for loopback: {}", exc)
        
        # Method 3: Try default WasapiSettings with found loopback device
        if loopback_device is not None:
            attempts.append(
                (
                    "default WasapiSettings with loopback device",
                    lambda: wasapi_settings_cls(),
                    loopback_device,
                )
            )
        
        # Last resort: try without loopback parameter
        attempts.append(("default WasapiSettings", lambda: wasapi_settings_cls(), None))
        
        for attempt_name, extra_settings_fn, device_idx in attempts:
            try:
                extra = extra_settings_fn()
                speaker_kwargs: dict[str, Any] = {
                    "samplerate": self.settings.sample_rate,
                    "blocksize": self.settings.block_size,
                    "dtype": "float32",
                    "channels": 1,
                    "callback": self._handle_speaker,
                    "extra_settings": extra,
                }
                
                # Use specified device, found loopback device, or None (auto-detect)
                if self.settings.speaker_device is not None:
                    speaker_kwargs["device"] = self.settings.speaker_device
                elif device_idx is not None:
                    speaker_kwargs["device"] = device_idx
                # else: let PortAudio auto-select
                
                device_str = speaker_kwargs.get("device", "auto")
                self.logger.info(
                    "Attempting speaker loopback with {}: device={}",
                    attempt_name,
                    device_str,
                )
                
                self._speaker_stream = sd.InputStream(**speaker_kwargs)
                self._speaker_stream.start()
                self._active_speaker_label = self._describe_stream_device(
                    self._speaker_stream, "output"
                )
                self.logger.info(
                    "✓ SUCCESS: Speaker loopback started on {} (method: {})",
                    self._active_speaker_label,
                    attempt_name,
                )
                return  # Success!
            except Exception as exc:
                error_type = type(exc).__name__
                error_msg = str(exc)
                self.logger.warning(
                    "✗ FAILED {}: {} - {}",
                    attempt_name,
                    error_type,
                    error_msg,
                )
                if self._speaker_stream is not None:
                    try:
                        self._speaker_stream.stop()
                        self._speaker_stream.close()
                    except Exception:
                        pass
                    self._speaker_stream = None
                continue
        
        # All attempts failed - try brute force: test all WASAPI input devices
        try:
            devices = sd.query_devices(kind="input")
            default_host_api_idx = sd.default.hostapi
            if isinstance(default_host_api_idx, (list, tuple)):
                default_host_api_idx = default_host_api_idx[0]
            default_host_api = sd.query_hostapis(default_host_api_idx)
            wasapi_name = default_host_api.get("name", "").lower()
            
            # Use loopback parameter only if supported
            if supports_loopback:
                extra = wasapi_settings_cls(loopback=True)
            else:
                extra = wasapi_settings_cls()
            for idx, dev in enumerate(devices):
                dev_host_api = sd.query_hostapis(dev.get("hostapi", 0))
                if wasapi_name not in dev_host_api.get("name", "").lower():
                    continue
                
                try:
                    dev_name = dev.get("name", "Unknown")
                    self.logger.info("Testing device [{}] for loopback: {}", idx, dev_name)
                    self._speaker_stream = sd.InputStream(
                        device=idx,
                        samplerate=self.settings.sample_rate,
                        blocksize=self.settings.block_size,
                        dtype="float32",
                        channels=1,
                        callback=self._handle_speaker,
                        extra_settings=extra,
                    )
                    self._speaker_stream.start()
                    self._active_speaker_label = self._describe_stream_device(
                        self._speaker_stream, "output"
                    )
                    self.logger.info(
                        "✓ SUCCESS: Speaker loopback started on device [{}]: {}",
                        idx,
                        self._active_speaker_label,
                    )
                    return  # Success!
                except Exception as exc:
                    error_type = type(exc).__name__
                    error_msg = str(exc)
                    self.logger.warning(
                        "✗ Device [{}] failed: {} - {}",
                        idx,
                        error_type,
                        error_msg,
                    )
                    if self._speaker_stream is not None:
                        try:
                            self._speaker_stream.stop()
                            self._speaker_stream.close()
                        except Exception:
                            pass
                        self._speaker_stream = None
                    continue
        except Exception as exc:
            self.logger.debug("Brute force device scan failed: {}", exc)
            if self._speaker_stream is not None:
                try:
                    self._speaker_stream.stop()
                    self._speaker_stream.close()
                except Exception:
                    pass
                self._speaker_stream = None
        
        # All attempts failed - provide diagnostic summary
        self.logger.error("=== LOOPBACK FAILED - DIAGNOSTIC SUMMARY ===")
        self.logger.error("All loopback attempts failed")
        self.logger.error("This is likely a SYSTEM LIMITATION, not a program bug.")
        self.logger.error("")
        self.logger.error("POSSIBLE CAUSES:")
        self.logger.error("1. Windows doesn't expose loopback devices by default")
        self.logger.error("2. 'Stereo Mix' is disabled in Windows Sound settings")
        self.logger.error("3. No virtual audio cable installed (e.g., VB-Audio Virtual Cable)")
        self.logger.error("")
        self.logger.error("SOLUTIONS:")
        self.logger.error("Option A: Enable 'Stereo Mix'")
        self.logger.error("  - Right-click speaker icon → Sound settings")
        self.logger.error("  - Sound Control Panel → Recording tab")
        self.logger.error("  - Right-click empty space → Show Disabled Devices")
        self.logger.error("  - Enable 'Stereo Mix'")
        self.logger.error("")
        self.logger.error("Option B: Install VB-Audio Virtual Cable")
        self.logger.error("  - Download from: https://vb-audio.com/Cable/")
        self.logger.error("  - Set it as default playback device")
        self.logger.error("")
        self.logger.error("=== END DIAGNOSTICS ===")
        
        error_msg = (
            "Loopback unavailable - enable 'Stereo Mix' in Windows Sound settings "
            "(Recording tab → Show disabled devices) or install VB-Audio Virtual Cable"
        )
        self.logger.warning("Unable to start speaker loopback: {}", error_msg)
        self._active_speaker_label = error_msg
        self._speaker_stream = None

    def _maybe_log_audio_event(self, channel: str, rms: float) -> None:
        threshold = 0.01
        min_interval = 0.5
        now = time.monotonic()
        last = self._last_sound_log.get(channel, 0.0)
        if rms >= threshold and (now - last) >= min_interval:
            self.logger.info("{} audio detected (rms={:.3f})", channel, rms)
            self._last_sound_log[channel] = now
