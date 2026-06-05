"""
StudioFlow Mobile: Desktop Edition (Core Engine Prototype)

Production-grade Python architecture for a mobile-native DAW core focused on:
- Resource management
- Screen real estate abstractions (not UI-bound, gesture-ready hooks)
- Ultra-low-latency audio processing pipeline design
- Desktop-grade features (multi-slot mixer chain, track freezing, stems export)
- "Clean Vocal" industry preset chain
- Cloud mastering (local fallback)

Notes:
- This module focuses on the engine (audio/DSP) and system orchestration.
- Intended to be embedded under a mobile UI (Flutter/React Native/Kivy) via FFI or IPC.
- Real-time audio device integration is optional and safely degrades if host packages are missing.

Dependencies (optional/auto-detected):
- numpy (required)
- soundfile (recommended for WAV export)
- scipy (recommended for resampling/high-quality filters)
- requests (optional for cloud mastering)
- sounddevice (optional for real-time I/O on desktop)

Author: Staff-level Python Engineer
"""

from __future__ import annotations

import math
import os
import threading
import queue
import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Callable, Dict

# Core dependencies
try:
    import numpy as np
except Exception as exc:
    raise RuntimeError("numpy is required to run the audio engine") from exc

# Optional dependencies for I/O/resampling
try:
    import soundfile as sf
except Exception:
    sf = None  # WAV I/O will degrade

try:
    from scipy import signal as sp_signal
except Exception:
    sp_signal = None  # Resampling/filters will degrade

try:
    import sounddevice as sd
except Exception:
    sd = None  # Real-time I/O will degrade

try:
    import requests
except Exception:
    requests = None  # Cloud mastering call will degrade

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
logger = logging.getLogger("studioflow")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s %(name)s: %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)


# ------------------------------------------------------------------------------
# Utils and Low-level Audio Buffer
# ------------------------------------------------------------------------------
def db_to_linear(db: float) -> float:
    return 10 ** (db / 20.0)


def linear_to_db(lin: float, eps: float = 1e-12) -> float:
    return 20.0 * math.log10(max(lin, eps))


def safe_clip(x: np.ndarray, min_val: float = -1.0, max_val: float = 1.0) -> np.ndarray:
    return np.clip(x, min_val, max_val)


def ensure_channels(audio: np.ndarray, channels: int) -> np.ndarray:
    """
    Ensure array has shape (channels, frames).
    """
    if audio.ndim == 1:
        audio = np.expand_dims(audio, 0)  # (1, frames)
    if audio.shape[0] != channels:
        if audio.shape[0] == 1 and channels == 2:
            # Mono to stereo duplication
            audio = np.vstack([audio, audio])
        else:
            raise ValueError(f"Channel mismatch: expected {channels}, got {audio.shape[0]}")
    return audio


def to_frames_channels(audio: np.ndarray) -> np.ndarray:
    """
    Convert (channels, frames) -> (frames, channels) for writing.
    """
    return np.swapaxes(audio, 0, 1)


def to_channels_frames(audio: np.ndarray) -> np.ndarray:
    """
    Convert (frames, channels) -> (channels, frames).
    """
    return np.swapaxes(audio, 0, 1)


def resample_audio(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """
    Resample audio (channels, frames).
    High-quality if scipy is available; otherwise linear interpolation.
    """
    if src_sr == dst_sr:
        return audio
    channels, frames = audio.shape
    if sp_signal is not None:
        # Use polyphase resampling
        gcd = math.gcd(src_sr, dst_sr)
        up = dst_sr // gcd
        down = src_sr // gcd
        out = []
        for ch in range(channels):
            out.append(sp_signal.resample_poly(audio[ch], up, down))
        # Pad/truncate to consistent length
        min_len = min(map(len, out))
        out = [x[:min_len] for x in out]
        return np.vstack(out)
    else:
        # Fallback linear interpolation
        duration = frames / float(src_sr)
        new_frames = int(round(duration * dst_sr))
        x_old = np.linspace(0.0, 1.0, frames, endpoint=False)
        x_new = np.linspace(0.0, 1.0, new_frames, endpoint=False)
        out = []
        for ch in range(channels):
            out.append(np.interp(x_new, x_old, audio[ch]).astype(audio.dtype))
        return np.vstack(out)


@dataclass
class AudioClip:
    """
    Represents an audio clip on a track timeline.
    """
    audio: np.ndarray  # (channels, frames), float32/float64
    sample_rate: int
    start_time: float  # in seconds
    gain_db: float = 0.0

    def render_window(self, t0: float, t1: float, dst_sr: int) -> np.ndarray:
        """
        Render a time window [t0, t1) to dst_sr
        """
        if t1 <= self.start_time:
            # window before clip
            return np.zeros((self.audio.shape[0], int((t1 - t0) * dst_sr)), dtype=self.audio.dtype)
        if t0 >= self.start_time + self.duration_sec:
            # window after clip
            return np.zeros((self.audio.shape[0], int((t1 - t0) * dst_sr)), dtype=self.audio.dtype)

        # Overlap window in clip coordinates
        clip_t0 = max(0.0, t0 - self.start_time)
        clip_t1 = min(self.duration_sec, t1 - self.start_time)
        if clip_t1 <= clip_t0:
            return np.zeros((self.audio.shape[0], int((t1 - t0) * dst_sr)), dtype=self.audio.dtype)

        # Slice original frames
        src_start = int(round(clip_t0 * self.sample_rate))
        src_end = int(round(clip_t1 * self.sample_rate))
        window = self.audio[:, src_start:src_end]
        # Resample if needed
        if self.sample_rate != dst_sr:
            window = resample_audio(window, self.sample_rate, dst_sr)

        # Place into exact position of [t0, t1)
        out_len = int(round((t1 - t0) * dst_sr))
        out = np.zeros((window.shape[0], out_len), dtype=window.dtype)
        # Compute offset where this window should start inside [t0, t1)
        start_offset = int(round((max(self.start_time, t0) - t0) * dst_sr))
        end_offset = start_offset + window.shape[1]
        end_offset = min(end_offset, out_len)
        out[:, start_offset:end_offset] += window[:, : (end_offset - start_offset)]

        # Apply gain in linear
        out *= db_to_linear(self.gain_db)
        return out

    @property
    def duration_sec(self) -> float:
        return self.audio.shape[1] / float(self.sample_rate)

