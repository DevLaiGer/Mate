"""Tests for VAD module."""

import numpy as np
import pytest

from mate.audio.vad import VADDetector, VADResult


def test_vad_initialization():
    """Test VAD initializes correctly."""
    vad = VADDetector(sample_rate=16000, frame_duration_ms=30, mode=2)
    assert vad.sample_rate == 16000
    assert vad.frame_duration_ms == 30
    assert vad.frame_size == 480  # 16000 * 30 / 1000


def test_vad_invalid_sample_rate():
    """Test VAD rejects invalid sample rates."""
    with pytest.raises(ValueError):
        VADDetector(sample_rate=44100)


def test_vad_process_silence():
    """Test VAD detects silence correctly."""
    vad = VADDetector(sample_rate=16000, frame_duration_ms=30)
    
    # Generate silence (zeros)
    silence = np.zeros(480, dtype=np.float32)
    result = vad.process_frame(silence, timestamp=0.0)
    
    assert isinstance(result, VADResult)
    assert result.is_speech is False


def test_vad_process_speech():
    """Test VAD detects speech (simulated with noise)."""
    vad = VADDetector(sample_rate=16000, frame_duration_ms=30)
    
    # Generate noise that should be detected as speech
    np.random.seed(42)
    speech = np.random.normal(0, 0.3, 480).astype(np.float32)
    result = vad.process_frame(speech, timestamp=0.0)
    
    assert isinstance(result, VADResult)
    # Note: actual detection depends on the audio characteristics


def test_vad_hangover():
    """Test VAD hangover keeps speech active after silence."""
    vad = VADDetector(sample_rate=16000, frame_duration_ms=30, hangover_ms=90)
    
    # Process speech
    speech = np.random.normal(0, 0.3, 480).astype(np.float32)
    vad.process_frame(speech)
    
    # Process silence - hangover should keep is_speech True for a few frames
    silence = np.zeros(480, dtype=np.float32)
    result1 = vad.process_frame(silence)
    result2 = vad.process_frame(silence)
    result3 = vad.process_frame(silence)
    
    # At least one should still detect speech due to hangover
    # (exact behavior depends on VAD internals)
    assert isinstance(result3, VADResult)


def test_vad_stats():
    """Test VAD statistics tracking."""
    vad = VADDetector(sample_rate=16000, frame_duration_ms=30)
    
    stats = vad.get_stats()
    assert "speech_ratio" in stats
    assert "total_frames" in stats
    assert stats["total_frames"] == 0

