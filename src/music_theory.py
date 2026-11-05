
"""
Resonantia - Teoría musical
Gestiona tonalidades, escalas, acordes y selección de notas.

Identidad sonora: Melódica
Tonalidad: La menor natural
Tempo: 110 BPM
Compás de referencia: 4/4

IMPORTANTE:
- Las clases de altura van de 0 a 11.
- Las notas MIDI van de 0 a 127.
"""

from dataclasses import dataclass
from math import isfinite


# ============================================================
# 1. CONFIGURACIÓN DE NOTAS
# ============================================================

# Clases de altura:
# Do=0, Do#=1, Re=2 ... Si=11.

NOTE_NAMES = (
    "Do", "Do#", "Re", "Re#", "Mi", "Fa",
    "Fa#", "Sol", "Sol#", "La", "La#", "Si"
)

MIDI_MIN = 0
MIDI_MAX = 127

# La menor natural:
# La, Si, Do, Re, Mi, Fa, Sol.
A_MINOR_SCALE = (9, 11, 0, 2, 4, 5, 7)

# Nombre de la tonalidad implementada.
SUPPORTED_KEY = "La menor"


# ============================================================
# 2. ACORDES DE RESONANTIA
# ============================================================

# Cada número representa una clase de altura,
# NO una nota MIDI completa.

CHORDS = {
    "Am9":   (9, 0, 4, 7, 11),  # La - Do - Mi - Sol - Si
    "Fmaj7": (5, 9, 0, 4),      # Fa - La - Do - Mi
    "Cmaj7": (0, 4, 7, 11),     # Do - Mi - Sol - Si
    "G6":    (7, 11, 2, 4),     # Sol - Si - Re - Mi
}


# ============================================================
# 3. CONFIGURACIÓN MUSICAL
# ============================================================

@dataclass(frozen=True)
class MusicConfig:
    """Configuración musical inicial de Resonantia."""

    bpm: int = 110
    key: str = SUPPORTED_KEY
    progression: tuple[str, ...] = (
        "Am9",
        "Fmaj7",
        "Cmaj7",
        "G6"
    )

    def __post_init__(self):
        # Validar BPM.
        if isinstance(self.bpm, bool) or not isinstance(self.bpm, (int, float)):
            raise TypeError("El BPM debe ser un número.")

        if not isfinite(self.bpm):
            raise ValueError("El BPM debe ser un número finito.")

        if not 1 <= self.bpm <= 300:
            raise ValueError("El BPM debe estar entre 1 y 300.")

        # Validar tonalidad.
        if self.key != SUPPORTED_KEY:
            raise ValueError(
                f"Tonalidad no implementada: {self.key}. "
                f"Actualmente solo se admite {SUPPORTED_KEY}."
            )

        # Validar progresión.
        if not isinstance(self.progression, tuple):
            raise TypeError("La progresión debe ser una tupla.")

        if not self.progression:
            raise ValueError("La progresión no puede estar vacía.")

        for chord in self.progression:
            if chord not in CHORDS:
                raise ValueError(f"Acorde no reconocido: {chord}")


# ============================================================
# 4. MOTOR DE ARMONÍA
# ============================================================

