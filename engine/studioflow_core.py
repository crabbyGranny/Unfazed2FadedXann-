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


# ------------------------------------------------------------------------------
# Plugin base and Micro-Modules (VST-like)
# ------------------------------------------------------------------------------
class Plugin:
    """
    Base class for all plugins.
    """

    def __init__(self, name: str):
        self.name = name
        self.enabled = True

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """
        Process audio buffer (channels, frames)
        """
        if not self.enabled:
            return audio
        return audio


class SaturationPlugin(Plugin):
    """
    Analog-style saturation using soft clipping/tanh with adjustable drive.
    """

    def __init__(self, drive: float = 0.2, sat_type: str = "Tube"):
        super().__init__("Saturation")
        self.drive = float(np.clip(drive, 0.0, 2.0))
        self.sat_type = sat_type

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if not self.enabled:
            return audio
        x = audio * (1.0 + 10.0 * self.drive)
        if self.sat_type.lower() == "tube":
            y = np.tanh(x)
        else:
            # Soft clip fallback
            y = x / (1.0 + np.abs(x))
        # Subtle output trim to keep levels manageable
        return safe_clip(y * 0.8)


class CompressorPlugin(Plugin):
    """
    Simple feed-forward compressor with RMS detection.
    """

    def __init__(
        self,
        threshold_db: float = -20.0,
        ratio: float = 4.0,
        attack_ms: float = 5.0,
        release_ms: float = 60.0,
        makeup_db: float = 0.0,
        mix: float = 1.0,
    ):
        super().__init__("Compressor")
        self.threshold_db = threshold_db
        self.ratio = ratio
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.makeup_db = makeup_db
        self.mix = float(np.clip(mix, 0.0, 1.0))

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if not self.enabled:
            return audio

        eps = 1e-12
        # Convert to mono for detector (RMS)
        rms = np.sqrt(np.mean(audio**2, axis=0) + eps)
        level_db = 20.0 * np.log10(np.maximum(rms, eps))

        # Gain computer
        over_db = level_db - self.threshold_db
        over_db = np.maximum(over_db, 0.0)
        gain_db = -over_db + over_db / self.ratio
        # Attack/Release smoothing
        alpha_a = math.exp(-1.0 / (0.001 * self.attack_ms * sample_rate))
        alpha_r = math.exp(-1.0 / (0.001 * self.release_ms * sample_rate))
        smoothed = np.zeros_like(gain_db)
        g_prev = 0.0
        for i, g in enumerate(gain_db):
            if g < g_prev:
                # release towards more 0 dB reduction
                g_prev = alpha_r * g_prev + (1 - alpha_r) * g
            else:
                # attack towards more reduction (more negative)
                g_prev = alpha_a * g_prev + (1 - alpha_a) * g
            smoothed[i] = g_prev

        lin_gain = db_to_linear(smoothed + self.makeup_db)
        # Apply per-sample gain to all channels
        wet = audio * lin_gain[np.newaxis, :]
        out = self.mix * wet + (1.0 - self.mix) * audio
        return out


class ParallelCompressorPlugin(CompressorPlugin):
    """
    Parallel compression variant with fixed wet/dry blend for 'glue'.
    """

    def __init__(self, threshold_db: float = -20, ratio: float = 4.0, mix: float = 0.5):
        super().__init__(threshold_db=threshold_db, ratio=ratio, makeup_db=0.0, mix=mix)


class DeEsserPlugin(Plugin):
    """
    Simple de-esser using a dynamic high-band attenuation centered around sibilance (~6-10 kHz).
    """

    def __init__(self, sensitivity: float = 0.8, center_hz: float = 8000.0, q: float = 1.0):
        super().__init__("DeEsser")
        self.sensitivity = float(np.clip(sensitivity, 0.0, 1.0))
        self.center_hz = center_hz
        self.q = q

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if not self.enabled:
            return audio
        # Split high-band via simple first-order high-pass (fallback if scipy unavailable)
        if sp_signal is not None:
            w0 = self.center_hz / (sample_rate / 2.0)
            # 1st order high-pass
            b, a = sp_signal.butter(1, w0, btype="highpass")
            high = sp_signal.lfilter(b, a, audio, axis=1)
        else:
            # naive HP filter
            alpha = 0.9
            high = np.copy(audio)
            for ch in range(audio.shape[0]):
                prev = 0.0
                for i in range(1, audio.shape[1]):
                    high[ch, i] = alpha * (high[ch, i-1] + audio[ch, i] - audio[ch, i-1])
                    prev = high[ch, i]

        # Detect sibilance via RMS of high band
        eps = 1e-12
        rms_high = np.sqrt(np.mean(high**2, axis=0) + eps)
        # Adaptive threshold from percentile
        thr = np.percentile(rms_high, 85)
        # Gain reduction curve
        over = np.maximum(rms_high - thr, 0.0)
        # Map to 0..1
        over_norm = over / (over.max() + eps)
        reduction_db = -12.0 * (over_norm * self.sensitivity)
        lin = db_to_linear(reduction_db)
        # Apply inverse gain to high band only
        out = audio - high + (high * lin[np.newaxis, :])
        return out


