"""Pure Python WASAPI loopback capture using comtypes."""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable

import numpy as np
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, IUnknown, c_int64
from loguru import logger

# WASAPI COM interface GUIDs
CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IMMDevice = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
IID_IAudioCaptureClient = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")

# Constants
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_BUFFERFLAGS_SILENT = 0x00000002
WAVE_FORMAT_PCM = 1
WAVE_FORMAT_IEEE_FLOAT = 3
eRender = 0
eConsole = 0


# Define COM interfaces using comtypes
class IMMDeviceEnumerator(IUnknown):
    """IMMDeviceEnumerator COM interface."""

    _iid_ = IID_IMMDeviceEnumerator
    _methods_ = [
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "EnumAudioEndpoints",
            (["in"], ctypes.c_int, "dataFlow"),
            (["in"], ctypes.c_int, "dwStateMask"),
            (["out"], ctypes.POINTER(ctypes.c_void_p), "ppDevices"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetDefaultAudioEndpoint",
            (["in"], ctypes.c_int, "dataFlow"),
            (["in"], ctypes.c_int, "role"),
            (["out"], ctypes.POINTER(ctypes.c_void_p), "ppEndpoint"),
        ),
    ]


class IMMDevice(IUnknown):
    """IMMDevice COM interface."""

    _iid_ = IID_IMMDevice
    _methods_ = [
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "Activate",
            (["in"], ctypes.POINTER(GUID), "iid"),
            (["in"], ctypes.c_int, "dwClsCtx"),
            (["in"], ctypes.c_void_p, "pActivationParams"),
            (["out"], ctypes.POINTER(ctypes.c_void_p), "ppInterface"),
        ),
        COMMETHOD([], ctypes.HRESULT, "OpenPropertyStore"),
        COMMETHOD([], ctypes.HRESULT, "GetId"),
        COMMETHOD([], ctypes.HRESULT, "GetState"),
    ]


class WAVEFORMATEX(ctypes.Structure):
    """WAVEFORMATEX structure."""

    _fields_ = [
        ("wFormatTag", ctypes.c_uint16),
        ("nChannels", ctypes.c_uint16),
        ("nSamplesPerSec", ctypes.c_uint32),
        ("nAvgBytesPerSec", ctypes.c_uint32),
        ("nBlockAlign", ctypes.c_uint16),
        ("wBitsPerSample", ctypes.c_uint16),
        ("cbSize", ctypes.c_uint16),
    ]


class IAudioClient(IUnknown):
    """IAudioClient COM interface."""

    _iid_ = IID_IAudioClient
    _methods_ = [
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "Initialize",
            (["in"], ctypes.c_int, "ShareMode"),
            (["in"], ctypes.c_uint32, "StreamFlags"),
            (["in"], c_int64, "hnsBufferDuration"),
            (["in"], c_int64, "hnsPeriodicity"),
            (["in"], ctypes.POINTER(WAVEFORMATEX), "pFormat"),
            (["in"], ctypes.c_void_p, "AudioSessionGuid"),
        ),
        COMMETHOD([], ctypes.HRESULT, "GetBufferSize"),
        COMMETHOD([], ctypes.HRESULT, "GetStreamLatency"),
        COMMETHOD([], ctypes.HRESULT, "GetCurrentPadding"),
        COMMETHOD([], ctypes.HRESULT, "IsFormatSupported"),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetMixFormat",
            (["out"], ctypes.POINTER(ctypes.POINTER(WAVEFORMATEX)), "ppDeviceFormat"),
        ),
        COMMETHOD([], ctypes.HRESULT, "GetDevicePeriod"),
        COMMETHOD([], ctypes.HRESULT, "Start"),
        COMMETHOD([], ctypes.HRESULT, "Stop"),
        COMMETHOD([], ctypes.HRESULT, "Reset"),
        COMMETHOD([], ctypes.HRESULT, "SetEventHandle"),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetService",
            (["in"], ctypes.POINTER(GUID), "riid"),
            (["out"], ctypes.POINTER(ctypes.c_void_p), "ppv"),
        ),
    ]


