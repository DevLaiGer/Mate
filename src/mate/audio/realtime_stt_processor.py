"""Real-time speech-to-text processor using RealtimeSTT library."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from mate.audio.capture import AudioCapture, AudioFrame
from mate.config import CaptionSettings
from mate.core.events import EventBus
from mate.core.state import CaptionFrame
from mate.logging import get_logger


class RealtimeSTTProcessor:
    """Processes audio frames using RealtimeSTT for real-time transcription."""

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
        
        # RealtimeSTT recorders (one per channel)
        self._recorders: dict[str, any] = {}
        
        self._sample_rate = capture.settings.sample_rate
        self._actual_sample_rates: dict[str, int] = {}
        
        self.logger.info("RealtimeSTT processor initialized")

    def start(self) -> bool:
        """Start the RealtimeSTT processor."""
        if self._running:
            return True

        try:
            from RealtimeSTT import AudioToTextRecorder
            
            # Create RealtimeSTT recorder for mic
            self.logger.info("Initializing RealtimeSTT recorder for microphone...")
            self._recorders["mic"] = AudioToTextRecorder(
                model=self.settings.whisper_language,
                language=self.settings.whisper_language,
                spinner=False,
                silero_sensitivity=0.4,  # VAD sensitivity
                webrtc_sensitivity=2,
                post_speech_silence_duration=0.4,  # Finalize after 400ms silence
                min_length_of_recording=0.5,  # Minimum 500ms before transcribing
                min_gap_between_recordings=0.0,
                enable_realtime_transcription=True,
                realtime_processing_pause=0.1,  # Check for transcription every 100ms
                on_realtime_transcription_update=lambda text: self._on_mic_update(text),
                on_realtime_transcription_stabilized=lambda text: self._on_mic_stabilized(text),
            )
            
            # Create RealtimeSTT recorder for speaker
            self.logger.info("Initializing RealtimeSTT recorder for speaker...")
            self._recorders["speaker"] = AudioToTextRecorder(
                model=self.settings.whisper_language,
                language=self.settings.whisper_language,
                spinner=False,
                silero_sensitivity=0.4,
                webrtc_sensitivity=2,
                post_speech_silence_duration=0.4,
                min_length_of_recording=0.5,
                min_gap_between_recordings=0.0,
                enable_realtime_transcription=True,
                realtime_processing_pause=0.1,
                on_realtime_transcription_update=lambda text: self._on_speaker_update(text),
                on_realtime_transcription_stabilized=lambda text: self._on_speaker_stabilized(text),
            )
            
            self.logger.info("✓ RealtimeSTT recorders initialized")
            
        except ImportError as e:
            self.logger.error("RealtimeSTT not installed: {}", e)
            self.logger.error("Install with: pip install RealtimeSTT")
            return False
        except Exception as e:
            self.logger.error("Failed to initialize RealtimeSTT: {}", e)
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

        self.logger.info("RealtimeSTT processor started")
        return True

    def stop(self) -> None:
        """Stop the processor and release resources."""
        if not self._running:
            return

        self.logger.info("Stopping RealtimeSTT processor...")
        self._running = False

        # Stop recorders
        for channel, recorder in self._recorders.items():
            try:
                if hasattr(recorder, 'stop'):
                    recorder.stop()
                    self.logger.info("Stopped {} recorder", channel)
            except Exception as e:
                self.logger.warning("Error stopping {} recorder: {}", channel, e)

        # Wait for threads
        if self._mic_thread and self._mic_thread.is_alive():
            self._mic_thread.join(timeout=2.0)
        if self._speaker_thread and self._speaker_thread.is_alive():
            self._speaker_thread.join(timeout=2.0)

        # Stop capture
        self.capture.stop()
        
        self.logger.info("RealtimeSTT processor stopped")

    def _handle_audio_frame(self, frame: AudioFrame) -> None:
        """Handle incoming audio frame from capture."""
        channel = frame.channel
        
        # Track actual sample rate
        if channel not in self._actual_sample_rates:
            self._actual_sample_rates[channel] = frame.sample_rate
            self.logger.info(
                "Detected {} sample rate: {}Hz",
                channel,
                frame.sample_rate,
            )
        
        # Add to buffer
        with self._buffer_locks[channel]:
            self._audio_buffer[channel].append(frame.audio_data)

    def _process_loop(self, channel: str, label: str) -> None:
        """Process audio loop - feeds audio to RealtimeSTT."""
        self.logger.info("Started RealtimeSTT thread for {}", label)
        
        recorder = self._recorders.get(channel)
        if not recorder:
            self.logger.error("No recorder found for {}", channel)
            return
        
        while self._running:
            # Get audio chunks
            with self._buffer_locks[channel]:
                if not self._audio_buffer[channel]:
                    time.sleep(0.05)
                    continue
                
                audio_chunks = self._audio_buffer[channel].copy()
                self._audio_buffer[channel].clear()
            
            # Concatenate audio
            if audio_chunks:
                audio_data = np.concatenate(audio_chunks)
                
                # Feed to RealtimeSTT recorder
                try:
                    # RealtimeSTT expects int16 PCM data
                    pcm_data = (audio_data * 32767).astype(np.int16)
                    recorder.feed_audio(pcm_data.tobytes())
                except Exception as e:
                    self.logger.error("Error feeding audio to {}: {}", channel, e)
            
            time.sleep(0.05)
        
        self.logger.info("Stopped RealtimeSTT thread for {}", label)

    def _on_mic_update(self, text: str) -> None:
        """Handle real-time transcription update from mic."""
        if not text or not text.strip():
            return
        
        frame = CaptionFrame(
            text=text.strip(),
            speaker="Mic",
            channel="mic",
            confidence=0.7,
            is_partial=True,
        )
        
        self.logger.debug("[Mic] Partial: \"{}\"", text[:50])
        self.events.emit("caption.frame", frame)

    def _on_mic_stabilized(self, text: str) -> None:
        """Handle stabilized (final) transcription from mic."""
        if not text or not text.strip():
            return
        
        frame = CaptionFrame(
            text=text.strip(),
            speaker="Mic",
            channel="mic",
            confidence=0.95,
            is_partial=False,
        )
        
        self.logger.info("[Mic] FINAL: \"{}\"", text)
        self.events.emit("caption.frame", frame)

    def _on_speaker_update(self, text: str) -> None:
        """Handle real-time transcription update from speaker."""
        if not text or not text.strip():
            return
        
        frame = CaptionFrame(
            text=text.strip(),
            speaker="Speaker",
            channel="speaker",
            confidence=0.7,
            is_partial=True,
        )
        
        self.logger.debug("[Speaker] Partial: \"{}\"", text[:50])
        self.events.emit("caption.frame", frame)

    def _on_speaker_stabilized(self, text: str) -> None:
        """Handle stabilized (final) transcription from speaker."""
        if not text or not text.strip():
            return
        
        frame = CaptionFrame(
            text=text.strip(),
            speaker="Speaker",
            channel="speaker",
            confidence=0.95,
            is_partial=False,
        )
        
        self.logger.info("[Speaker] FINAL: \"{}\"", text)
        self.events.emit("caption.frame", frame)