class StereoWidthPlugin(Plugin):
    """
    Mid/Side stereo width adjustment.
    amount: 0 -> mono, 1 -> original, >1 -> wider
    """

    def __init__(self, amount: float = 1.15):
        super().__init__("StereoWidth")
        self.amount = float(np.clip(amount, 0.0, 2.0))

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if not self.enabled:
            return audio
        if audio.shape[0] == 1:
            return audio  # mono unaffected
        L, R = audio[0], audio[1]
        M = 0.5 * (L + R)
        S = 0.5 * (L - R)
        S *= self.amount
        L2 = M + S
        R2 = M - S
        return np.vstack([L2, R2])


class NoiseGatePlugin(Plugin):
    """
    Simple downward expander/noise gate for input cleanliness.
    """

    def __init__(self, threshold_db: float = -50.0, ratio: float = 2.0, attack_ms: float = 5.0, release_ms: float = 80.0):
        super().__init__("NoiseGate")
        self.threshold_db = threshold_db
        self.ratio = ratio
        self.attack_ms = attack_ms
        self.release_ms = release_ms

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if not self.enabled:
            return audio
        eps = 1e-12
        rms = np.sqrt(np.mean(audio**2, axis=0) + eps)
        level_db = 20.0 * np.log10(np.maximum(rms, eps))
        below = np.maximum(self.threshold_db - level_db, 0.0)
        reduction_db = below * (self.ratio - 1.0)
        # Smooth
        alpha_a = math.exp(-1.0 / (0.001 * self.attack_ms * sample_rate))
        alpha_r = math.exp(-1.0 / (0.001 * self.release_ms * sample_rate))
        smoothed = np.zeros_like(reduction_db)
        g_prev = 0.0
        for i, g in enumerate(reduction_db):
            if g < g_prev:
                g_prev = alpha_r * g_prev + (1 - alpha_r) * g
            else:
                g_prev = alpha_a * g_prev + (1 - alpha_a) * g
            smoothed[i] = g_prev
        lin = db_to_linear(-smoothed)
        return audio * lin[np.newaxis, :]


# ------------------------------------------------------------------------------
# "The Logic-Chain": Deep-Link Vocal Strip and 8-slot chain
# ------------------------------------------------------------------------------
class VocalStrip(Plugin):
    """
    Non-destructive vocal strip with micro-modules.
    Chain: Saturation -> Parallel Compression -> De-Esser -> Stereo Width
    """

    def __init__(self, drive: float = 0.2, parallel_threshold: float = -20.0, parallel_ratio: float = 4.0,
                 deesser_sensitivity: float = 0.8, stereo_amount: float = 1.15):
        super().__init__("VocalStrip")
        self.sat = SaturationPlugin(drive=drive, sat_type="Tube")
        self.par_comp = ParallelCompressorPlugin(threshold_db=parallel_threshold, ratio=parallel_ratio, mix=0.5)
        self.deesser = DeEsserPlugin(sensitivity=deesser_sensitivity)
        self.stereo = StereoWidthPlugin(amount=stereo_amount)

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if not self.enabled:
            return audio
        x = self.sat.process(audio, sample_rate)
        x = self.par_comp.process(x, sample_rate)
        x = self.deesser.process(x, sample_rate)
        x = self.stereo.process(x, sample_rate)
        return x


class PluginChain:
    """
    8-slot plugin chain per track. Slots can be None.
    """

    def __init__(self, slots: int = 8):
        self.slots: List[Optional[Plugin]] = [None] * slots

    def set_plugin(self, index: int, plugin: Optional[Plugin]) -> None:
        if index < 0 or index >= len(self.slots):
            raise IndexError("Plugin slot out of range")
        self.slots[index] = plugin

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        x = audio
        for p in self.slots:
            if p is not None and p.enabled:
                x = p.process(x, sample_rate)
        return x


