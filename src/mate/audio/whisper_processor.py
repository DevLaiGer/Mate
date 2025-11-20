"""Whisper audio processor that handles both mic and speaker audio."""

from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from mate.audio.caption_manager import CaptionManager
from mate.audio.capture import AudioCapture, AudioFrame
from mate.audio.vad import VADDetector
from mate.config import CaptionSettings
from mate.core.events import EventBus
from mate.core.state import CaptionFrame
from mate.logging import get_logger


class WhisperProcessor:
    """Processes audio frames through whisper-cli with independent mic and speaker threads."""

    def __init__(
        self,
        settings: CaptionSettings,
        capture: AudioCapture,
        events: EventBus,
    ) -> None:
        self.settings = settings
        self.capture = capture
        self.events = events
        self.logger = get_logger("whisper-processor")
        self._running = False
        self._audio_buffer: dict[str, list[np.ndarray]] = {"mic": [], "speaker": []}
        self._buffer_locks: dict[str, threading.Lock] = {
            "mic": threading.Lock(),
            "speaker": threading.Lock(),
        }
        self._mic_thread: threading.Thread | None = None
        self._speaker_thread: threading.Thread | None = None
        self._whisper_exe: Path | None = None
        self._model_path: Path | None = None  # Medium model for Layer B/C
        self._model_path_fast: Path | None = None  # Tiny model for Layer A
        
        # Buffer size in seconds - configurable for real-time vs accuracy tradeoff
        self._buffer_duration = settings.realtime_latency
        self._sample_rate = capture.settings.sample_rate
        self._actual_sample_rates: dict[str, int] = {}  # Track actual sample rates per channel
        
        # Sliding window for continuous transcription with context
        self._sliding_window: dict[str, list[np.ndarray]] = {"mic": [], "speaker": []}
        self._window_max_duration = 10.0  # Keep up to 10 seconds of context
        self._last_full_text: dict[str, str] = {"mic": "", "speaker": ""}  # Track last complete transcription
        self._active_caption_id: dict[str, str | None] = {"mic": None, "speaker": None}
        
        # Sentence accumulation for real-time display
        self._sentence_buffer: dict[str, str] = {"mic": "", "speaker": ""}
        self._sentence_buffer_start_time: dict[str, float | None] = {"mic": None, "speaker": None}
        self._sentence_buffer_timeout = 10.0  # seconds (finalize if no updates for 10s)
        
        # Silence detection - require sustained silence before finalizing
        self._silence_counter: dict[str, int] = {"mic": 0, "speaker": 0}
        self._silence_threshold_count = 2  # Require 2 consecutive silence detections (~2.4 seconds)
        
        # Voice Activity Detection (VAD) for better speech/silence detection
        try:
            self._vad: dict[str, VADDetector] = {
                "mic": VADDetector(
                    sample_rate=16000,  # Will resample if needed
                    frame_duration_ms=30,
                    mode=2,  # Moderate aggressiveness
                    hangover_ms=300,  # 300ms hangover
                ),
                "speaker": VADDetector(
                    sample_rate=16000,
                    frame_duration_ms=30,
                    mode=2,
                    hangover_ms=300,
                ),
            }
            self._vad_enabled = True
            self.logger.info("✓ VAD enabled for improved speech detection")
        except Exception as e:
            self.logger.warning("VAD initialization failed: {}, falling back to RMS", e)
            self._vad_enabled = False
        
        # Three-Layer STT Architecture Configuration
        # Layer A: Quick partials for instant feedback (200-400ms)
        self._layer_a_interval = 0.3  # seconds
        self._layer_a_min_samples = int(self._sample_rate * 0.2)  # 200ms minimum
        self._layer_a_last_process: dict[str, float] = {"mic": 0.0, "speaker": 0.0}
        
        # Layer B: Sliding windows for better accuracy (2-3s window, 0.5s step)
        self._layer_b_window_duration = 2.5  # seconds
        self._layer_b_step = 0.5  # seconds
        self._layer_b_last_process: dict[str, float] = {"mic": 0.0, "speaker": 0.0}
        
        # Layer C: Final pass on utterance end (handled by VAD silence detection)
        # Uses existing _silence_counter and _sentence_buffer logic
        
        # Utterance tracking for Layer C
        self._utterance_start: dict[str, float | None] = {"mic": None, "speaker": None}
        self._utterance_buffer: dict[str, list[np.ndarray]] = {"mic": [], "speaker": []}
        
        # Track accumulated text per layer (for merging within same layer)
        # Each layer accumulates its own text, then higher layer replaces lower
        self._layer_a_accumulated: dict[str, str] = {"mic": "", "speaker": ""}  # Layer A text
        self._layer_b_accumulated: dict[str, str] = {"mic": "", "speaker": ""}  # Layer B text
        self._current_layer: dict[str, str] = {"mic": "", "speaker": ""}  # Current active layer
        
        # Caption timeline manager for smart replacement
        self._caption_manager = CaptionManager(max_history=100)
        
        self.logger.info(
            "Three-layer STT: Layer A={:.0f}ms, Layer B={:.1f}s/{:.1f}s step",
            self._layer_a_interval * 1000,
            self._layer_b_window_duration,
            self._layer_b_step,
        )
        
        self.logger.info(
            "Whisper processor configured with {:.1f}s latency (lower = faster, higher = more accurate)",
            self._buffer_duration,
        )
        
        # Setup recordings directory if enabled
        self._save_recordings = settings.save_recordings
        if self._save_recordings:
            self._recordings_dir = Path(settings.recordings_dir).expanduser()
            self._recordings_dir.mkdir(parents=True, exist_ok=True)
            self._max_recordings = settings.max_recordings
            self.logger.info("Recordings will be saved to: {}", self._recordings_dir)
            if self._max_recordings > 0:
                self.logger.info("Maximum recordings: {}", self._max_recordings)
        else:
            self._recordings_dir = None
            self.logger.info("Recording saving is disabled")

    def start(self) -> bool:
        """Start the whisper processor."""
        if self._running:
            return True

        # Find whisper-cli.exe
        whisper_exe = Path(self.settings.whisper_executable).expanduser()
        
        # Look for whisper-cli.exe
        if not whisper_exe.exists() or "cli" not in whisper_exe.name.lower():
            possible_paths = [
                whisper_exe.parent / "whisper-cli.exe",
                Path.cwd() / "whisper-blas-bin-x64" / "Release" / "whisper-cli.exe",
                Path.cwd() / "whisper-cli.exe",
            ]
            for path in possible_paths:
                if path.exists():
                    whisper_exe = path
                    break
            else:
                self.logger.error("whisper-cli.exe not found. Needed for file processing.")
                return False

        model_path = Path(self.settings.whisper_model_path).expanduser()
        if not model_path.exists():
            self.logger.error("Whisper model not found: {}", model_path)
            self.logger.error("Please download the model and place it in the models/ directory")
            return False
        
        # Check for fast model (tiny) for Layer A
        model_path_fast = Path(self.settings.whisper_model_path_fast).expanduser()
        if not model_path_fast.exists():
            self.logger.warning("Fast model not found: {}, Layer A will use medium model (slower)", model_path_fast)
            self.logger.warning("Download tiny model for faster Layer A: https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin")
            model_path_fast = model_path  # Fallback to medium model

        self._whisper_exe = whisper_exe
        self._model_path = model_path
        self._model_path_fast = model_path_fast
        self._running = True
        
        self.logger.info("✓ Whisper-cli: {}", whisper_exe)
        self.logger.info("✓ Model (Layer B/C): {} ({:.1f} MB)", model_path.name, model_path.stat().st_size / 1024 / 1024)
        if model_path_fast != model_path:
            self.logger.info("✓ Model (Layer A): {} ({:.1f} MB)", model_path_fast.name, model_path_fast.stat().st_size / 1024 / 1024)

        # Register audio callbacks
        self.capture.register(self._handle_audio_frame)
        self.capture.start()

        # Start separate processing threads for mic and speaker
        self._mic_thread = threading.Thread(
            target=self._process_loop,
            args=("mic", "Mic"),
            daemon=True,
        )
        self._speaker_thread = threading.Thread(
            target=self._process_loop,
            args=("speaker", "Speaker"),
            daemon=True,
        )
        
        self._mic_thread.start()
        self._speaker_thread.start()

        self.logger.info("Whisper processor started with independent mic and speaker threads")
        return True

    def stop(self) -> None:
        """Stop the whisper processor."""
        if not self._running:
            return

        self._running = False
        self.logger.info("Whisper processor stopped")

    def _handle_audio_frame(self, frame: AudioFrame) -> None:
        """Receive audio frames from capture."""
        if not self._running:
            return

        # Detect actual sample rate from frame (for WASAPI which doesn't resample)
        if frame.channel == "speaker" and frame.channel not in self._actual_sample_rates:
            # Try to get actual sample rate from WASAPI capture
            if hasattr(self.capture, '_wasapi_capture') and self.capture._wasapi_capture:
                wasapi_rate = self.capture._wasapi_capture._sample_rate
                if wasapi_rate > 0:
                    self._actual_sample_rates[frame.channel] = wasapi_rate
                    self.logger.info(
                        "Detected {} channel sample rate: {}Hz",
                        frame.channel,
                        wasapi_rate,
                    )

        # Use channel-specific lock to prevent blocking between channels
        with self._buffer_locks[frame.channel]:
            self._audio_buffer[frame.channel].append(frame.samples.copy())

    def _process_loop(self, channel: str, label: str) -> None:
        """
        Main processing loop for a specific channel - implements three-layer STT.
        
        Layer A: Quick partials every 300ms
        Layer B: Sliding windows every 500ms  
        Layer C: Final pass on silence detection
        """
        self.logger.info("Started three-layer processing thread for {}", label)
        last_buffer_trim = time.time()
        
        while self._running:
            current_time = time.time()
            
            # Layer A: Quick partials for instant feedback (every 300ms)
            time_since_layer_a = current_time - self._layer_a_last_process[channel]
            if time_since_layer_a >= self._layer_a_interval:
                self._process_layer_a(channel, label, current_time)
                self._layer_a_last_process[channel] = current_time
            
            # Layer B: Sliding windows for better accuracy (every 500ms)
            time_since_layer_b = current_time - self._layer_b_last_process[channel]
            if time_since_layer_b >= self._layer_b_step:
                self._process_layer_b(channel, label, current_time)
                self._layer_b_last_process[channel] = current_time
            
            # Trim old audio from buffer every 2 seconds to prevent memory growth
            if current_time - last_buffer_trim > 2.0:
                self._trim_audio_buffer(channel)
                last_buffer_trim = current_time
            
            # Layer C: Final pass handled by silence detection in Layer B
            
            # Sleep briefly to avoid busy-waiting
            time.sleep(0.05)  # 50ms for responsive layer timing
        
        self.logger.info("Stopped processing thread for {}", label)

    def _trim_audio_buffer(self, channel: str) -> None:
        """Trim old audio from buffer to prevent unbounded memory growth."""
        channel_sample_rate = self._actual_sample_rates.get(channel, self._sample_rate)
        
        with self._buffer_locks[channel]:
            if not self._audio_buffer[channel]:
                return
            
            # Keep only last 5 seconds of audio (enough for Layer B window)
            total_audio = np.concatenate(self._audio_buffer[channel])
            max_samples = int(channel_sample_rate * 5.0)
            
            if len(total_audio) > max_samples:
                # Trim to last 5 seconds
                trimmed = total_audio[-max_samples:]
                self._audio_buffer[channel] = [trimmed]
                self.logger.debug(
                    "Trimmed {} buffer: {:.1f}s -> {:.1f}s",
                    channel,
                    len(total_audio) / channel_sample_rate,
                    len(trimmed) / channel_sample_rate
                )

    def _detect_speech(self, audio_data: np.ndarray, channel: str, sample_rate: int) -> bool:
        """
        Detect if audio contains speech using VAD or RMS fallback.
        
        Args:
            audio_data: Audio buffer to analyze
            channel: Channel identifier ('mic' or 'speaker')
            sample_rate: Audio sample rate
            
        Returns:
            True if speech detected, False if silence
        """
        if self._vad_enabled and channel in self._vad:
            # Use VAD for accurate speech detection
            vad = self._vad[channel]
            
            # Resample to 16kHz if needed (VAD requires 16kHz)
            if sample_rate != 16000:
                # Simple downsampling/upsampling
                ratio = 16000 / sample_rate
                target_length = int(len(audio_data) * ratio)
                audio_resampled = np.interp(
                    np.linspace(0, len(audio_data), target_length),
                    np.arange(len(audio_data)),
                    audio_data
                )
            else:
                audio_resampled = audio_data
            
            # Process audio through VAD
            try:
                vad_results = vad.process_buffer(audio_resampled, start_timestamp=time.time())
                
                # Count speech frames
                speech_frames = sum(1 for r in vad_results if r.is_speech)
                total_frames = len(vad_results)
                
                if total_frames == 0:
                    return False
                
                # Require at least 30% of frames to be speech
                speech_ratio = speech_frames / total_frames
                is_speech = speech_ratio > 0.3
                
                self.logger.debug(
                    "VAD {} detection: {}/{} frames speech ({:.1f}%) -> {}",
                    channel,
                    speech_frames,
                    total_frames,
                    speech_ratio * 100,
                    "SPEECH" if is_speech else "SILENCE"
                )
                
                return is_speech
            
            except Exception as e:
                self.logger.warning("VAD processing error for {}: {}, falling back to RMS", channel, e)
                # Fall through to RMS method
        
        # Fallback to RMS-based detection
        rms = float(np.sqrt(np.mean(np.square(audio_data))))
        is_speech = rms >= 0.01
        
        self.logger.debug(
            "RMS {} detection: {:.4f} -> {}",
            channel,
            rms,
            "SPEECH" if is_speech else "SILENCE"
        )
        
        return is_speech

    def _process_layer_a(self, channel: str, label: str, current_time: float) -> None:
        """
        Layer A: Quick partials for instant feedback (200-400ms audio).
        Low confidence, immediate UX response.
        """
        channel_sample_rate = self._actual_sample_rates.get(channel, self._sample_rate)
        
        # Get recent audio without locking (quick check)
        with self._buffer_locks[channel]:
            if not self._audio_buffer[channel]:
                self.logger.debug("[Layer A] {} no audio in buffer", channel)
                return
            recent_audio = self._audio_buffer[channel].copy()
        
        if not recent_audio:
            return
        
        # Concatenate recent chunks
        audio_data = np.concatenate(recent_audio)
        
        # Need at least 200ms for Layer A
        if len(audio_data) < self._layer_a_min_samples:
            self.logger.debug(
                "[Layer A] {} audio too short: {:.2f}s < 0.2s",
                channel,
                len(audio_data) / channel_sample_rate
            )
            return
        
        # Take only last 400ms for quick processing
        max_samples = int(channel_sample_rate * 0.4)
        if len(audio_data) > max_samples:
            audio_data = audio_data[-max_samples:]
        
        self.logger.info(
            "[Layer A] {} processing {:.2f}s of audio...",
            channel,
            len(audio_data) / channel_sample_rate
        )
        
        # Check for speech
        if not self._detect_speech(audio_data, channel, channel_sample_rate):
            self.logger.debug("[Layer A] {} no speech detected", channel)
            return
        
        # Track utterance start and create caption ID
        if self._utterance_start[channel] is None:
            import uuid
            self._utterance_start[channel] = current_time
            self._utterance_buffer[channel] = []
            self._active_caption_id[channel] = str(uuid.uuid4())  # Same ID for whole utterance
        
        # Add to utterance buffer
        self._utterance_buffer[channel].append(audio_data)
        
        # Transcribe quickly
        start_time = self._utterance_start[channel] or current_time
        
        self.logger.info("[Layer A] {} starting transcription...", channel)
        text = self._quick_transcribe(audio_data, channel_sample_rate, channel)
        self.logger.info("[Layer A] {} transcription result: \"{}\"", channel, text if text else "(empty)")
        
        if text and text.strip():
            new_text = text.strip()
            
            # MERGE within Layer A: append new text to accumulated Layer A text
            if self._current_layer[channel] == "A":
                # Same layer - check if new text extends previous
                old_text = self._layer_a_accumulated[channel]
                if new_text.startswith(old_text[:min(20, len(old_text))]):
                    # Extension - use new text (it includes old + new)
                    self._layer_a_accumulated[channel] = new_text
                else:
                    # Different text - append
                    self._layer_a_accumulated[channel] = old_text + " " + new_text
            else:
                # Layer A firing while Layer B is active, OR first Layer A
                # Just accumulate Layer A's text, DON'T change current_layer if B is active
                self._layer_a_accumulated[channel] = new_text
                
                # Only set current_layer to "A" if no layer is active yet
                if self._current_layer[channel] == "":
                    self._current_layer[channel] = "A"
                # If Layer B is active, keep it as "B" - don't switch back!
            
            # Build display text based on current active layer
            if self._current_layer[channel] == "B":
                # Layer B is active - show B (confirmed) + A (new)
                display_text = self._layer_b_accumulated[channel]
                # Append Layer A's new text that goes beyond Layer B
                if self._layer_a_accumulated[channel]:
                    # Check if Layer A has text beyond Layer B
                    if len(self._layer_a_accumulated[channel]) > len(display_text):
                        new_part = self._layer_a_accumulated[channel][len(display_text):].strip()
                        if new_part:
                            display_text += " " + new_part
            else:
                # Layer A is active - show just A
                display_text = self._layer_a_accumulated[channel]
            
            frame = CaptionFrame(
                text=display_text,
                speaker=label,
                channel=channel,
                confidence=0.5,  # Low confidence - temporary
                is_partial=True,  # Will be replaced
                start_time=start_time,
                end_time=current_time,
                layer="A",
                caption_id=self._active_caption_id[channel],
            )
            
            # Emit Layer A
            self.logger.info("[Layer A] {} EMIT: \"{}\"", label, display_text[:70])
            self.events.emit("caption.frame", frame)
        else:
            self.logger.warning("[Layer A] {} transcription returned empty text", channel)

    def _process_layer_b(self, channel: str, label: str, current_time: float) -> None:
        """
        Layer B: Sliding windows for better accuracy (2-3s window, 0.5s step).
        Medium confidence, overlapped processing.
        """
        channel_sample_rate = self._actual_sample_rates.get(channel, self._sample_rate)
        
        # Get audio buffer (DON'T clear - Layer A needs it too!)
        with self._buffer_locks[channel]:
            if not self._audio_buffer[channel]:
                # Check for silence and finalize if needed
                self._check_layer_c_finalize(channel, label, current_time)
                return
            
            # Add new chunks to utterance buffer (copy, don't clear)
            new_chunks = self._audio_buffer[channel].copy()
            # DON'T clear buffer here - Layer A needs to read it too!
        
        # Add to utterance buffer if in active utterance
        if self._utterance_start[channel] is not None:
            self._utterance_buffer[channel].extend(new_chunks)
        
        # Concatenate for sliding window
        if not self._utterance_buffer[channel]:
            self.logger.debug("[Layer B] {} no utterance buffer", channel)
            return
        
        audio_data = np.concatenate(self._utterance_buffer[channel])
        
        # Take last 2.5s for Layer B window
        window_samples = int(channel_sample_rate * self._layer_b_window_duration)
        if len(audio_data) > window_samples:
            audio_data = audio_data[-window_samples:]
        
        # Need at least 1s for meaningful transcription
        min_samples = int(channel_sample_rate * 1.0)
        if len(audio_data) < min_samples:
            self.logger.debug(
                "[Layer B] {} audio too short: {:.2f}s < 1.0s",
                channel,
                len(audio_data) / channel_sample_rate
            )
            return
        
        self.logger.info(
            "[Layer B] {} processing {:.2f}s of audio...",
            channel,
            len(audio_data) / channel_sample_rate
        )
        
        # Detect speech
        is_speech = self._detect_speech(audio_data, channel, channel_sample_rate)
        
        if not is_speech:
            # Silence detected - increment counter
            self._silence_counter[channel] += 1
            
            # Check if ready to finalize (Layer C)
            if self._silence_counter[channel] >= self._silence_threshold_count:
                self._check_layer_c_finalize(channel, label, current_time)
            
            return
        
        # Reset silence counter on speech
        self._silence_counter[channel] = 0
        
        # Start new utterance if needed
        if self._utterance_start[channel] is None:
            self._utterance_start[channel] = current_time
        
        # Transcribe with better accuracy
        self.logger.info("[Layer B] {} starting transcription...", channel)
        text = self._transcribe_audio_data(audio_data, channel_sample_rate, channel)
        self.logger.info("[Layer B] {} transcription result: \"{}\"", channel, text if text else "(empty)")
        
        if text and text.strip():
            new_text = text.strip()
            
            # Check if switching from Layer A to Layer B or continuing Layer B
            if self._current_layer[channel] == "B":
                # MERGE within Layer B: append new text to accumulated Layer B text
                old_text = self._layer_b_accumulated[channel]
                if new_text.startswith(old_text[:min(20, len(old_text))]):
                    # Extension - use new text (it includes old + new)
                    self._layer_b_accumulated[channel] = new_text
                else:
                    # Different text - append
                    self._layer_b_accumulated[channel] = old_text + " " + new_text
                
                # Also append any new Layer A text that came after last Layer B
                layer_a_text = self._layer_a_accumulated[channel]
                if layer_a_text and len(layer_a_text) > len(self._layer_b_accumulated[channel]):
                    # Layer A has more - append the difference
                    new_part = layer_a_text[len(self._layer_b_accumulated[channel]):].strip()
                    if new_part:
                        self._layer_b_accumulated[channel] += " " + new_part
            else:
                # REPLACE: Switching from Layer A to Layer B
                # Start Layer B with confirmed text + any extra from Layer A
                self._layer_b_accumulated[channel] = new_text
                self._current_layer[channel] = "B"
                
                # Check if Layer A has more text ahead
                layer_a_text = self._layer_a_accumulated[channel]
                if layer_a_text and len(layer_a_text) > len(new_text):
                    # Layer A has more - append the difference
                    new_part = layer_a_text[len(new_text):].strip()
                    if new_part:
                        self._layer_b_accumulated[channel] += " " + new_part
            
            display_text = self._layer_b_accumulated[channel]
            
            frame = CaptionFrame(
                text=display_text,
                speaker=label,
                channel=channel,
                confidence=0.75,  # Medium confidence - improved
                is_partial=True,  # Still replaceable by Layer 3
                start_time=self._utterance_start[channel] or current_time,
                end_time=current_time,
                layer="B",
                caption_id=self._active_caption_id[channel],
            )
            
            # Emit Layer B (merged within B, or replaced Layer A)
            self.logger.info("[Layer B] {} EMIT (B_confirmed + A_new): \"{}\"", label, display_text[:70])
            self.events.emit("caption.frame", frame)
        else:
            self.logger.warning("[Layer B] {} transcription returned empty text", channel)

    def _check_layer_c_finalize(self, channel: str, label: str, current_time: float) -> None:
        """
        Layer C: Final pass on utterance end for highest accuracy.
        """
        if not self._utterance_buffer[channel] or self._utterance_start[channel] is None:
            # Nothing to finalize
            self._silence_counter[channel] = 0
            return
        
        channel_sample_rate = self._actual_sample_rates.get(channel, self._sample_rate)
        
        # Concatenate full utterance
        audio_data = np.concatenate(self._utterance_buffer[channel])
        
        # Transcribe full utterance for best accuracy
        text = self._transcribe_audio_data(audio_data, channel_sample_rate, channel)
        
        if text and text.strip():
            # Layer C: Final, most accurate text
            # This REPLACES all accumulated Layer A and Layer B text
            display_text = text.strip()
            
            # Update tracking
            self._current_layer[channel] = "C"
            
            frame = CaptionFrame(
                text=display_text,
                speaker=label,
                channel=channel,
                confidence=0.95,  # High confidence - final
                is_partial=False,  # FINAL - locked
                start_time=self._utterance_start[channel] or current_time,
                end_time=current_time,
                layer="C",
                caption_id=self._active_caption_id[channel],
            )
            
            # Emit Layer C (FINAL - replaces all accumulated A and B)
            self.logger.info("[Layer C] {} EMIT FINAL (REPLACES all A+B): \"{}\"", label, display_text)
            self.events.emit("caption.frame", frame)
        
        # Reset utterance tracking
        self._utterance_start[channel] = None
        self._utterance_buffer[channel] = []
        self._silence_counter[channel] = 0
        
        # Clear layer accumulations for next utterance
        self._layer_a_accumulated[channel] = ""
        self._layer_b_accumulated[channel] = ""
        self._current_layer[channel] = ""

    def _quick_transcribe(self, audio_data: np.ndarray, sample_rate: int, channel: str) -> str:
        """Quick transcription for Layer A using tiny model (optimized for speed)."""
        return self._transcribe_audio_data(audio_data, sample_rate, channel, use_fast_model=True)

    def _transcribe_audio_data(self, audio_data: np.ndarray, sample_rate: int, channel: str, use_fast_model: bool = False) -> str:
        """Transcribe audio data using Whisper."""
        # Save to temporary WAV file
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                wav_path = Path(tmp_file.name)
            
            # Save WAV
            with wave.open(str(wav_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(sample_rate)
                pcm_data = (audio_data * 32767).astype(np.int16)
                wav_file.writeframes(pcm_data.tobytes())
            
            # Transcribe with appropriate model
            text = self._transcribe_file(wav_path, use_fast_model=use_fast_model)
            
            # Clean up
            wav_path.unlink(missing_ok=True)
            
            # NO POST-PROCESSING - return raw text from Whisper
            if text:
                return text.strip()
            
            return ""
        
        except Exception as e:
            self.logger.error("Transcription error for {}: {}", channel, e)
            return ""

    def _process_channel(self, channel: str, label: str) -> None:
        """Process audio buffer for a specific channel with sliding window."""
        # Use actual sample rate for this channel if detected (for speaker WASAPI)
        channel_sample_rate = self._actual_sample_rates.get(channel, self._sample_rate)
        
        # Use channel-specific lock
        with self._buffer_locks[channel]:
            if not self._audio_buffer[channel]:
                return

            # Get new audio chunks
            new_chunks = self._audio_buffer[channel].copy()
            self._audio_buffer[channel].clear()

        # Add new chunks to sliding window
        self._sliding_window[channel].extend(new_chunks)
        
        # Concatenate all audio in sliding window
        audio_data = np.concatenate(self._sliding_window[channel])
        
        # Trim sliding window to max duration
        max_samples = int(channel_sample_rate * self._window_max_duration)
        if len(audio_data) > max_samples:
            # Keep only the most recent audio
            audio_data = audio_data[-max_samples:]
            # Recalculate chunks (approximate - just keep as single chunk)
            self._sliding_window[channel] = [audio_data]

        # Skip if too short - need at least 2.0 seconds (optimized for speed)
        min_samples = int(channel_sample_rate * 2.0)
        if len(audio_data) < min_samples:
            return

        # Detect speech using VAD or fallback to RMS
        is_speech = self._detect_speech(audio_data, channel, channel_sample_rate)
        
        if not is_speech:
            # Silence detected
            self.logger.debug("Silence detected for {}, silence count: {}", channel, self._silence_counter[channel] + 1)
            
            # Increment silence counter
            self._silence_counter[channel] += 1
            
            # Only finalize after sustained silence (multiple consecutive silent buffers)
            if self._silence_counter[channel] >= self._silence_threshold_count:
                self.logger.info("Sustained silence detected for {}, finalizing...", channel)
                
                # Emit any accumulated sentence buffer on sustained silence
                if self._sentence_buffer[channel].strip():
                    import uuid
                    if self._active_caption_id[channel] is None:
                        self._active_caption_id[channel] = str(uuid.uuid4())
                    
                    frame = CaptionFrame(
                        text=self._sentence_buffer[channel].strip(),
                        speaker=label,
                        channel=channel,
                        confidence=0.85,
                        is_partial=False,
                    )
                    
                    self.logger.info('Emitting buffered text after silence [{}]: "{}"', label, self._sentence_buffer[channel])
                    self.events.emit("caption.frame", frame)
                    self._sentence_buffer[channel] = ""
                    self._sentence_buffer_start_time[channel] = None
                
                # Clear sliding window on sustained silence and reset state
                self._sliding_window[channel].clear()
                self._last_full_text[channel] = ""
                self._active_caption_id[channel] = None
                self._silence_counter[channel] = 0
            
            return

        # Reset silence counter when speech is detected
        self._silence_counter[channel] = 0

        self.logger.info(
            "Processing {} audio: {:.1f} seconds, sample_rate: {}Hz",
            channel,
            len(audio_data) / channel_sample_rate,
            channel_sample_rate,
        )

        # Temporarily set sample rate for WAV saving
        original_rate = self._sample_rate
        self._sample_rate = channel_sample_rate

        # Save to WAV file (permanent or temporary)
        process_start = time.time()
        try:
            if self._save_recordings and self._recordings_dir:
                # Save to permanent file with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # milliseconds
                filename = f"{timestamp}_{channel}.wav"
                wav_path = self._recordings_dir / filename
                delete_after = False
                
                self._save_wav(wav_path, audio_data)
                self.logger.info("Saved {} audio to: {}", channel, filename)
                
                # Clean up old recordings if limit is set
                if self._max_recordings > 0:
                    self._cleanup_old_recordings(channel)
            else:
                # Use temporary file
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                    wav_path = Path(tmp_file.name)
                delete_after = True
                self._save_wav(wav_path, audio_data)

            # Process with whisper-cli
            text = self._transcribe_file(wav_path)
            
            # Clean up temporary file if needed
            if delete_after:
                wav_path.unlink(missing_ok=True)

            if text:
                # Clean up the text
                text = text.strip()
                text = self._clean_transcription(text)
                
                # Skip if text is empty after cleaning
                if not text:
                    self.logger.debug("Text empty after cleaning for {}", channel)
                    # Clear window if text was filtered out
                    self._sliding_window[channel].clear()
                else:
                    # Check if this is different from the last text
                    is_update = text != self._last_full_text[channel]
                    
                    if is_update:
                        import uuid
                        
                        # Accumulate text in sentence buffer
                        if self._sentence_buffer[channel]:
                            # Check if new text is extension or new fragment
                            if not text.startswith(self._sentence_buffer[channel][:min(20, len(self._sentence_buffer[channel]))]):
                                # New fragment - append with space
                                self._sentence_buffer[channel] += " " + text
                            else:
                                # Extension/refinement - replace
                                self._sentence_buffer[channel] = text
                        else:
                            # Start new buffer
                            self._sentence_buffer[channel] = text
                            self._sentence_buffer_start_time[channel] = time.time()
                            self._active_caption_id[channel] = str(uuid.uuid4())
                        
                        self._last_full_text[channel] = text
                        buffer_text = self._sentence_buffer[channel].strip()
                        
                        # Check timeout (only finalize on timeout, not punctuation)
                        # Punctuation in continuous speech shouldn't split captions
                        buffer_age = 0.0
                        if self._sentence_buffer_start_time[channel]:
                            buffer_age = time.time() - self._sentence_buffer_start_time[channel]
                        timeout_exceeded = buffer_age > self._sentence_buffer_timeout
                        
                        if timeout_exceeded:
                            # Timeout - emit as FINAL
                            frame = CaptionFrame(
                                text=buffer_text,
                                speaker=label,
                                channel=channel,
                                confidence=0.85,
                                is_partial=False,
                            )
                            
                            self.logger.info(
                                'Final sentence [{}] (timeout): "{}"',
                                label,
                                buffer_text,
                            )
                            self.events.emit("caption.frame", frame)
                            
                            # Clear buffer after final emission
                            self._sentence_buffer[channel] = ""
                            self._sentence_buffer_start_time[channel] = None
                            self._active_caption_id[channel] = None
                        else:
                            # Ongoing speech - emit as PARTIAL for real-time display
                            frame = CaptionFrame(
                                text=buffer_text,
                                speaker=label,
                                channel=channel,
                                confidence=0.7,
                                is_partial=True,
                            )
                            
                            self.logger.debug(
                                'Partial caption [{}]: "{}"',
                                label,
                                buffer_text,
                            )
                            self.events.emit("caption.frame", frame)
                        
                        # Clear audio window after processing to avoid re-transcribing
                        self._sliding_window[channel].clear()

        except Exception as exc:
            self.logger.exception("Error processing {} audio: {}", channel, exc)
        finally:
            # Restore original sample rate
            self._sample_rate = original_rate

    def _clean_transcription(self, text: str) -> str:
        """Clean transcription by removing repeated text and environmental noise."""
        # Remove environmental noise descriptions (case insensitive)
        noise_patterns = [
            r'\[.*?\]',  # [music], [applause], etc.
            r'\(.*?\)',  # (music playing), etc.
            r'♪.*?♪',    # Musical notes
        ]
        
        for pattern in noise_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Step 1: Remove repeated phrases within text (like "fast APR, fast APR, fast APR")
        # This regex finds patterns like "word word" or "phrase, phrase, phrase"
        def remove_consecutive_repeats(text: str) -> str:
            # Match repeated sequences of 1-10 words (with punctuation)
            # Pattern: capture a phrase, then match if it repeats immediately
            max_iterations = 10
            iteration = 0
            
            while iteration < max_iterations:
                # Find patterns like: "word word word" or "phrase, phrase, phrase"
                # Matches 1-10 words that repeat consecutively (with optional comma/punctuation)
                pattern = r'\b(\w+(?:\s+\w+){0,9})(?:[,\s]+\1){1,}'
                
                new_text = re.sub(
                    pattern,
                    r'\1',  # Replace with just one instance
                    text,
                    flags=re.IGNORECASE
                )
                
                if new_text == text:
                    break  # No more changes
                text = new_text
                iteration += 1
            
            return text
        
        text = remove_consecutive_repeats(text)
        
        # Step 2: Remove repeated sentences/phrases
        # Split by common sentence endings or commas for shorter phrases
        sentences = re.split(r'([.!?]+\s*)', text)
        
        # Reconstruct with punctuation
        cleaned_parts = []
        seen_sentences = set()
        
        i = 0
        while i < len(sentences):
            sentence = sentences[i].strip()
            
            if not sentence:
                i += 1
                continue
            
            # Get punctuation if it exists
            punctuation = ''
            if i + 1 < len(sentences) and re.match(r'^[.!?]+\s*$', sentences[i + 1]):
                punctuation = sentences[i + 1]
                i += 1
            
            # Normalize for comparison (lowercase, remove extra spaces)
            normalized = re.sub(r'\s+', ' ', sentence.lower()).strip()
            
            # Only add if we haven't seen this sentence before
            if normalized and normalized not in seen_sentences:
                seen_sentences.add(normalized)
                cleaned_parts.append(sentence + punctuation)
            
            i += 1
        
        # Join and clean up extra whitespace
        result = ' '.join(cleaned_parts)
        result = re.sub(r'\s+', ' ', result)
        result = result.strip()
        
        return result

    def _save_wav(self, path: Path, audio_data: np.ndarray) -> None:
        """Save audio data to WAV file with proper conversion."""
        # Ensure audio is in correct range and format
        # Input should be float32 in range [-1.0, 1.0]
        
        # Log original data stats
        mean_val = np.mean(np.abs(audio_data))
        max_val = np.abs(audio_data).max()
        min_val = audio_data.min()
        max_pos_val = audio_data.max()
        
        self.logger.debug(
            "Input audio stats: dtype={}, mean_abs={:.6f}, min={:.6f}, max={:.6f}, max_abs={:.6f}",
            audio_data.dtype,
            mean_val,
            min_val,
            max_pos_val,
            max_val,
        )
        
        # Check if audio data is essentially silent or corrupted
        if max_val < 1e-6:
            self.logger.warning("Audio data is essentially silent (max={:.9f})", max_val)
        
        # Ensure we're working with float32
        if audio_data.dtype != np.float32:
            self.logger.debug("Converting audio from {} to float32", audio_data.dtype)
            audio_data = audio_data.astype(np.float32)
        
        # Normalize if needed
        if max_val > 1.0:
            self.logger.warning("Audio data exceeds [-1, 1] range, normalizing. Max: {:.2f}", max_val)
            audio_data = audio_data / max_val
        elif max_val > 0 and max_val < 0.01:
            # Audio is too quiet, amplify it
            scale_factor = 0.5 / max_val  # Scale to 50% of max to avoid clipping
            self.logger.warning("Audio too quiet (max={:.6f}), amplifying by {:.2f}x", max_val, scale_factor)
            audio_data = audio_data * scale_factor
        
        # Convert float32 [-1.0, 1.0] to int16 [-32768, 32767]
        # Use round instead of clip for better accuracy
        audio_int16 = np.round(audio_data * 32767.0).astype(np.int16)
        
        self.logger.debug(
            "Output WAV: {} samples, int16 range=[{}, {}]",
            len(audio_int16),
            audio_int16.min(),
            audio_int16.max(),
        )

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(audio_int16.tobytes())
        
        self.logger.info("Saved WAV: {} bytes at {}Hz", path.stat().st_size, self._sample_rate)

    def _transcribe_file(self, audio_path: Path, use_fast_model: bool = False) -> str | None:
        """Transcribe audio file using whisper-cli."""
        try:
            # Choose model based on layer
            model_path = self._model_path_fast if use_fast_model else self._model_path
            timeout = 10 if use_fast_model else 60  # Tiny model: 10s, Medium model: 60s
            
            cmd = [
                str(self._whisper_exe),
                "-m", str(model_path),
                "-l", self.settings.whisper_language,
                "-f", str(audio_path),
                "--no-prints",  # Suppress debug output
                "-nt",  # No timestamps
                "-t", "4",  # Threads
            ]
            
            # Add prompt if configured (helps with context/terminology)
            if self.settings.whisper_prompt:
                cmd.extend(["--prompt", self.settings.whisper_prompt])

            self.logger.debug("Running whisper command ({}): {}", "FAST" if use_fast_model else "ACCURATE", " ".join(cmd))
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )

            if result.returncode != 0:
                self.logger.error("Whisper-cli failed with code {}: stderr={}, stdout={}", 
                                result.returncode, result.stderr, result.stdout)
                return None
            
            self.logger.debug("Whisper stdout: {}", result.stdout[:200] if result.stdout else "empty")

            # Parse output - look for lines that don't contain metadata
            lines = result.stdout.strip().split('\n')
            transcription_lines = []
            
            for line in lines:
                line = line.strip()
                # Skip empty lines and lines that look like metadata
                if not line or line.startswith('[') or '-->' in line:
                    continue
                # Skip lines that are just timestamps
                if line.replace(':', '').replace('.', '').replace(' ', '').isdigit():
                    continue
                transcription_lines.append(line)

            text = ' '.join(transcription_lines).strip()
            
            if text:
                self.logger.debug("Transcription result: {}", text[:100])
                return text
            else:
                self.logger.warning("Whisper returned empty transcription for: {}", audio_path.name)
                return None

        except subprocess.TimeoutExpired:
            model_name = "tiny" if use_fast_model else "medium"
            self.logger.error("Whisper transcription timed out ({}s, {} model) - audio may be too long", timeout, model_name)
            return None
        except Exception as exc:
            self.logger.exception("Transcription error: {}", exc)
            return None

    def _cleanup_old_recordings(self, channel: str) -> None:
        """Remove old recordings if exceeding max limit."""
        if not self._recordings_dir or self._max_recordings <= 0:
            return
        
        try:
            # Get all recordings for this channel, sorted by modification time
            pattern = f"*_{channel}.wav"
            recordings = sorted(
                self._recordings_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,  # Newest first
            )
            
            # Delete old recordings beyond the limit
            if len(recordings) > self._max_recordings:
                for old_file in recordings[self._max_recordings:]:
                    old_file.unlink(missing_ok=True)
                    self.logger.debug("Deleted old recording: {}", old_file.name)
                
                deleted_count = len(recordings) - self._max_recordings
                self.logger.info(
                    "Cleaned up {} old {} recordings (limit: {})",
                    deleted_count,
                    channel,
                    self._max_recordings,
                )
        except Exception as exc:
            self.logger.warning("Failed to cleanup old recordings: {}", exc)

