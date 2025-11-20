"""Real-time speech-to-text processor using faster-whisper (from RealtimeSTT)."""

from __future__ import annotations

import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

from mate.audio.capture import AudioCapture, AudioFrame
from mate.config import CaptionSettings
from mate.core.events import EventBus
from mate.core.state import CaptionFrame
from mate.logging import get_logger


class RealtimeSTTProcessor:
    """Processes audio frames using faster-whisper for real-time transcription."""

    def __init__(
        self,
        settings: CaptionSettings,
        capture: AudioCapture,
        events: EventBus,
    ) -> None:
        self.settings = settings
        self.capture = capture
        self.events = events
        self.logger = get_logger("realtime-stt")
        self._running = False
        
        # Audio buffers per channel
        self._audio_buffer: dict[str, list[np.ndarray]] = {"mic": [], "speaker": []}
        self._buffer_locks: dict[str, threading.Lock] = {
            "mic": threading.Lock(),
            "speaker": threading.Lock(),
        }
        
        # Processing threads
        self._mic_thread: threading.Thread | None = None
        self._speaker_thread: threading.Thread | None = None
        
        # faster-whisper models
        self._models: dict[str, any] = {}
        
        self._sample_rate = capture.settings.sample_rate
        self._actual_sample_rates: dict[str, int] = {}
        
        # Transcription settings
        self._buffer_duration = 1.0  # Process every 1 second
        
        # Track last transcription per channel
        self._last_text: dict[str, str] = {"mic": "", "speaker": ""}
        
        self.logger.info("RealtimeSTT processor initialized")

    def start(self) -> bool:
        """Start the faster-whisper processor."""
        if self._running:
            return True

        try:
            from faster_whisper import WhisperModel
            
            # Initialize faster-whisper models
            self.logger.info("Loading faster-whisper models...")
            
            # Base model for real-time transcription
            self._models["base"] = WhisperModel(
                "base",
                device="cpu",  # Use "cuda" if you have GPU
                compute_type="int8",  # Quantization for speed
            )
            
            self.logger.info("✓ faster-whisper model loaded: base")
            
        except ImportError as e:
            self.logger.error("faster-whisper not installed: {}", e)
            self.logger.error("Install with: pip install faster-whisper")
            return False
        except Exception as e:
            self.logger.error("Failed to load faster-whisper model: {}", e)
            return False

        self._running = True

        # Register audio callbacks
        self.capture.register(self._handle_audio_frame)

        # Start capture
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

        self.logger.info("faster-whisper processor started")
        return True

    def stop(self) -> None:
        """Stop the processor and release resources."""
        if not self._running:
            return

        self.logger.info("Stopping faster-whisper processor...")
        self._running = False

        # Wait for threads
        if self._mic_thread and self._mic_thread.is_alive():
            self._mic_thread.join(timeout=2.0)
        if self._speaker_thread and self._speaker_thread.is_alive():
            self._speaker_thread.join(timeout=2.0)

        # Stop capture
        self.capture.stop()
        
        self.logger.info("faster-whisper processor stopped")

    def _handle_audio_frame(self, frame: AudioFrame) -> None:
        """Handle incoming audio frame from capture."""
        channel = frame.channel
        
        # Track actual sample rate (use capture settings)
        if channel not in self._actual_sample_rates:
            self._actual_sample_rates[channel] = self._sample_rate
            self.logger.info(
                "Using {} sample rate: {}Hz",
                channel,
                self._sample_rate,
            )
        
        # Add to buffer
        with self._buffer_locks[channel]:
            self._audio_buffer[channel].append(frame.samples)

    def _process_loop(self, channel: str, label: str) -> None:
        """Process audio loop - transcribes with faster-whisper."""
        self.logger.info("Started faster-whisper thread for {}", label)
        
        model = self._models.get("base")
        if not model:
            self.logger.error("No model found for {}", channel)
            return
        
        last_process_time = time.time()
        
        while self._running:
            current_time = time.time()
            
            # Process every buffer_duration seconds
            if current_time - last_process_time < self._buffer_duration:
                time.sleep(0.1)
                continue
            
            # Get audio chunks
            with self._buffer_locks[channel]:
                if not self._audio_buffer[channel]:
                    time.sleep(0.1)
                    continue
                
                audio_chunks = self._audio_buffer[channel].copy()
                self._audio_buffer[channel].clear()
            
            # Concatenate audio
            audio_data = np.concatenate(audio_chunks)
            
            # Check for speech (RMS)
            rms = float(np.sqrt(np.mean(np.square(audio_data))))
            if rms < 0.01:
                continue
            
            # Get sample rate
            channel_sample_rate = self._actual_sample_rates.get(channel, self._sample_rate)
            
            # Transcribe with faster-whisper
            try:
                text = self._transcribe_audio(audio_data, channel_sample_rate, model, label)
                
                if text and text.strip() and text != self._last_text[channel]:
                    # Emit partial caption
                    frame = CaptionFrame(
                        text=text.strip(),
                        speaker=label,
                        channel=channel,
                        confidence=0.8,
                        is_partial=True,
                    )
                    
                    # Print to console
                    print(f"\n[{label}] {text}")
                    print("-" * 80)
                    
                    self.logger.info("[{}] \"{}\"", label, text[:70])
                    self.events.emit("caption.frame", frame)
                    self._last_text[channel] = text
                    
            except Exception as e:
                self.logger.error("Transcription error for {}: {}", channel, e)
            
            last_process_time = current_time
        
        self.logger.info("Stopped faster-whisper thread for {}", label)

    def _transcribe_audio(self, audio_data: np.ndarray, sample_rate: int, model: any, label: str) -> str:
        """Transcribe audio using faster-whisper."""
        try:
            # Convert float32 to int16
            audio_int16 = (audio_data * 32767).astype(np.int16)
            
            # faster-whisper expects float32 in range [-1, 1]
            audio_float32 = audio_int16.astype(np.float32) / 32767.0
            
            # Transcribe
            segments, info = model.transcribe(
                audio_float32,
                language=self.settings.whisper_language,
                vad_filter=True,  # Enable VAD filtering
                vad_parameters=dict(
                    threshold=0.5,
                    min_silence_duration_ms=500,
                ),
            )
            
            # Collect all segments
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text)
            
            text = " ".join(text_parts).strip()
            return text
            
        except Exception as e:
            self.logger.error("Transcription error: {}", e)
            return ""