# ------------------------------------------------------------------------------
# Tracks, Mixer, Freeze-Track (background), and Project Model
# ------------------------------------------------------------------------------
@dataclass
class Track:
    name: str
    is_vocal: bool = False
    clips: List[AudioClip] = field(default_factory=list)
    vocal_strip: VocalStrip = field(default_factory=VocalStrip)
    chain: PluginChain = field(default_factory=PluginChain)
    muted: bool = False
    solo: bool = False
    gain_db: float = 0.0
    frozen: bool = False
    _frozen_audio: Optional[np.ndarray] = None
    _frozen_sr: Optional[int] = None
    _freeze_lock: threading.Lock = field(default_factory=threading.Lock)

    def add_clip(self, clip: AudioClip) -> None:
        self.clips.append(clip)

    def render(self, t0: float, t1: float, sample_rate: int) -> np.ndarray:
        """
        Render track audio in window [t0, t1)
        """
        out_len = max(0, int(round((t1 - t0) * sample_rate)))
        if out_len == 0:
            return np.zeros((2, 0), dtype=np.float32)

        if self.muted:
            return np.zeros((2, out_len), dtype=np.float32)

        if self.frozen and self._frozen_audio is not None and self._frozen_sr == sample_rate:
            # Trim window from frozen buffer (assumed aligned from t=0)
            start = int(round(t0 * sample_rate))
            end = start + out_len
            frozen = self._frozen_audio
            if end > frozen.shape[1]:
                pad = np.zeros((frozen.shape[0], end - frozen.shape[1]), dtype=frozen.dtype)
                frozen = np.hstack([frozen, pad])
            x = frozen[:, start:end]
            return x * db_to_linear(self.gain_db)

        # Sum clips
        acc = np.zeros((2, out_len), dtype=np.float32)
        for clip in self.clips:
            c = clip.render_window(t0, t1, sample_rate).astype(np.float32)
            # Ensure stereo
            c = ensure_channels(c, 2)
            acc[:, :c.shape[1]] += c

        # Apply vocal strip if vocal track
        if self.is_vocal and self.vocal_strip is not None:
            acc = self.vocal_strip.process(acc, sample_rate)

        # Apply 8-slot chain
        acc = self.chain.process(acc, sample_rate)

        # Track gain
        acc *= db_to_linear(self.gain_db)
        return safe_clip(acc)

    def freeze(self, duration_sec: float, sample_rate: int) -> None:
        """
        Freeze the track: render entire timeline [0, duration_sec) with chain, store result.
        """
        with self._freeze_lock:
            if self.frozen:
                return
            logger.info(f"Freezing track '{self.name}'...")
            try:
                x = self.render(0.0, duration_sec, sample_rate).astype(np.float32)
                self._frozen_audio = x
                self._frozen_sr = sample_rate
                self.frozen = True
                logger.info(f"Track '{self.name}' frozen. Length={x.shape[1]/sample_rate:.2f}s")
            except Exception as exc:
                logger.exception(f"Failed to freeze track '{self.name}': {exc}")

    def unfreeze(self) -> None:
        with self._freeze_lock:
            self.frozen = False
            self._frozen_audio = None
            self._frozen_sr = None


class FreezeManager:
    """
    Background manager to freeze heavy tracks automatically (Freeze-Track Technology).
    """

    def __init__(self, threshold_plugins: int = 5):
        self.threshold_plugins = threshold_plugins
        self._queue: "queue.Queue[Tuple[Track, float, int]]" = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._running = False

    def start(self):
        if not self._running:
            self._running = True
            self._thread.start()

    def stop(self):
        self._running = False

    def schedule_freeze(self, track: Track, duration_sec: float, sample_rate: int) -> None:
        # Heuristic: if chain is heavy, schedule
        used = sum(1 for p in track.chain.slots if p is not None and p.enabled)
        if track.is_vocal:
            used += 2  # vocal strip weight
        if used >= self.threshold_plugins and not track.frozen:
            self._queue.put((track, duration_sec, sample_rate))

    def _worker(self):
        while self._running:
            try:
                track, dur, sr = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                track.freeze(dur, sr)
            except Exception as exc:
                logger.exception(f"Freeze worker error: {exc}")


