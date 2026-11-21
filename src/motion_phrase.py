"""Interpretación temporal del movimiento para RESONANTIA."""
from dataclasses import dataclass
from enum import Enum
from math import isfinite

class MotionPhase(str, Enum):
    STILLNESS = "stillness"
    ATTACK = "attack"
    SUSTAIN = "sustain"
    RELEASE = "release"

@dataclass(frozen=True)
class MotionPhrase:
    phase: MotionPhase
    energy: float
    onset: float
    phase_changed: bool
    elapsed: float

class MotionPhraseDetector:
    """Suavizado, histéresis y permanencia mínima para fases musicales."""
    def __init__(self, attack_threshold=0.24, release_threshold=0.13,
                 still_threshold=0.07, smoothing=0.30,
                 min_phase_seconds=0.18, attack_seconds=0.22,
                 still_seconds=0.65):
        if not 0 <= still_threshold < release_threshold < attack_threshold <= 1:
            raise ValueError("Umbrales inválidos: still < release < attack.")
        if not 0 < smoothing <= 1:
            raise ValueError("smoothing debe estar en (0, 1].")
        self.attack_threshold=attack_threshold
        self.release_threshold=release_threshold
        self.still_threshold=still_threshold
        self.smoothing=smoothing
        self.min_phase_seconds=max(0.0,min_phase_seconds)
        self.attack_seconds=max(0.0,attack_seconds)
        self.still_seconds=max(0.0,still_seconds)
        self.reset()

    def reset(self):
        self.energy=0.0
        self.previous_energy=0.0
        self.phase=MotionPhase.STILLNESS
        self.phase_elapsed=0.0
        self.low_energy_elapsed=0.0

    @staticmethod
    def _unit(value):
        value=float(value)
        if not isfinite(value):
            raise ValueError("La energía debe ser finita.")
        return max(0.0,min(1.0,value))

    def update(self, raw_energy, delta_time):
        raw=self._unit(raw_energy)
        dt=max(0.0,min(float(delta_time),0.25))
        old=self.phase
        self.previous_energy=self.energy
        self.energy += self.smoothing*(raw-self.energy)
        rise=max(0.0,self.energy-self.previous_energy)
        onset=max(0.0,min(1.0,rise/max(dt,0.025)*0.20))
        self.phase_elapsed += dt
        self.low_energy_elapsed = self.low_energy_elapsed+dt if self.energy <= self.still_threshold else 0.0
        eligible=self.phase_elapsed >= self.min_phase_seconds

        if self.phase == MotionPhase.STILLNESS:
            if eligible and self.energy >= self.attack_threshold:
                self.phase=MotionPhase.ATTACK
        elif self.phase == MotionPhase.ATTACK:
            if eligible and self.phase_elapsed >= self.attack_seconds:
                self.phase=MotionPhase.SUSTAIN if self.energy > self.release_threshold else MotionPhase.RELEASE
        elif self.phase == MotionPhase.SUSTAIN:
            if eligible and self.energy < self.release_threshold:
                self.phase=MotionPhase.RELEASE
        elif self.phase == MotionPhase.RELEASE:
            if eligible and self.low_energy_elapsed >= self.still_seconds:
                self.phase=MotionPhase.STILLNESS
            elif eligible and self.energy >= self.attack_threshold:
                self.phase=MotionPhase.ATTACK

        changed=self.phase != old
        if changed:
            self.phase_elapsed=0.0
        return MotionPhrase(self.phase,self.energy,onset,changed,self.phase_elapsed)
