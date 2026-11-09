"""Reloj musical común: todos los instrumentos comparten BPM y compás."""
import time

class MusicClock:
    def __init__(self, bpm=122, beats_per_bar=4):
        if bpm <= 0 or beats_per_bar <= 0:
            raise ValueError("BPM y beats_per_bar deben ser positivos.")
        self.bpm = float(bpm)
        self.beats_per_bar = int(beats_per_bar)
        self.seconds_per_beat = 60.0 / self.bpm
        self.bar_duration = self.seconds_per_beat * self.beats_per_bar
        self.started_at = None
        self.bar_index = 0
    def start(self, at=None):
        self.started_at = time.monotonic() if at is None else at
        self.bar_index = 0
    def bar_start(self, index=None):
        if self.started_at is None:
            raise RuntimeError("El reloj todavía no ha iniciado.")
        i = self.bar_index if index is None else index
        return self.started_at + i * self.bar_duration
    def next_bar(self):
        self.bar_index += 1
        return self.bar_start()