class Mixer:
    """
    Handles track summing with solo/mute logic and master processing.
    """

    def __init__(self):
        self.tracks: List[Track] = []
        self.master_chain = PluginChain()
        self.master_gain_db: float = 0.0

    def add_track(self, track: Track) -> None:
        self.tracks.append(track)

    def render(self, t0: float, t1: float, sample_rate: int) -> np.ndarray:
        out_len = max(0, int(round((t1 - t0) * sample_rate)))
        if out_len == 0:
            return np.zeros((2, 0), dtype=np.float32)

        any_solo = any(tr.solo for tr in self.tracks)
        acc = np.zeros((2, out_len), dtype=np.float32)
        for tr in self.tracks:
            if any_solo and not tr.solo:
                continue
            x = tr.render(t0, t1, sample_rate)
            acc[:, :x.shape[1]] += x

        # Master chain and gain
        acc = self.master_chain.process(acc, sample_rate)
        acc *= db_to_linear(self.master_gain_db)
        return safe_clip(acc)


@dataclass
class Project:
    """
    Project model: sample rate, tempo (for future MIDI), and mixer.
    """
    name: str
    sample_rate: int = 48000
    tempo_bpm: float = 120.0
    mixer: Mixer = field(default_factory=Mixer)
    duration_sec: float = 0.0  # Project timeline end (max of clips)

    def update_duration_from_clips(self):
        max_end = 0.0
        for tr in self.mixer.tracks:
            for c in tr.clips:
                max_end = max(max_end, c.start_time + c.duration_sec)
        self.duration_sec = max_end


# ------------------------------------------------------------------------------
# Drivers: Real-time Low-Latency Engine (callback-based) and Offline Rendering
# ------------------------------------------------------------------------------
class LowLatencyDriver:
    """
    Attempt low-latency real-time IO (ASIO-like behavior). Falls back safely.
    """
    def __init__(self, project: Project, buffer_ms: float = 5.3, blocksize: Optional[int] = None):
        self.project = project
        self.buffer_ms = buffer_ms
        self.blocksize = blocksize
        self._t = 0.0
        self._running = False
        self._stream = None

    def start(self):
        if sd is None:
            logger.warning("sounddevice is not available; real-time output disabled. Running null loop.")
            self._running = True
            threading.Thread(target=self._null_loop, daemon=True).start()
            return

        try:
            sr = self.project.sample_rate
            if self.blocksize is None:
                self.blocksize = max(64, int(sr * self.buffer_ms / 1000.0))

            def callback(outdata, frames, time_info, status):
                if status:
                    logger.debug(f"Audio status: {status}")
                t0 = self._t
                t1 = t0 + frames / float(sr)
                buf = self.project.mixer.render(t0, t1, sr)
                # Ensure length
                if buf.shape[1] < frames:
                    pad = np.zeros((buf.shape[0], frames - buf.shape[1]), dtype=buf.dtype)
                    buf = np.hstack([buf, pad])
                outdata[:] = to_frames_channels(buf[:, :frames])
                self._t = t1

            self._stream = sd.OutputStream(
                samplerate=self.project.sample_rate,
                blocksize=self.blocksize,
                channels=2,
                dtype='float32',
                callback=callback,
                latency='low'
            )
            self._stream.start()
            self._running = True
            logger.info(f"LowLatencyDriver started: sr={self.project.sample_rate}, block={self.blocksize}")
        except Exception as exc:
            logger.exception(f"Failed to start real-time driver: {exc}")
            self._running = False

    def stop(self):
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _null_loop(self):
        """
        Fallback loop to exercise processing without sound output.
        """
        sr = self.project.sample_rate
        frames = max(64, int(sr * self.buffer_ms / 1000.0))
        while self._running:
            t0 = self._t
            t1 = t0 + frames / float(sr)
            _ = self.project.mixer.render(t0, t1, sr)
            self._t = t1
            # Sleep roughly buffer duration
            time.sleep(max(0.0, frames / float(sr) * 0.9))


# ------------------------------------------------------------------------------
# Export Engine: WAV (32-bit float / up to 96k), Stems, Cloud Mastering
# ------------------------------------------------------------------------------
class ExportError(Exception):
    pass