class HarmonyEngine:
    """
    Aplica las reglas básicas de armonía de Resonantia.

    Administra:
    - Progresión de acordes.
    - Escala musical.
    - Selección de notas compatibles.
    - Conversión de clases de altura a notas MIDI.
    """

    def __init__(self, config: MusicConfig | None = None):
        self.config = config if config is not None else MusicConfig()
        self.chord_index = 0

    # --------------------------------------------------------
    # 4.1. CONSULTAR ACORDE ACTUAL
    # --------------------------------------------------------

    @property
    def current_chord(self) -> str:
        """Devuelve el acorde activo."""
        return self.config.progression[self.chord_index]

    # --------------------------------------------------------
    # 4.2. AVANZAR EN LA PROGRESIÓN
    # --------------------------------------------------------

    def advance_chord(self) -> str:
        """
        Avanza al siguiente acorde.

        Al terminar la progresión, vuelve al primer acorde.
        """

        self.chord_index = (
            self.chord_index + 1
        ) % len(self.config.progression)

        return self.current_chord

    # --------------------------------------------------------
    # 4.3. OBTENER NOTAS DE UN ACORDE
    # --------------------------------------------------------

    def get_chord_notes(
        self,
        chord: str | None = None
    ) -> tuple[int, ...]:
        """
        Devuelve las clases de altura del acorde activo
        o del acorde solicitado.

        Ejemplo:
        Am9 -> (9, 0, 4, 7, 11)
        """

        if chord is None:
            chord = self.current_chord

        if not isinstance(chord, str) or chord not in CHORDS:
            raise ValueError(f"Acorde no reconocido: {chord}")

        return CHORDS[chord]

    # --------------------------------------------------------
    # 4.4. COMPROBAR PERTENENCIA A LA ESCALA
    # --------------------------------------------------------

    def is_in_scale(self, midi_note: int) -> bool:
        """
        Comprueba si una nota MIDI pertenece a La menor natural.

        Recibe una nota MIDI completa entre 0 y 127.
        """

        if isinstance(midi_note, bool) or not isinstance(midi_note, int):
            raise TypeError("La nota MIDI debe ser un número entero.")

        if not MIDI_MIN <= midi_note <= MIDI_MAX:
            raise ValueError("La nota MIDI debe estar entre 0 y 127.")

        return midi_note % 12 in A_MINOR_SCALE

    # --------------------------------------------------------
    # 4.5. OBTENER NOTAS DE LA ESCALA EN UN REGISTRO
    # --------------------------------------------------------

    def get_scale_notes(
        self,
        low_midi: int = 48,
        high_midi: int = 84
    ) -> list[int]:
        """
        Devuelve todas las notas MIDI de La menor natural
        dentro del registro solicitado.

        Ejemplo:
        get_scale_notes(60, 72)
        """

        if isinstance(low_midi, bool) or not isinstance(low_midi, int):
            raise TypeError("El límite inferior debe ser un entero.")

        if isinstance(high_midi, bool) or not isinstance(high_midi, int):
            raise TypeError("El límite superior debe ser un entero.")

        if not MIDI_MIN <= low_midi <= MIDI_MAX:
            raise ValueError("El límite inferior debe estar entre 0 y 127.")

        if not MIDI_MIN <= high_midi <= MIDI_MAX:
            raise ValueError("El límite superior debe estar entre 0 y 127.")

        if low_midi > high_midi:
            raise ValueError("El límite inferior supera al superior.")

        return [
            note
            for note in range(low_midi, high_midi + 1)
            if self.is_in_scale(note)
        ]

    # --------------------------------------------------------
    # 4.6. NOTAS SEGURAS PARA LA MELODÍA
    # --------------------------------------------------------

    def get_safe_melody_notes(self) -> tuple[int, ...]:
        """
        Devuelve las clases de altura del acorde actual
        que también pertenecen a La menor.

        Se conserva este formato por compatibilidad
        con el código anterior de Resonantia.
        """

        return tuple(
            note
            for note in self.get_chord_notes()
            if note in A_MINOR_SCALE
        )

    # --------------------------------------------------------
    # 4.7. NOTAS MIDI SEGURAS PARA LA MELODÍA
    # --------------------------------------------------------

    def get_safe_melody_midi_notes(
        self,
        low_midi: int = 60,
        high_midi: int = 84
    ) -> list[int]:
        """
        Devuelve notas MIDI completas que pertenecen
        al acorde actual y a la escala de La menor.

        Permite seleccionar registros adecuados para
        construir melodías reconocibles.
        """

        if isinstance(low_midi, bool) or not isinstance(low_midi, int):
            raise TypeError("El límite inferior debe ser un entero.")

        if isinstance(high_midi, bool) or not isinstance(high_midi, int):
            raise TypeError("El límite superior debe ser un entero.")

        if not MIDI_MIN <= low_midi <= MIDI_MAX:
            raise ValueError("El límite inferior debe estar entre 0 y 127.")

        if not MIDI_MIN <= high_midi <= MIDI_MAX:
            raise ValueError("El límite superior debe estar entre 0 y 127.")

        if low_midi > high_midi:
            raise ValueError("El límite inferior supera al superior.")

        chord_pitch_classes = self.get_chord_notes()

        return [
            note
            for note in range(low_midi, high_midi + 1)
            if (
                note % 12 in chord_pitch_classes
                and self.is_in_scale(note)
            )
        ]

    # --------------------------------------------------------
    # 4.8. CONVERTIR CLASE DE ALTURA A NOMBRE
    # --------------------------------------------------------

    @staticmethod
    def get_note_name(pitch_class: int) -> str:
        """Convierte una clase de altura en su nombre musical."""

        if isinstance(pitch_class, bool) or not isinstance(pitch_class, int):
            raise TypeError("La clase de altura debe ser un entero.")

        if not 0 <= pitch_class <= 11:
            raise ValueError("La clase de altura debe estar entre 0 y 11.")

        return NOTE_NAMES[pitch_class]


# ============================================================
# 5. PRUEBA INDEPENDIENTE DEL MÓDULO
# ============================================================

if __name__ == "__main__":

    harmony = HarmonyEngine()

    print("=" * 45)
    print("       RESONANTIA - MOTOR MUSICAL")
    print("=" * 45)

    print(f"Tonalidad: {harmony.config.key}")
    print(f"Tempo: {harmony.config.bpm} BPM")
    print(f"Progresión: {' -> '.join(harmony.config.progression)}")

    print("\nACORDE INICIAL")
    print("-" * 45)

    print(f"Acorde: {harmony.current_chord}")
    print(f"Notas: {harmony.get_chord_notes()}")
    print(f"Notas melódicas: {harmony.get_safe_melody_notes()}")

    print("\nNOTAS MIDI PARA LA MELODÍA")
    print("-" * 45)

    midi_notes = harmony.get_safe_melody_midi_notes()

    for note in midi_notes:
        pitch_class = note % 12
        note_name = harmony.get_note_name(pitch_class)

        print(f"MIDI {note}: {note_name}")

    print("\nRECORRIDO DE LA PROGRESIÓN")
    print("-" * 45)

    for _ in range(len(harmony.config.progression)):

        chord = harmony.current_chord
        notes = harmony.get_chord_notes()

        print(f"{chord}: {notes}")

        harmony.advance_chord()

    print("\nPRUEBA DE ESCALA")
    print("-" * 45)

    scale_notes = harmony.get_scale_notes(60, 72)

    print(f"Notas MIDI entre 60 y 72: {scale_notes}")

    print("\nMotor musical ejecutado correctamente.")
