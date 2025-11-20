"""Voice Activity Detection (VAD) module using WebRTC VAD."""

from __future__ import annotations

import struct
from collections import deque
from dataclasses import dataclass

import numpy as np
import webrtcvad

from mate.logging import get_logger


@dataclass
class VADResult:
    """Result of VAD detection."""
    
    is_speech: bool
    confidence: float  # 0.0 to 1.0
    timestamp: float


class VADDetector:
    """Voice Activity Detector using WebRTC VAD with hangover support."""
    
    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        mode: int = 2,
        hangover_ms: int = 300,
    ):
        """
        Initialize VAD detector.
        
        Args:
            sample_rate: Audio sample rate (8000, 16000, 32000, or 48000)
            frame_duration_ms: Frame duration (10, 20, or 30 ms)
            mode: VAD aggressiveness mode (0-3, higher = more aggressive)
            hangover_ms: Continue detecting speech for this duration after speech ends
        """
        self.logger = get_logger("vad")
        
        if sample_rate not in [8000, 16000, 32000, 48000]:
            raise ValueError(f"Sample rate must be 8000, 16000, 32000, or 48000, got {sample_rate}")
        
        if frame_duration_ms not in [10, 20, 30]:
            raise ValueError(f"Frame duration must be 10, 20, or 30 ms, got {frame_duration_ms}")
        
        if mode not in [0, 1, 2, 3]:
            raise ValueError(f"Mode must be 0-3, got {mode}")
        
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.mode = mode
        self.hangover_ms = hangover_ms
        
        # Calculate frame size
        self.frame_size = int(sample_rate * frame_duration_ms / 1000)
        self.frame_bytes = self.frame_size * 2  # 16-bit PCM
        
        # Initialize WebRTC VAD
        self.vad = webrtcvad.Vad(mode)
        
        # Hangover tracking
        self.hangover_frames = int(hangover_ms / frame_duration_ms)
        self.speech_frames = deque(maxlen=self.hangover_frames)
        
        # Statistics
        self.total_frames = 0
        self.speech_count = 0
        
        self.logger.info(
            "VAD initialized: {}Hz, {}ms frames, mode={}, hangover={}ms",
            sample_rate,
            frame_duration_ms,
            mode,
            hangover_ms,
        )
    
    def process_frame(self, audio_frame: np.ndarray, timestamp: float = 0.0) -> VADResult:
        """
        Process a single audio frame.
        
        Args:
            audio_frame: Audio data as float32 numpy array [-1.0, 1.0]
            timestamp: Timestamp of this frame in seconds
            
        Returns:
            VADResult with speech detection result
        """
        if len(audio_frame) != self.frame_size:
            raise ValueError(
                f"Frame size mismatch: expected {self.frame_size}, got {len(audio_frame)}"
            )
        
        # Convert float32 [-1.0, 1.0] to int16 PCM
        pcm_data = (audio_frame * 32767).astype(np.int16)
        pcm_bytes = pcm_data.tobytes()
        
        # Run VAD
        try:
            is_speech = self.vad.is_speech(pcm_bytes, self.sample_rate)
        except Exception as e:
            self.logger.warning("VAD error: {}, assuming silence", e)
            is_speech = False
        
        # Update statistics
        self.total_frames += 1
        if is_speech:
            self.speech_count += 1
        
        # Apply hangover: if we detected speech recently, continue reporting speech
        self.speech_frames.append(is_speech)
        has_recent_speech = any(self.speech_frames)
        
        # Calculate confidence based on recent history
        if len(self.speech_frames) > 0:
            confidence = sum(self.speech_frames) / len(self.speech_frames)
        else:
            confidence = 1.0 if is_speech else 0.0
        
        return VADResult(
            is_speech=has_recent_speech,
            confidence=confidence,
            timestamp=timestamp,
        )
    
    def process_buffer(self, audio_buffer: np.ndarray, start_timestamp: float = 0.0) -> list[VADResult]:
        """
        Process a buffer of audio by splitting into frames.
        
        Args:
            audio_buffer: Audio data as float32 numpy array
            start_timestamp: Starting timestamp in seconds
            
        Returns:
            List of VADResult for each frame
        """
        results = []
        
        # Split buffer into frames
        num_frames = len(audio_buffer) // self.frame_size
        
        for i in range(num_frames):
            start_idx = i * self.frame_size
            end_idx = start_idx + self.frame_size
            frame = audio_buffer[start_idx:end_idx]
            
            timestamp = start_timestamp + (i * self.frame_duration_ms / 1000)
            result = self.process_frame(frame, timestamp)
            results.append(result)
        
        return results
    
    def is_speaking(self) -> bool:
        """Check if currently detecting speech (with hangover)."""
        return any(self.speech_frames)
    
    def reset(self) -> None:
        """Reset VAD state."""
        self.speech_frames.clear()
        self.logger.debug("VAD state reset")
    
    def get_stats(self) -> dict[str, float]:
        """Get VAD statistics."""
        if self.total_frames == 0:
            return {"speech_ratio": 0.0, "total_frames": 0}
        
        return {
            "speech_ratio": self.speech_count / self.total_frames,
            "total_frames": self.total_frames,
            "speech_frames": self.speech_count,
        }