class ExportEngine:
    """
    Supports:
    - WAV (Lossless): 44.1kHz up to 96kHz, 32-bit float
    - Stems export: each track individually
    - Cloud Mastering: sends master to server (optional), local mastering fallback
    """

    def __init__(self, project: Project):
        self.project = project

    def export_master(self, path: str, sample_rate: int = 96000) -> str:
        """
        Render full project to path at target sample_rate, 32-bit float WAV if possible.
        """
        if sf is None:
            raise ExportError("soundfile is not available. Cannot write WAV.")
        self.project.update_duration_from_clips()
        duration = max(self.project.duration_sec, 0.001)
        logger.info(f"Exporting master: {path} at {sample_rate} Hz, duration {duration:.2f}s")
        src_sr = self.project.sample_rate
        audio = self.project.mixer.render(0.0, duration, src_sr)
        audio = resample_audio(audio, src_sr, sample_rate)
        # Write 32-bit float WAV
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            sf.write(path, to_frames_channels(audio), samplerate=sample_rate, subtype="FLOAT")
        except Exception as exc:
            raise ExportError(f"Failed to export master: {exc}") from exc
        return path

    def export_stems(self, folder: str, sample_rate: int = 96000) -> Dict[str, str]:
        """
        Render each track to individual files.
        """
        if sf is None:
            raise ExportError("soundfile is not available. Cannot write WAV.")
        self.project.update_duration_from_clips()
        duration = max(self.project.duration_sec, 0.001)
        os.makedirs(folder, exist_ok=True)
        outputs = {}
        logger.info(f"Exporting stems to {folder} at {sample_rate} Hz")
        for tr in self.project.mixer.tracks:
            audio = tr.render(0.0, duration, self.project.sample_rate)
            audio = resample_audio(audio, self.project.sample_rate, sample_rate)
            file_path = os.path.join(folder, f"{tr.name.replace(' ', '_')}.wav")
            try:
                sf.write(file_path, to_frames_channels(audio), samplerate=sample_rate, subtype="FLOAT")
                outputs[tr.name] = file_path
            except Exception as exc:
                logger.exception(f"Failed to export stem for {tr.name}: {exc}")
        return outputs

    def cloud_master(self, input_wav: str, output_wav: str, endpoint: Optional[str] = None) -> str:
        """
        Send the mix to a cloud mastering service. If not available, apply local chain:
        - Broad EQ tilt
        - Bus compression
        - Brickwall limiting (soft)
        """
        if endpoint and requests is not None:
            try:
                with open(input_wav, "rb") as f:
                    files = {"file": (os.path.basename(input_wav), f, "audio/wav")}
                    r = requests.post(endpoint, files=files, timeout=60)
                    r.raise_for_status()
                with open(output_wav, "wb") as f:
                    f.write(r.content)
                logger.info("Cloud mastering completed.")
                return output_wav
            except Exception as exc:
                logger.warning(f"Cloud mastering failed, using local fallback: {exc}")

        # Local fallback mastering
        if sf is None:
            raise ExportError("soundfile is not available. Cannot perform local mastering fallback.")
        data, sr = sf.read(input_wav, dtype="float32", always_2d=True)
        x = to_channels_frames(data.T)  # shape (channels, frames)

        # Broad tilt EQ: slight high-shelf
        def high_shelf(audio: np.ndarray, gain_db: float = 1.5, freq: float = 6000.0):
            if sp_signal is None:
                return audio * db_to_linear(gain_db)
            w0 = freq / (sr / 2.0)
            b, a = sp_signal.iirfilter(2, w0, btype="high", ftype="butter")
            hi = sp_signal.lfilter(b, a, audio, axis=1)
            return audio + (db_to_linear(gain_db) - 1.0) * hi

        x = high_shelf(x, gain_db=1.5)

        # Bus glue (gentle parallel comp)
        comp = ParallelCompressorPlugin(threshold_db=-18.0, ratio=2.0, mix=0.3)
        x = comp.process(x, sr)

        # Soft limiter
        peak = np.max(np.abs(x)) + 1e-9
        if peak > 0.98:
            x /= (peak / 0.98)
        x = safe_clip(x)

        sf.write(output_wav, to_frames_channels(x), samplerate=sr, subtype="FLOAT")
        logger.info("Local mastering completed.")
        return output_wav