class IAudioCaptureClient(IUnknown):
    """IAudioCaptureClient COM interface."""

    _iid_ = IID_IAudioCaptureClient
    _methods_ = [
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetBuffer",
            (["out"], ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)), "ppData"),
            (["out"], ctypes.POINTER(ctypes.c_uint32), "pNumFramesToRead"),
            (["out"], ctypes.POINTER(ctypes.c_uint32), "pdwFlags"),
            (["out"], ctypes.POINTER(ctypes.c_uint64), "pu64DevicePosition"),
            (["out"], ctypes.POINTER(ctypes.c_uint64), "pu64QPCPosition"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "ReleaseBuffer",
            (["in"], ctypes.c_uint32, "NumFramesRead"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetNextPacketSize",
            (["out"], ctypes.POINTER(ctypes.c_uint32), "pNumFramesInNextPacket"),
        ),
    ]


class WasapiLoopbackCapture:
    """Pure Python WASAPI loopback capture using COM interfaces."""

    def __init__(
        self,
        target_rate: int = 16000,
        callback: Callable[[np.ndarray], None] | None = None,
    ) -> None:
        self.target_rate = target_rate
        self.callback = callback
        self.logger = logger.bind(name="wasapi-loopback")
        self._running = False
        self._thread: threading.Thread | None = None
        self._device_enumerator: IMMDeviceEnumerator | None = None
        self._device: IMMDevice | None = None
        self._audio_client: IAudioClient | None = None
        self._capture_client: IAudioCaptureClient | None = None
        self._wave_format: WAVEFORMATEX | None = None
        self._frame_size = 0
        self._sample_rate = 0
        self._channels = 0
        self._is_float = False
        self._disable_resampling = True  # Don't resample small chunks - causes distortion!

    def start(self) -> None:
        """Start WASAPI loopback capture."""
        if self._running:
            return

        try:
            # Initialize COM for this thread
            import comtypes.client

            comtypes.CoInitialize()

            # Create device enumerator
            self._device_enumerator = comtypes.client.CreateObject(
                CLSID_MMDeviceEnumerator,
                clsctx=CLSCTX_ALL,
                interface=IMMDeviceEnumerator,
            )

            # Get default render endpoint
            # comtypes returns a raw c_void_p, so we need to cast it to IMMDevice*
            device_ptr = self._device_enumerator.GetDefaultAudioEndpoint(
                eRender, eConsole
            )
            
            # Cast the raw pointer to IMMDevice interface
            # device_ptr is a c_void_p or int, convert to POINTER(IMMDevice)
            if isinstance(device_ptr, int):
                device_ptr = ctypes.c_void_p(device_ptr)
            self._device = ctypes.cast(device_ptr, ctypes.POINTER(IMMDevice))

            # Activate IAudioClient
            # comtypes returns a raw c_void_p, cast it to IAudioClient*
            audio_client_ptr = self._device.Activate(
                ctypes.byref(IID_IAudioClient),
                CLSCTX_ALL,
                None,
            )

            # Cast the raw pointer to IAudioClient interface
            if isinstance(audio_client_ptr, int):
                audio_client_ptr = ctypes.c_void_p(audio_client_ptr)
            self._audio_client = ctypes.cast(audio_client_ptr, ctypes.POINTER(IAudioClient))

            # Get mix format
            # comtypes automatically handles out parameters
            format_ptr = self._audio_client.GetMixFormat()

            # format_ptr is a POINTER(WAVEFORMATEX), access via .contents or [0]
            self._wave_format = format_ptr[0] if format_ptr else None
            if not self._wave_format:
                raise RuntimeError("GetMixFormat returned NULL")
            self._sample_rate = self._wave_format.nSamplesPerSec
            self._channels = self._wave_format.nChannels
            self._is_float = self._wave_format.wFormatTag == WAVE_FORMAT_IEEE_FLOAT
            self._frame_size = self._wave_format.nBlockAlign

            self.logger.info(
                "WASAPI format: {}Hz, {}ch, format_tag={}, bits={}, block_align={}, is_float={}",
                self._sample_rate,
                self._channels,
                self._wave_format.wFormatTag,
                self._wave_format.wBitsPerSample,
                self._wave_format.nBlockAlign,
                self._is_float,
            )

            # Initialize audio client in loopback mode
            buffer_duration = 10000000  # 100ms in 100-nanosecond units
            hr = self._audio_client.Initialize(
                AUDCLNT_SHAREMODE_SHARED,
                AUDCLNT_STREAMFLAGS_LOOPBACK,
                buffer_duration,
                0,
                format_ptr,
                None,
            )
            if hr != 0:
                raise RuntimeError(f"IAudioClient.Initialize failed: {hr:08x}")

            # Get capture client
            # comtypes returns a raw c_void_p, cast it to IAudioCaptureClient*
            capture_client_ptr = self._audio_client.GetService(
                ctypes.byref(IID_IAudioCaptureClient),
            )

            # Cast the raw pointer to IAudioCaptureClient interface
            if isinstance(capture_client_ptr, int):
                capture_client_ptr = ctypes.c_void_p(capture_client_ptr)
            self._capture_client = ctypes.cast(
                capture_client_ptr, ctypes.POINTER(IAudioCaptureClient)
            )

            # Start capture
            hr = self._audio_client.Start()
            if hr != 0:
                raise RuntimeError(f"IAudioClient.Start failed: {hr:08x}")

            self._running = True

            # Start capture thread
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()

            self.logger.info("✓ WASAPI loopback capture started successfully")

        except Exception as exc:
            self.logger.exception("✗ FAILED: Pure Python WASAPI capture failed - {}", exc)
            self.logger.error("Full WASAPI error traceback:")
            import traceback
            self.logger.error("\n{}", traceback.format_exc())
            self.stop()
            raise

    def stop(self) -> None:
        """Stop WASAPI loopback capture."""
        if not self._running:
            return

        self._running = False

        try:
            if self._audio_client:
                self._audio_client.Stop()
        except Exception:
            pass

        if self._thread:
            self._thread.join(timeout=1.0)

        # Release COM objects
        self._capture_client = None
        self._audio_client = None
        self._device = None
        self._device_enumerator = None

        # Uninitialize COM
        try:
            import comtypes

            comtypes.CoUninitialize()
        except Exception:
            pass

        self.logger.info("WASAPI loopback capture stopped")

    def _capture_loop(self) -> None:
        """Main capture loop running in background thread."""
        # Initialize COM for this thread
        try:
            import comtypes

            comtypes.CoInitialize()
        except Exception:
            pass

        try:
            while self._running:
                # Get next packet size
                # comtypes returns the output value directly
                packet_length_val = self._capture_client.GetNextPacketSize()

                while packet_length_val > 0:
                    # Get buffer - comtypes returns tuple of output parameters
                    data_ptr, num_frames_val, flags_val, device_pos, qpc_pos = (
                        self._capture_client.GetBuffer()
                    )

                    if num_frames_val > 0:
                        # Read audio data
                        if flags_val & AUDCLNT_BUFFERFLAGS_SILENT:
                            # Silent buffer - create zeros and reshape
                            samples = np.zeros(
                                num_frames_val * self._channels, dtype=np.float32
                            ).reshape(num_frames_val, self._channels)
                        else:
                            # Read data from pointer
                            # Calculate total samples: frames * channels
                            total_samples = num_frames_val * self._channels
                            
                            # Calculate bytes needed based on ACTUAL format
                            # WASAPI loopback ALWAYS outputs float32 (4 bytes per sample)
                            # regardless of what wFormatTag says
                            bytes_per_sample = 4  # float32
                            total_bytes = total_samples * bytes_per_sample

                            # Access pointer data
                            try:
                                # data_ptr might be an integer address or a pointer
                                if isinstance(data_ptr, int):
                                    ptr_addr = data_ptr
                                elif hasattr(data_ptr, "contents"):
                                    ptr_addr = ctypes.addressof(data_ptr.contents)
                                elif hasattr(data_ptr, "value"):
                                    ptr_addr = data_ptr.value
                                else:
                                    ptr_addr = ctypes.cast(data_ptr, ctypes.c_void_p).value
                                
                                buffer_type = ctypes.c_ubyte * total_bytes
                                buffer = buffer_type.from_address(ptr_addr)
                                buffer_bytes = bytes(buffer)
                            except Exception as exc:
                                self.logger.debug("Failed to read buffer: {}", exc)
                                # Release buffer and continue
                                try:
                                    self._capture_client.ReleaseBuffer(num_frames_val)
                                except Exception:
                                    pass
                                break

                            # Convert to numpy based on format
                            # IMPORTANT: WASAPI loopback ALWAYS outputs float32, regardless of wFormatTag
                            # This is a quirk of loopback mode
                            samples = np.frombuffer(
                                buffer_bytes, dtype=np.float32
                            ).copy()
                            
                            # Initialize/increment sample counter
                            if hasattr(self, '_sample_count'):
                                self._sample_count += 1
                            else:
                                self._sample_count = 1
                            
                            # Log first buffer to verify format
                            if self._sample_count == 1:
                                self.logger.info(
                                    "First buffer raw values (first 10): {}",
                                    samples[:10] if len(samples) >= 10 else samples
                                )
                            
                            if self._sample_count <= 5:  # Log first 5 buffers
                                self.logger.info(
                                    "WASAPI buffer #{}: {} samples, format={}, min={:.6f}, max={:.6f}, mean_abs={:.6f}",
                                    self._sample_count,
                                    len(samples),
                                    "float32" if self._is_float else "int16->float32",
                                    samples.min(),
                                    samples.max(),
                                    np.abs(samples).mean(),
                                )

                            # Reshape to frames x channels
                            # Verify the size matches before reshaping
                            expected_size = num_frames_val * self._channels
                            if len(samples) != expected_size:
                                self.logger.warning(
                                    "Sample size mismatch: got {} samples, expected {} (frames={}, channels={})",
                                    len(samples), expected_size, num_frames_val, self._channels
                                )
                                # Trim or pad to match expected size
                                if len(samples) > expected_size:
                                    samples = samples[:expected_size]
                                else:
                                    samples = np.pad(samples, (0, expected_size - len(samples)))
                            
                            samples = samples.reshape(num_frames_val, self._channels)

                        # Mix to mono if stereo
                        if self._channels > 1:
                            # Check if samples is 2D before mixing
                            if samples.ndim == 2:
                                # Log before mixing
                                if self._sample_count <= 5:
                                    self.logger.info(
                                        "Mixing stereo to mono: shape={}, channels={}",
                                        samples.shape,
                                        self._channels,
                                    )
                                samples = samples.mean(axis=1)
                            elif samples.ndim == 1:
                                # Already 1D, just ensure it's the right size
                                # This shouldn't happen, but handle it gracefully
                                expected_mono_size = num_frames_val
                                if len(samples) == num_frames_val * self._channels:
                                    # Reshape and mix
                                    samples = samples.reshape(num_frames_val, self._channels).mean(axis=1)
                                elif len(samples) != expected_mono_size:
                                    self.logger.warning("Unexpected 1D sample size: {}", len(samples))
                                    samples = samples[:expected_mono_size]  # Trim to expected size

                        # Log after mono conversion
                        if self._sample_count <= 5:
                            self.logger.info(
                                "After mono conversion: {} samples, min={:.6f}, max={:.6f}",
                                len(samples),
                                samples.min(),
                                samples.max(),
                            )

                        # Resample if needed (DISABLED - resampling small chunks causes distortion)
                        if not self._disable_resampling and self._sample_rate != self.target_rate:
                            pre_resample_len = len(samples)
                            samples = self._resample(samples, self._sample_rate)
                            if self._sample_count <= 5:
                                self.logger.info(
                                    "Resampled: {} -> {} samples ({}Hz -> {}Hz), min={:.6f}, max={:.6f}",
                                    pre_resample_len,
                                    len(samples),
                                    self._sample_rate,
                                    self.target_rate,
                                    samples.min(),
                                    samples.max(),
                                )
                        elif self._sample_count <= 5 and self._sample_rate != self.target_rate:
                            self.logger.info(
                                "Skipping per-chunk resampling (keeps native {}Hz to avoid distortion)",
                                self._sample_rate,
                            )

                        # Call callback
                        if self.callback:
                            try:
                                self.callback(samples)
                            except Exception as exc:
                                self.logger.exception("Callback error: {}", exc)

                    # Release buffer
                    self._capture_client.ReleaseBuffer(num_frames_val)

                    # Get next packet size
                    packet_length_val = self._capture_client.GetNextPacketSize()

                # Small sleep to avoid busy loop
                time.sleep(0.01)

        except Exception as exc:
            self.logger.exception("Capture loop error: {}", exc)
            self._running = False
        finally:
            # Uninitialize COM for this thread
            try:
                import comtypes

                comtypes.CoUninitialize()
            except Exception:
                pass

    def _resample(self, samples: np.ndarray, source_rate: int) -> np.ndarray:
        """Resample audio using librosa."""
        try:
            import librosa

            return librosa.resample(
                samples, orig_sr=source_rate, target_sr=self.target_rate
            )
        except ImportError:
            # Fallback: simple linear interpolation (not ideal but works)
            self.logger.warning("librosa not available, using simple resampling")
            ratio = self.target_rate / source_rate
            indices = np.linspace(0, len(samples) - 1, int(len(samples) * ratio))
            return np.interp(indices, np.arange(len(samples)), samples)
