"""Direct WASAPI test - save raw audio to WAV without any processing."""

import time
import wave
from pathlib import Path

import numpy as np

from mate.audio.wasapi_loopback import WasapiLoopbackCapture
from mate.logging import get_logger

logger = get_logger("wasapi-test")

# Collect audio chunks
audio_chunks = []
max_duration = 10  # seconds
start_time = None


def audio_callback(samples: np.ndarray) -> None:
    """Collect audio samples."""
    global start_time
    if start_time is None:
        start_time = time.time()
    
    audio_chunks.append(samples.copy())
    elapsed = time.time() - start_time
    
    if elapsed >= max_duration:
        logger.info("Collected {:.1f} seconds of audio, {} chunks", elapsed, len(audio_chunks))


def main():
    """Test WASAPI capture and save to WAV."""
    logger.info("=== WASAPI Direct Capture Test ===")
    logger.info("This will capture 10 seconds of audio from your speakers")
    logger.info("Play some audio (YouTube, music, etc.) NOW!")
    
    # Start capture
    capture = WasapiLoopbackCapture(
        target_rate=16000,  # Not used since resampling is disabled
        callback=audio_callback,
    )
    
    try:
        capture.start()
        
        actual_rate = capture._sample_rate
        channels = capture._channels
        is_float = capture._is_float
        
        logger.info("Capture started:")
        logger.info("  Sample rate: {}Hz", actual_rate)
        logger.info("  Channels: {}", channels)
        logger.info("  Format: {}", "float32" if is_float else "int16")
        
        # Wait for audio collection
        while start_time is None or (time.time() - start_time) < max_duration:
            time.sleep(0.1)
        
        # Stop capture
        capture.stop()
        
        if not audio_chunks:
            logger.error("No audio captured!")
            return
        
        # Concatenate all chunks
        logger.info("Concatenating {} chunks...", len(audio_chunks))
        audio_data = np.concatenate(audio_chunks)
        
        logger.info("Total samples: {}", len(audio_data))
        logger.info("Audio stats:")
        logger.info("  dtype: {}", audio_data.dtype)
        logger.info("  min: {:.6f}", audio_data.min())
        logger.info("  max: {:.6f}", audio_data.max())
        logger.info("  mean_abs: {:.6f}", np.abs(audio_data).mean())
        logger.info("  std: {:.6f}", audio_data.std())
        
        # Save to WAV file
        output_path = Path("test_wasapi_output.wav")
        
        # Convert float32 to int16
        if audio_data.dtype == np.float32:
            # Ensure range is [-1.0, 1.0]
            max_val = np.abs(audio_data).max()
            if max_val > 1.0:
                logger.warning("Audio exceeds [-1, 1] range, normalizing")
                audio_data = audio_data / max_val
            
            audio_int16 = np.round(audio_data * 32767.0).astype(np.int16)
        else:
            audio_int16 = audio_data.astype(np.int16)
        
        logger.info("Saving to: {}", output_path)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(actual_rate)
            wav_file.writeframes(audio_int16.tobytes())
        
        file_size = output_path.stat().st_size
        duration = len(audio_data) / actual_rate
        
        logger.info("✓ SUCCESS!")
        logger.info("Saved: {} ({:.2f} MB, {:.1f} seconds)", output_path, file_size / 1024 / 1024, duration)
        logger.info("")
        logger.info("Now PLAY the file: {}", output_path)
        logger.info("Does it sound clear or corrupted/distorted?")
        
    except Exception as exc:
        logger.exception("Test failed: {}", exc)
        capture.stop()


if __name__ == "__main__":
    main()

