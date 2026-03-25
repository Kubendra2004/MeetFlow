"""
audio_recorder.py
Records microphone audio during a Google Meet session.
Saves as 16-kHz WAV (speech-quality, ~4x smaller than 44.1kHz).
"""
import os
import threading
import datetime
import numpy as np

try:
    import sounddevice as sd
    import soundfile as sf
    _AUDIO_AVAILABLE = True
except ImportError:
    _AUDIO_AVAILABLE = False
    print("[AudioRecorder] ⚠️  sounddevice/soundfile not installed — recording disabled.")

RECORDINGS_DIR = "recordings"
SAMPLE_RATE    = 16000   # 16 kHz — sufficient for speech; 4x smaller than 44.1kHz
CHANNELS       = 1


class AudioRecorder:
    """Thread-safe audio recorder. Call start() then stop()."""

    def __init__(self):
        self.recording   = False
        self.frames      = []
        self._thread     = None
        self._lock       = threading.Lock()
        self.output_path = None
        os.makedirs(RECORDINGS_DIR, exist_ok=True)

    def start(self, label: str = None):
        """Begin recording to a new WAV file."""
        if not _AUDIO_AVAILABLE:
            return
        if self.recording:
            print("[AudioRecorder] Already recording — ignoring start().")
            return

        ts = label or datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        self.output_path = os.path.join(RECORDINGS_DIR, f"meeting_{ts}.wav")
        self.frames      = []
        self.recording   = True
        self._thread     = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        print(f"[AudioRecorder] 🎙️  Recording started → {self.output_path}")

    def stop(self) -> str | None:
        """
        Stop recording, flush and save the WAV file.
        Returns the saved file path, or None if not recording / no audio.
        """
        if not self.recording:
            return None

        self.recording = False
        if self._thread:
            self._thread.join(timeout=5)

        path = self._save()
        if path:
            print(f"[AudioRecorder] ✅ Saved → {path}")
        return path

    # ── Internal ───────────────────────────────────────────
    def _record_loop(self):
        """Capture mic input in a background thread."""
        def _cb(indata, frames, time_info, status):
            if self.recording:
                with self._lock:
                    self.frames.append(indata.copy())

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                dtype="float32", callback=_cb):
                while self.recording:
                    sd.sleep(200)
        except Exception as e:
            print(f"[AudioRecorder] ❌ Recording error: {e}")
            self.recording = False

    def _save(self) -> str | None:
        """Write buffered frames to disk."""
        with self._lock:
            if not self.frames:
                print("[AudioRecorder] ⚠️  No audio captured — nothing saved.")
                return None
            data = np.concatenate(self.frames, axis=0)

        try:
            sf.write(self.output_path, data, SAMPLE_RATE)
            return self.output_path
        except Exception as e:
            print(f"[AudioRecorder] ❌ Failed to save file: {e}")
            return None
