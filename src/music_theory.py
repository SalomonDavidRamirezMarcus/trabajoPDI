
"""
Resonantia - Teoría musical
Gestiona tonalidades, escalas, acordes y selección de notas.
"""

from dataclasses import dataclass


# Notas cromáticas: cada nota tiene un número MIDI asociado.
NOTE_NAMES = (
    "Do", "Do#", "Re", "Re#", "Mi", "Fa",
    "Fa#", "Sol", "Sol#", "La", "La#", "Si"
)

# La menor natural: todas estas notas pertenecen a la escala.
A_MINOR_SCALE = (9, 11, 0, 2, 4, 5, 7)

# Progresión armónica inicial: Am - F - C - G.

# Acordes extendidos para la identidad electrónica de Resonantia.
# Cada número representa una clase de altura: Do=0, ..., Si=11.

CHORDS = {
    "Am9":   (9, 0, 4, 7, 11),  # La - Do - Mi - Sol - Si
    "Fmaj7": (5, 9, 0, 4),      # Fa - La - Do - Mi
    "Cmaj7": (0, 4, 7, 11),     # Do - Mi - Sol - Si
    "G6":    (7, 11, 2, 4),     # Sol - Si - Re - Mi
}


@dataclass(frozen=True)
class MusicConfig:
    """Configuración musical inicial de Resonantia."""

    bpm: int = 110
    key: str = "La menor"
    progression: tuple[str, ...] = ("Am9", "Fmaj7", "Cmaj7", "G6")

    def __post_init__(self):
        if self.bpm <= 0:
            raise ValueError("El BPM debe ser mayor que cero.")

        if not self.progression:
            raise ValueError("La progresión no puede estar vacía.")

        for chord in self.progression:
            if chord not in CHORDS:
                raise ValueError(f"Acorde no reconocido: {chord}")


class HarmonyEngine:
    """Aplica las reglas básicas de armonía de Resonantia."""

    def __init__(self, config: MusicConfig | None = None):
        self.config = config or MusicConfig()
        self.chord_index = 0

    @property
    def current_chord(self) -> str:
        """Devuelve el acorde activo."""
        return self.config.progression[self.chord_index]

    def advance_chord(self) -> str:
        """Avanza al siguiente acorde de la progresión."""
        self.chord_index = (
            self.chord_index + 1
        ) % len(self.config.progression)

        return self.current_chord

    def get_chord_notes(self, chord: str | None = None) -> tuple[int, ...]:
        """Devuelve las notas del acorde activo o del acorde solicitado."""
        chord = chord or self.current_chord

        if chord not in CHORDS:
            raise ValueError(f"Acorde no reconocido: {chord}")

        return CHORDS[chord]

    def is_in_scale(self, midi_note: int) -> bool:
        """Comprueba si una nota MIDI pertenece a La menor natural."""
        return midi_note % 12 in A_MINOR_SCALE

    def get_scale_notes(
        self,
        low_midi: int = 48,
        high_midi: int = 84,
    ) -> list[int]:
        """Devuelve las notas de La menor dentro de un registro MIDI."""
        if low_midi > high_midi:
            raise ValueError("El límite inferior supera al superior.")

        return [
            note
            for note in range(low_midi, high_midi + 1)
            if self.is_in_scale(note)
        ]

    def get_safe_melody_notes(self) -> tuple[int, ...]:
        """
        Devuelve las notas del acorde activo que también
        pertenecen a La menor.
        """
        return tuple(
            note
            for note in self.get_chord_notes()
            if note in A_MINOR_SCALE
        )


if __name__ == "__main__":
    harmony = HarmonyEngine()

    print("=== RESONANTIA: MOTOR MUSICAL ===")
    print(f"Tonalidad: {harmony.config.key}")
    print(f"Tempo: {harmony.config.bpm} BPM")
    print(f"Acorde inicial: {harmony.current_chord}")
    print(f"Notas del acorde: {harmony.get_chord_notes()}")
    print(f"Notas permitidas: {harmony.get_safe_melody_notes()}")

    print("\nRecorrido de la progresión:")
    for _ in range(len(harmony.config.progression)):
        print(harmony.current_chord, harmony.get_chord_notes())
        harmony.advance_chord()
