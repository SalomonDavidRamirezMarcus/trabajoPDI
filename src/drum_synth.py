"""Percusión sintetizada por osciladores y ruido; no usa samples externos."""
import numpy as np

class DrumSynth:
    def __init__(self, sample_rate=44100):
        self.sample_rate = int(sample_rate)
        self.voices = []
    def trigger(self, kind, velocity=90):
        if kind not in ("kick", "snare", "hihat"):
            raise ValueError(f"Tipo de percusión desconocido: {kind}")
        self.voices.append({"kind": kind, "age": 0, "velocity": max(1, min(127, int(velocity))) / 127.0,
                            "phase": 0.0, "noise_state": np.random.default_rng().uniform(-1, 1)})
    def render(self, frames):
        out = np.zeros(int(frames), dtype=np.float32)
        alive = []
        for voice in self.voices:
            age = voice["age"]
            t = (age + np.arange(frames, dtype=np.float64)) / self.sample_rate
            amp = voice["velocity"]
            if voice["kind"] == "kick":
                duration = 0.42
                freq = 42.0 + 105.0 * np.exp(-t * 22.0)
                phase = 2 * np.pi * np.cumsum(freq) / self.sample_rate
                signal = np.sin(phase) * np.exp(-t * 9.5)
            elif voice["kind"] == "snare":
                duration = 0.24
                rng = np.random.default_rng(1234 + age)
                noise = rng.uniform(-1, 1, int(frames))
                tone = np.sin(2 * np.pi * 185 * t)
                signal = (0.78 * noise + 0.22 * tone) * np.exp(-t * 19.0)
            else:
                duration = 0.12
                rng = np.random.default_rng(5678 + age)
                noise = rng.uniform(-1, 1, int(frames))
                # Ruido metálico con modulación rápida para un hi-hat brillante.
                metallic = np.sign(np.sin(2 * np.pi * 6200 * t))
                signal = (0.72 * noise + 0.28 * metallic) * np.exp(-t * 38.0)
            out += (signal * amp * 0.32).astype(np.float32)
            voice["age"] += int(frames)
            if voice["age"] / self.sample_rate < duration:
                alive.append(voice)
        self.voices = alive
        return np.clip(out, -1.0, 1.0)