# ------------------------------------------------------------------------------
# Resource Management: CPU-aware freeze scheduling
# ------------------------------------------------------------------------------
class ResourceManager:
    """
    Monitors heuristics and triggers freeze to prevent UI lag.
    """
    def __init__(self, project: Project, freeze_manager: FreezeManager):
        self.project = project
        self.freeze_manager = freeze_manager

    def evaluate_and_optimize(self):
        """
        Heuristic: if project has many active plugins, schedule freezers.
        """
        self.project.update_duration_from_clips()
        dur = self.project.duration_sec
        sr = self.project.sample_rate
        for tr in self.project.mixer.tracks:
            self.freeze_manager.schedule_freeze(tr, dur, sr)


# ------------------------------------------------------------------------------
# Precision Pointer: virtual mouse for one-handed precision editing
# ------------------------------------------------------------------------------
class PrecisionPointer:
    """
    Smooths and scales touch deltas to high-precision pointer motion.
    """
    def __init__(self, sensitivity: float = 1.0, acceleration: float = 0.2, smoothing: float = 0.5):
        self.sensitivity = sensitivity
        self.acceleration = acceleration
        self.smoothing = float(np.clip(smoothing, 0.0, 0.99))
        self._vx = 0.0
        self._vy = 0.0

    def update(self, dx: float, dy: float) -> Tuple[float, float]:
        """
        Input: raw touch delta (dx, dy). Output: high-precision pointer delta.
        """
        speed = math.sqrt(dx * dx + dy * dy)
        accel_gain = 1.0 + self.acceleration * speed
        tx = dx * self.sensitivity * accel_gain
        ty = dy * self.sensitivity * accel_gain
        # One-pole low-pass smoothing on velocity
        self._vx = self.smoothing * self._vx + (1.0 - self.smoothing) * tx
        self._vy = self.smoothing * self._vy + (1.0 - self.smoothing) * ty
        return self._vx, self._vy


# ------------------------------------------------------------------------------
# Onboarding: "The 60-Second Producer" Tutorial (logic only)
# ------------------------------------------------------------------------------
class TutorialEngine:
    """
    Shadow-teaches PC workflow via guided steps.
    """
    def __init__(self, project: Project):
        self.project = project
        self.step = 0
        self.steps = [
            "Do you have a beat or are we making one?",
            "Ghost Hand: Drag a sample into the Step Sequencer.",
            "Vocal Setup: Checking mic environment... Activating Noise Gate if noisy.",
            "Desktop Hack: Use bottom shortcut to switch Mixer/Playlist/Samples (F5/F6/F7 style).",
        ]
        self.noise_gate = NoiseGatePlugin(threshold_db=-45.0)

    def current_instruction(self) -> str:
        return self.steps[self.step] if self.step < len(self.steps) else "Tutorial complete."

    def next(self):
        self.step += 1

    def auto_noise_gate_on_vocal(self):
        for tr in self.project.mixer.tracks:
            if tr.is_vocal:
                # Insert as first in chain if empty
                for i in range(len(tr.chain.slots)):
                    if tr.chain.slots[i] is None:
                        tr.chain.set_plugin(i, self.noise_gate)
                        logger.info(f"Noise gate auto-enabled on vocal track '{tr.name}'")
                        return


# ------------------------------------------------------------------------------
# Clean Vocal Industry Chain (as per prompt)
# ------------------------------------------------------------------------------
class IndustryVocalChain(Plugin):
    """
    "Perfect Vocal" industry preset chain:
    1) Analog Saturation
    2) Parallel Compression
    3) AI De-Esser
    4) Spatial Imaging
    """
    def __init__(self):
        super().__init__("IndustryVocalChain")
        self.sat = SaturationPlugin(drive=0.2, sat_type="Tube")
        self.par = ParallelCompressorPlugin(threshold_db=-20.0, ratio=4.0, mix=0.5)
        self.deesser = DeEsserPlugin(sensitivity=0.8)
        self.stereo = StereoWidthPlugin(amount=1.15)

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        x = self.sat.process(audio, sample_rate)
        x = self.par.process(x, sample_rate)
        x = self.deesser.process(x, sample_rate)
        x = self.stereo.process(x, sample_rate)
        return x


# ------------------------------------------------------------------------------
# File Management: project folders and sample hierarchy
# ------------------------------------------------------------------------------
class FileManager:
    """
    PC-style folder hierarchy for samples and projects.
    """
    def __init__(self, root: str = "./StudioFlow"):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def ensure_project_folder(self, name: str) -> str:
        path = os.path.join(self.root, "Projects", name)
        os.makedirs(path, exist_ok=True)
        return path

    def samples_folder(self) -> str:
        path = os.path.join(self.root, "Samples")
        os.makedirs(path, exist_ok=True)
        return path


