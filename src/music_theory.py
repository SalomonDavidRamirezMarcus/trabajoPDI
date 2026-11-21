"""
RESONANTIA - Motor de teoría musical
Gestiona tonalidad, escalas, acordes, progresiones y selección de notas MIDI.

Configuración inicial:
- Estilo: electrónica melódica bailable.
- Tonalidad: Do mayor.
- Tempo: 122 BPM.
- Compás: 4/4.
- Subdivisión: 4 pasos por pulso (semicorcheas).

Las clases de altura van de 0 a 11.
Las notas MIDI completas van de 0 a 127.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Iterable


# ============================================================
# 1. CONSTANTES MUSICALES
# ============================================================

NOTE_NAMES = (
    "Do", "Do#", "Re", "Re#", "Mi", "Fa",
    "Fa#", "Sol", "Sol#", "La", "La#", "Si"
)

MIDI_MIN = 0
MIDI_MAX = 127

C_MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
SUPPORTED_KEY = "Do mayor"

# Progresión diatónica sencilla: todos los acordes usan notas naturales.
DEFAULT_PROGRESSION = ("Dm7", "G")

# Cada valor representa una clase de altura, no una nota MIDI completa.
# La fundamental aparece primero para conservar compatibilidad con
# music_sequencer.py, que utiliza chord_notes[0] como raíz del bajo.
CHORDS = {
    # Triadas diatónicas en Do mayor (sin sostenidos ni bemoles).
    # La fundamental va primero para mantener compatible el bajo.
    "C":  (0, 4, 7),
    "Am": (9, 0, 4),
    "F":  (5, 9, 0),
    

    # Alias compatibles con configuraciones o código anterior.
    "Cmaj7": (0, 4, 7, 11),
    "Am7":   (9, 0, 4, 7),
    "Fmaj7": (5, 9, 0, 4),
    "G7":    (7, 11, 2, 5),
    "Em":    (4, 7, 11),
     "Dm":    (2, 5, 9),
    # Voicings RESONANTIA: Dm7 y G en segunda inversión (D en el bajo).
    "Dm7":  (2, 5, 9, 0),
    "G":    (2, 7, 11),
}

# ============================================================
# 2. CONFIGURACIÓN MUSICAL
# ============================================================

@dataclass(frozen=True)
class MusicConfig:
    """Parámetros globales de teoría musical de RESONANTIA."""

    bpm: float = 122
    key: str = SUPPORTED_KEY
    progression: tuple[str, ...] = DEFAULT_PROGRESSION
    beats_per_bar: int = 4
    steps_per_beat: int = 4

    def __post_init__(self):
        """Valida los parámetros para evitar configuraciones inconsistentes."""

        if isinstance(self.bpm, bool) or not isinstance(self.bpm, (int, float)):
            raise TypeError("El BPM debe ser un número.")

        if not isfinite(self.bpm):
            raise ValueError("El BPM debe ser un número finito.")

        if not 1 <= self.bpm <= 300:
            raise ValueError("El BPM debe estar entre 1 y 300.")

        if self.key != SUPPORTED_KEY:
            raise ValueError(
                f"Tonalidad no implementada: {self.key}. "
                f"Actualmente solo se admite {SUPPORTED_KEY}."
            )

        if not isinstance(self.progression, tuple):
            raise TypeError("La progresión debe ser una tupla.")

        if not self.progression:
            raise ValueError("La progresión no puede estar vacía.")

        for chord in self.progression:
            if not isinstance(chord, str) or chord not in CHORDS:
                raise ValueError(f"Acorde no reconocido: {chord}")

        if isinstance(self.beats_per_bar, bool) or not isinstance(self.beats_per_bar, int):
            raise TypeError("beats_per_bar debe ser un entero.")

        if self.beats_per_bar <= 0:
            raise ValueError("beats_per_bar debe ser mayor que cero.")

        if isinstance(self.steps_per_beat, bool) or not isinstance(self.steps_per_beat, int):
            raise TypeError("steps_per_beat debe ser un entero.")

        if self.steps_per_beat <= 0:
            raise ValueError("steps_per_beat debe ser mayor que cero.")

    @property
    def seconds_per_beat(self) -> float:
        """Duración de un pulso de negra según el BPM global."""
        return 60.0 / self.bpm

    @property
    def seconds_per_bar(self) -> float:
        """Duración de un compás completo."""
        return self.seconds_per_beat * self.beats_per_bar

    @property
    def steps_per_bar(self) -> int:
        """Cantidad de subdivisiones por compás."""
        return self.beats_per_bar * self.steps_per_beat

    @property
    def seconds_per_step(self) -> float:
        """Duración de una subdivisión del compás."""
        return self.seconds_per_beat / self.steps_per_beat


# ============================================================
# 3. MOTOR DE ARMONÍA
# ============================================================

class HarmonyEngine:
    """
    Administra las reglas armónicas de RESONANTIA.

    Funciones principales:
    - Recorrer la progresión de acordes.
    - Consultar las notas de cada acorde.
    - Identificar notas pertenecientes a Do mayor.
    - Obtener notas seguras para melodías.
    - Convertir clases de altura a nombres musicales.
    - Generar listas de notas MIDI para registros concretos.

    Este módulo no reproduce audio ni controla el reloj en tiempo real.
    """

    def __init__(self, config: MusicConfig | None = None):
        if config is not None and not isinstance(config, MusicConfig):
            raise TypeError("config debe ser una instancia de MusicConfig.")

        self.config = config if config is not None else MusicConfig()
        self.chord_index = 0

    # --------------------------------------------------------
    # 3.1. CONSULTA DEL ACORDE ACTUAL
    # --------------------------------------------------------

    @property
    def current_chord(self) -> str:
        """Devuelve el acorde activo de la progresión."""
        return self.config.progression[self.chord_index]

    # --------------------------------------------------------
    # 3.2. CONTROL DE LA PROGRESIÓN
    # --------------------------------------------------------

    def advance_chord(self) -> str:
        """
        Avanza al siguiente acorde y vuelve al inicio al terminar.

        El módulo no decide cuándo cambiar de acorde: esa decisión debe
        coordinarse con el reloj musical y el director de RESONANTIA.
        """
        self.chord_index = (self.chord_index + 1) % len(self.config.progression)
        return self.current_chord

    def reset_progression(self) -> str:
        """Reinicia la progresión al primer acorde."""
        self.chord_index = 0
        return self.current_chord

    def set_chord_index(self, index: int) -> str:
        """Permite establecer explícitamente la posición de la progresión."""
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("El índice del acorde debe ser un entero.")

        if not 0 <= index < len(self.config.progression):
            raise ValueError("El índice está fuera de la progresión.")

        self.chord_index = index
        return self.current_chord

    # --------------------------------------------------------
    # 3.3. CONSULTA DE NOTAS DE ACORDES
    # --------------------------------------------------------

    def get_chord_notes(self, chord: str | None = None) -> tuple[int, ...]:
        """
        Devuelve las clases de altura del acorde indicado o del actual.

        Ejemplo:
            C -> (0, 4, 7)
        """
        if chord is None:
            chord = self.current_chord

        if not isinstance(chord, str) or chord not in CHORDS:
            raise ValueError(f"Acorde no reconocido: {chord}")

        return CHORDS[chord]

    # --------------------------------------------------------
    # 3.4. VALIDACIÓN Y PERTENENCIA A LA ESCALA
    # --------------------------------------------------------

    @staticmethod
    def _validate_midi_note(midi_note: int) -> None:
        if isinstance(midi_note, bool) or not isinstance(midi_note, int):
            raise TypeError("La nota MIDI debe ser un número entero.")

        if not MIDI_MIN <= midi_note <= MIDI_MAX:
            raise ValueError("La nota MIDI debe estar entre 0 y 127.")

    @staticmethod
    def _validate_midi_range(low_midi: int, high_midi: int) -> None:
        for value, label in (
            (low_midi, "límite inferior"),
            (high_midi, "límite superior"),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"El {label} debe ser un entero.")

            if not MIDI_MIN <= value <= MIDI_MAX:
                raise ValueError(f"El {label} debe estar entre 0 y 127.")

        if low_midi > high_midi:
            raise ValueError("El límite inferior supera al superior.")

    def is_in_scale(self, midi_note: int) -> bool:
        """Indica si una nota MIDI pertenece a Do mayor."""
        self._validate_midi_note(midi_note)
        return midi_note % 12 in C_MAJOR_SCALE

    # --------------------------------------------------------
    # 3.5. NOTAS DE LA ESCALA EN UN REGISTRO
    # --------------------------------------------------------

    def get_scale_notes(
        self,
        low_midi: int = 48,
        high_midi: int = 84
    ) -> list[int]:
        """Devuelve las notas MIDI de Do mayor dentro del registro solicitado."""
        self._validate_midi_range(low_midi, high_midi)

        return [
            note
            for note in range(low_midi, high_midi + 1)
            if self.is_in_scale(note)
        ]

    # --------------------------------------------------------
    # 3.6. NOTAS SEGURAS PARA LA MELODÍA
    # --------------------------------------------------------

    def get_safe_melody_notes(self, chord: str | None = None) -> tuple[int, ...]:
        """
        Devuelve las clases de altura compartidas por el acorde y la escala.

        Se conserva este método para mantener compatibilidad con el código
        anterior de RESONANTIA.
        """
        chord_notes = self.get_chord_notes(chord)

        return tuple(
            note for note in chord_notes
            if note in C_MAJOR_SCALE
        )

    def get_safe_melody_midi_notes(
        self,
        low_midi: int = 60,
        high_midi: int = 84,
        chord: str | None = None
    ) -> list[int]:
        """
        Devuelve notas MIDI compatibles simultáneamente con el acorde
        solicitado y la escala de Do mayor.
        """
        self._validate_midi_range(low_midi, high_midi)
        chord_pitch_classes = self.get_chord_notes(chord)

        return [
            note
            for note in range(low_midi, high_midi + 1)
            if note % 12 in chord_pitch_classes and self.is_in_scale(note)
        ]

    # --------------------------------------------------------
    # 3.7. SELECCIÓN DE NOTAS POR CLASE DE ALTURA
    # --------------------------------------------------------

    @staticmethod
    def get_midi_notes_for_pitch_class(
        pitch_class: int,
        low_midi: int = 0,
        high_midi: int = 127
    ) -> list[int]:
        """Devuelve todas las notas MIDI de una clase de altura en un registro."""
        if isinstance(pitch_class, bool) or not isinstance(pitch_class, int):
            raise TypeError("La clase de altura debe ser un entero.")

        if not 0 <= pitch_class <= 11:
            raise ValueError("La clase de altura debe estar entre 0 y 11.")

        HarmonyEngine._validate_midi_range(low_midi, high_midi)

        return [
            note
            for note in range(low_midi, high_midi + 1)
            if note % 12 == pitch_class
        ]

    # --------------------------------------------------------
    # 3.8. CONVERSIÓN A NOMBRE MUSICAL
    # --------------------------------------------------------

    @staticmethod
    def get_note_name(pitch_class: int) -> str:
        """Convierte una clase de altura (0-11) en su nombre musical."""
        if isinstance(pitch_class, bool) or not isinstance(pitch_class, int):
            raise TypeError("La clase de altura debe ser un entero.")

        if not 0 <= pitch_class <= 11:
            raise ValueError("La clase de altura debe estar entre 0 y 11.")

        return NOTE_NAMES[pitch_class]

    @staticmethod
    def get_midi_note_name(midi_note: int) -> str:
        """Devuelve el nombre de la nota correspondiente a un número MIDI."""
        HarmonyEngine._validate_midi_note(midi_note)
        octave = (midi_note // 12) - 1
        return f"{NOTE_NAMES[midi_note % 12]}{octave}"

    # --------------------------------------------------------
    # 3.9. INFORMACIÓN DE LA CONFIGURACIÓN
    # --------------------------------------------------------

    def get_progression(self) -> tuple[str, ...]:
        """Devuelve la progresión completa configurada."""
        return self.config.progression

    def get_progression_position(self) -> tuple[int, int]:
        """Devuelve la posición actual como (índice, cantidad de acordes)."""
        return self.chord_index, len(self.config.progression)


# ============================================================
# 4. PRUEBA INDEPENDIENTE DEL MÓDULO
# ============================================================

def run_self_test() -> None:
    """Ejecuta comprobaciones básicas sin reproducir audio."""

    harmony = HarmonyEngine()

    assert harmony.config.bpm == 122
    assert harmony.config.beats_per_bar == 4
    assert harmony.config.steps_per_beat == 4
    assert harmony.current_chord == "C"
    assert harmony.get_chord_notes() == (0, 4, 7)
    assert harmony.get_chord_notes("Am") == (9, 0, 4)
    assert harmony.is_in_scale(60)  # Do
    assert not harmony.is_in_scale(61)  # Do#

    safe_notes = harmony.get_safe_melody_midi_notes(60, 84)
    assert safe_notes
    assert all(note % 12 in harmony.get_chord_notes() for note in safe_notes)

    progression = []
    for _ in range(len(harmony.config.progression)):
        progression.append(harmony.current_chord)
        harmony.advance_chord()

    assert tuple(progression) == DEFAULT_PROGRESSION
    assert harmony.current_chord == "C"

    print("=" * 58)
    print("RESONANTIA - PRUEBA DEL MOTOR DE TEORÍA MUSICAL")
    print("=" * 58)
    print(f"Tonalidad: {harmony.config.key}")
    print(f"Tempo: {harmony.config.bpm} BPM")
    print(f"Compás: {harmony.config.beats_per_bar}/4")
    print(f"Subdivisiones por pulso: {harmony.config.steps_per_beat}")
    print(f"Duración del pulso: {harmony.config.seconds_per_beat:.4f} s")
    print(f"Duración del compás: {harmony.config.seconds_per_bar:.4f} s")
    print(f"Progresión: {' -> '.join(harmony.get_progression())}")
    print(f"Notas seguras para melodía: {safe_notes}")
    print("Pruebas completadas correctamente.")


if __name__ == "__main__":
    run_self_test()