# ------------------------------------------------------------------------------
# Example usage and small test harness
# ------------------------------------------------------------------------------
def _generate_test_tone(duration: float, sr: int, freq: float = 220.0, stereo: bool = True) -> np.ndarray:
    t = np.arange(int(duration * sr)) / float(sr)
    x = 0.15 * np.sin(2 * math.pi * freq * t).astype(np.float32)
    if stereo:
        return np.vstack([x, x])
    else:
        return np.expand_dims(x, 0)


def example_usage():
    """
    Demonstrates:
    - Project creation
    - Adding a vocal track and a beat track
    - Applying Industry Vocal Chain
    - Freeze-Track optimization
    - Export master (96k/32-bit float) and stems
    - Local cloud mastering fallback
    - Precision pointer utility
    Note: For reproducibility, uses synthesized tones instead of real audio.
    """
    # Create project
    project = Project(name="StudioFlow_Demo", sample_rate=48000)

    # File manager
    fm = FileManager()
    proj_folder = fm.ensure_project_folder(project.name)

    # Tracks
    vocal = Track(name="Lead Vocal", is_vocal=True)
    beat = Track(name="Beat")

    # Add test clips (3 seconds)
    vocal_clip = AudioClip(audio=_generate_test_tone(3.0, project.sample_rate, freq=330.0),
                           sample_rate=project.sample_rate, start_time=0.0, gain_db=-2.0)
    beat_clip = AudioClip(audio=_generate_test_tone(3.0, project.sample_rate, freq=55.0),
                          sample_rate=project.sample_rate, start_time=0.0, gain_db=0.0)

    vocal.add_clip(vocal_clip)
    beat.add_clip(beat_clip)

    # Apply Industry Vocal Chain via the track's vocal strip and plugin chain
    # Here we put IndustryVocalChain at slot 0 to emulate "Perfect Vocal" button
    vocal.chain.set_plugin(0, IndustryVocalChain())

    # Add tracks to mixer
    project.mixer.add_track(beat)
    project.mixer.add_track(vocal)

    # Tutorial: auto-enable noise gate if environment is noisy (simulated)
    tutorial = TutorialEngine(project)
    tutorial.auto_noise_gate_on_vocal()

    # Start Freeze Manager and Resource Manager
    freeze_mgr = FreezeManager(threshold_plugins=3)
    freeze_mgr.start()
    res_mgr = ResourceManager(project, freeze_mgr)
    res_mgr.evaluate_and_optimize()  # Schedule freezes if needed

    # Start low-latency engine (if sounddevice available) for a quick preview
    driver = LowLatencyDriver(project, buffer_ms=5.3)  # Small buffer for low latency
    driver.start()
    time.sleep(0.25)  # Let it render a few buffers
    driver.stop()

    # Export master and stems
    exporter = ExportEngine(project)
    master_wav = os.path.join(proj_folder, "master_96k.wav")
    try:
        exporter.export_master(master_wav, sample_rate=96000)
        logger.info(f"Master exported: {master_wav}")
    except ExportError as exc:
        logger.warning(f"Export failed: {exc}")

    stems_folder = os.path.join(proj_folder, "stems")
    try:
        stems = exporter.export_stems(stems_folder, sample_rate=96000)
        logger.info(f"Stems exported: {stems}")
    except ExportError as exc:
        logger.warning(f"Stems export failed: {exc}")

    # Cloud mastering (local fallback if no endpoint)
    mastered_wav = os.path.join(proj_folder, "mastered.wav")
    try:
        exporter.cloud_master(master_wav, mastered_wav, endpoint=None)
        logger.info(f"Mastered file: {mastered_wav}")
    except ExportError as exc:
        logger.warning(f"Cloud mastering failed: {exc}")

    # Precision Pointer demo
    pointer = PrecisionPointer(sensitivity=1.0, acceleration=0.25, smoothing=0.6)
    deltas = [(1, 0), (2, 1), (3, 1), (0.5, -1), (-1, -2)]
    smoothed = [pointer.update(dx, dy) for dx, dy in deltas]
    logger.info(f"Precision pointer smoothed deltas: {smoothed}")

    # Clean up freeze manager thread
    freeze_mgr.stop()
    logger.info("Example usage completed.")


if __name__ == "__main__":
    try:
        example_usage()
    except Exception as e:
        logger.exception(f"Fatal error in example usage: {e}")
