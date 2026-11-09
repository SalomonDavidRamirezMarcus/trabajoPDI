"""
RESONANTIA - Secuenciador musical V2
Genera eventos de electrónica bailable en compás 4/4.

Responsabilidades:
- Traducir las decisiones de MusicDirector en eventos musicales.
- Mantener todos los instrumentos dentro del mismo compás y reloj.
- Generar batería usando las notas del kit 32X DAC del SoundFont.
- Crear bajo, acordes y motivos melódicos relacionados con la armonía.
- Modificar densidad y acentos sin crear tempos independientes.

Este módulo NO reproduce audio ni administra el reloj en tiempo real.
Entrega eventos ordenados para que el motor de audio los programe.
"""

from dataclasses import dataclass
from typing import Iterable

from music_director import MusicDirector, MusicState


# ============================================================
# 1. CONFIGURACIÓN DEL SECUENCIADOR
# ============================================================

BEATS_PER_BAR = 4
MIN_MIDI_NOTE = 0
MAX_MIDI_NOTE = 127

# Mapeo indicado para el preset [4000:5C] - 32X DAC.
# Se asume la numeración MIDI habitual: C5=72, D5=74, E5=76.
# Si el piano roll de tu DAW usa otra convención de octavas,
# se debe comprobar el número MIDI real antes de cambiar estos valores.
DRUM_NOTES = {
    "kick": 72,       # C5
    "hihat": 74,      # D5
    "snare": 76,      # E5
}

# Patrones en pulsos de negra. Un compás 4/4 va de 0.0 a 4.0.
KICK_PATTERN = (0.0, 1.0, 2.0, 3.0)
SNARE_PATTERN = (1.0, 3.0)
HIHAT_PATTERN = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5)

# Motivo de grados relativos dentro del acorde.
# Los índices se adaptan al número de notas del acorde actual.
MELODY_MOTIF = (0, 2, 1, 2, 0, 1, 2, 1)
MELODY_RHYTHM = (0.0, 0.5, 1.5, 2.0, 3.0, 3.5)


# ============================================================
# 2. ESTRUCTURA DE EVENTO MUSICAL
# ============================================================

@dataclass(frozen=True)
class MusicalEvent:
    """Evento que el motor de audio debe reproducir en un punto musical."""

    bar: int
    beat: float
    instrument: str
    midi_note: int
    duration_beats: float
    velocity: int
    chord: str
    mode: str


# ============================================================
# 3. SECUENCIADOR
# ============================================================

class MusicSequencer:
    """
    Construye los eventos de cada compás a partir del MusicDirector.

    El secuenciador no acelera instrumentos individualmente. El movimiento
    modifica la densidad y los acentos, mientras el reloj global mantiene
    la sincronización de todos los eventos.
    """

    def __init__(self, director: MusicDirector | None = None):
        self.director = director or MusicDirector()
        self.harmony = self.director.harmony

        # Se consulta el tempo configurado en music_theory.py.
        # Para el objetivo actual de RESONANTIA, MusicConfig debe quedar
        # configurado en 122 BPM. Este módulo no crea relojes alternativos.
        self.bpm = self.harmony.config.bpm

        self._motif_index = 0
        self._last_melody_note: int | None = None

    # --------------------------------------------------------
    # 3.1. VALIDACIONES Y UTILIDADES
    # --------------------------------------------------------

    @staticmethod
    def _validate_bar_number(bar_number: int) -> None:
        if isinstance(bar_number, bool) or not isinstance(bar_number, int):
            raise TypeError("bar_number debe ser un número entero.")
        if bar_number < 1:
            raise ValueError("bar_number debe ser mayor o igual a 1.")

    @staticmethod
    def _validate_beat(beat: float) -> None:
        if isinstance(beat, bool) or not isinstance(beat, (int, float)):
            raise TypeError("beat debe ser un número.")
        if not 0 <= beat < BEATS_PER_BAR:
            raise ValueError("beat debe estar entre 0 (incluido) y 4 (excluido).")

    @staticmethod
    def _validate_velocity(velocity: int) -> None:
        if isinstance(velocity, bool) or not isinstance(velocity, int):
            raise TypeError("velocity debe ser un número entero.")
        if not 1 <= velocity <= 127:
            raise ValueError("velocity debe estar entre 1 y 127.")

    @staticmethod
    def _pitch_class_to_midi(
        pitch_class: int,
        low_midi: int,
        high_midi: int,
        reference_note: int | None = None,
    ) -> int:
        """Selecciona una nota MIDI de una clase de altura y registro dados."""
        if not 0 <= pitch_class <= 11:
            raise ValueError("pitch_class debe estar entre 0 y 11.")
        if not 0 <= low_midi <= high_midi <= 127:
            raise ValueError("El registro MIDI debe estar entre 0 y 127.")

        candidates = [
            note for note in range(low_midi, high_midi + 1)
            if note % 12 == pitch_class
        ]
        if not candidates:
            raise ValueError("No hay notas disponibles en el registro solicitado.")

        if reference_note is None:
            return candidates[len(candidates) // 2]

        return min(candidates, key=lambda note: abs(note - reference_note))

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, float(value)))

    def _add_event(
        self,
        events: list[MusicalEvent],
        bar: int,
        beat: float,
        instrument: str,
        note: int,
        duration: float,
        velocity: int,
        chord: str,
        mode: str,
    ) -> None:
        """Añade un evento después de validar sus parámetros."""
        self._validate_beat(beat)

        if not isinstance(instrument, str) or not instrument.strip():
            raise ValueError("instrument debe ser un texto no vacío.")
        if isinstance(note, bool) or not isinstance(note, int):
            raise TypeError("midi_note debe ser un número entero.")
        if not MIN_MIDI_NOTE <= note <= MAX_MIDI_NOTE:
            raise ValueError("midi_note debe estar entre 0 y 127.")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise TypeError("duration_beats debe ser un número.")
        if duration <= 0:
            raise ValueError("duration_beats debe ser mayor que cero.")
        self._validate_velocity(velocity)

        events.append(
            MusicalEvent(
                bar=bar,
                beat=float(beat),
                instrument=instrument,
                midi_note=note,
                duration_beats=float(duration),
                velocity=velocity,
                chord=chord,
                mode=mode,
            )
        )

    # --------------------------------------------------------
    # 3.2. BATERÍA - KIT 32X DAC
    # --------------------------------------------------------

    def _create_drums(
        self,
        events: list[MusicalEvent],
        bar_number: int,
        chord: str,
        mode: str,
        movement: float,
        intensity: float,
    ) -> None:
        """
        Genera un groove de electrónica bailable.

        Kick: cuatro pulsos por compás.
        Snare: tiempos 2 y 4.
        Hi-hat: corcheas.
        Movimiento alto: añade semicorcheas de hi-hat en posiciones
        de transición, sin modificar el BPM.
        """
        base_intensity = self._clamp(intensity, 0.0, 1.0)

        kick_velocity = int(96 + base_intensity * 20)
        snare_velocity = int(76 + base_intensity * 18)
        hat_velocity = int(38 + base_intensity * 22)

        for beat in KICK_PATTERN:
            # Un pequeño acento en el primer tiempo.
            velocity = min(120, kick_velocity + (5 if beat == 0 else 0))
            self._add_event(
                events, bar_number, beat, "kick",
                DRUM_NOTES["kick"], 0.16, velocity, chord, mode
            )

        for beat in SNARE_PATTERN:
            self._add_event(
                events, bar_number, beat, "snare",
                DRUM_NOTES["snare"], 0.14,
                min(115, snare_velocity), chord, mode
            )

        for index, beat in enumerate(HIHAT_PATTERN):
            # Alternancia de acentos para que el hi-hat no sea plano.
            velocity = hat_velocity if index % 2 == 0 else max(25, hat_velocity - 12)
            self._add_event(
                events, bar_number, beat, "hihat",
                DRUM_NOTES["hihat"], 0.08,
                min(100, velocity), chord, mode
            )

        # A mayor movimiento, más actividad rítmica, nunca otro tempo.
        if movement >= 0.65:
            for beat in (0.75, 1.75, 2.75, 3.75):
                self._add_event(
                    events, bar_number, beat, "hihat",
                    DRUM_NOTES["hihat"], 0.06,
                    max(25, min(75, hat_velocity - 8)), chord, mode
                )

    # --------------------------------------------------------
    # 3.3. BAJO
    # --------------------------------------------------------

    def _create_bass(
        self,
        events: list[MusicalEvent],
        bar_number: int,
        chord: str,
        chord_notes: tuple[int, ...],
        mode: str,
        intensity: float,
        movement: float,
    ) -> None:
        """Genera una línea de bajo basada en la fundamental del acorde."""
        if not chord_notes:
            return

        root = chord_notes[0]
        bass_note = self._pitch_class_to_midi(root, 28, 43)

        # Patrón sincopado estable. La actividad aumenta los acentos,
        # pero las posiciones siguen ancladas al compás compartido.
        pattern = (0.0, 1.5, 2.0, 3.5)
        velocity_base = int(72 + self._clamp(intensity, 0, 1) * 28)

        for index, beat in enumerate(pattern):
            accent = 7 if index in (0, 2) else 0
            movement_accent = 4 if movement >= 0.65 and index == 3 else 0
            velocity = min(115, velocity_base + accent + movement_accent)

            self._add_event(
                events, bar_number, beat, "bass",
                bass_note, 0.42, velocity, chord, mode
            )

    # --------------------------------------------------------
    # 3.4. ARMONÍA
    # --------------------------------------------------------

    def _create_harmony(
        self,
        events: list[MusicalEvent],
        bar_number: int,
        chord: str,
        chord_notes: tuple[int, ...],
        mode: str,
        intensity: float,
    ) -> None:
        """Distribuye notas del acorde en voicings breves y sincronizados."""
        if not chord_notes:
            return

        # Dos entradas por compás para aportar energía sin saturar.
        for beat in (0.0, 2.0):
            for pitch_class in chord_notes[:4]:
                note = self._pitch_class_to_midi(pitch_class, 60, 76)
                velocity = int(48 + self._clamp(intensity, 0, 1) * 18)

                self._add_event(
                    events, bar_number, beat, "chords",
                    note, 0.72, velocity, chord, mode
                )

    # --------------------------------------------------------
    # 3.5. MELODÍA
    # --------------------------------------------------------

    def _create_melody(
        self,
        events: list[MusicalEvent],
        bar_number: int,
        chord: str,
        chord_notes: tuple[int, ...],
        mode: str,
        density: float,
        intensity: float,
    ) -> None:
        """
        Construye un motivo melódico repetible con variaciones pequeñas.

        Las notas se eligen entre las notas del acorde actual y se mantienen
        en un registro agudo. Se favorecen movimientos cercanos para evitar
        saltos excesivos entre notas consecutivas.
        """
        if not chord_notes:
            return

        density = self._clamp(density, 0.0, 1.0)
        intensity = self._clamp(intensity, 0.0, 1.0)

        if density < 0.35:
            selected_beats = (0.0, 2.0)
        elif density < 0.65:
            selected_beats = (0.0, 1.0, 2.0, 3.0)
        else:
            selected_beats = MELODY_RHYTHM

        for index, beat in enumerate(selected_beats):
            motif_position = (index + self._motif_index) % len(MELODY_MOTIF)
            chord_index = MELODY_MOTIF[motif_position] % len(chord_notes)
            pitch_class = chord_notes[chord_index]

            # Alterna el registro de manera moderada cada cierto número
            # de compases, manteniendo el motivo reconocible.
            low, high = (72, 88)
            if self._motif_index == 2 and index == len(selected_beats) - 1:
                low, high = (76, 91)

            note = self._pitch_class_to_midi(
                pitch_class,
                low,
                high,
                reference_note=self._last_melody_note,
            )

            # Evita saltos grandes cuando existe una alternativa cercana.
            if self._last_melody_note is not None:
                nearby_notes = [
                    candidate
                    for candidate in range(69, 89)
                    if candidate % 12 == pitch_class
                ]
                if nearby_notes:
                    note = min(
                        nearby_notes,
                        key=lambda candidate: abs(candidate - self._last_melody_note),
                    )

            self._last_melody_note = note
            velocity = int(58 + intensity * 28)

            # Notas cortas para dejar espacio a la batería y al bajo.
            self._add_event(
                events, bar_number, beat, "melody",
                note, 0.30, min(105, velocity), chord, mode
            )

        self._motif_index = (self._motif_index + 1) % 4

    # --------------------------------------------------------
    # 3.6. GENERAR UN COMPÁS
    # --------------------------------------------------------

    def create_bar(self, bar_number: int, state: MusicState):
        """
        Genera los eventos de un compás.

        No avanza automáticamente la progresión armónica: el llamador
        debe invocar director.advance_bar() cuando termine el compás.
        """
        self._validate_bar_number(bar_number)

        if state is None:
            raise TypeError("state no puede ser None.")

        decision = self.director.update(state)
        chord = decision.chord
        chord_notes = self.harmony.get_chord_notes(chord)
        events: list[MusicalEvent] = []

        if decision.mode == "silence":
            return events, decision

        movement = self._clamp(getattr(state, "movement", 0.0), 0.0, 1.0)

        if decision.drums_enabled:
            self._create_drums(
                events, bar_number, chord, decision.mode,
                movement, decision.intensity
            )

        if decision.bass_enabled:
            self._create_bass(
                events, bar_number, chord, chord_notes, decision.mode,
                decision.intensity, movement
            )

        if decision.harmony_enabled:
            self._create_harmony(
                events, bar_number, chord, chord_notes, decision.mode,
                decision.intensity
            )

        if "melody" in decision.active_roles:
            self._create_melody(
                events, bar_number, chord, chord_notes, decision.mode,
                decision.melody_density, decision.intensity
            )

        # Orden determinista: primero el instante, luego la familia
        # instrumental para facilitar el envío al motor de audio.
        instrument_order = {
            "kick": 0,
            "snare": 1,
            "hihat": 2,
            "bass": 3,
            "chords": 4,
            "melody": 5,
        }
        events.sort(
            key=lambda event: (
                event.beat,
                instrument_order.get(event.instrument, 99),
                event.midi_note,
            )
        )

        return events, decision

    # --------------------------------------------------------
    # 3.7. GENERAR UNA PROGRESIÓN
    # --------------------------------------------------------

    def create_progression(self, states: Iterable[MusicState]):
        """
        Genera varios compases y avanza un acorde al terminar cada uno.

        Cada elemento de states representa el estado humano correspondiente
        a un compás. La temporización real debe realizarla el reloj global.
        """
        all_events: list[MusicalEvent] = []
        results = []

        for bar_number, state in enumerate(states, start=1):
            events, decision = self.create_bar(bar_number, state)

            all_events.extend(events)
            results.append(
                {
                    "bar": bar_number,
                    "state": state,
                    "decision": decision,
                    "events": events,
                }
            )

            self.director.advance_bar()

        return all_events, results


# ============================================================
# 4. PRUEBA INDEPENDIENTE
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("RESONANTIA - PRUEBA DEL SECUENCIADOR MUSICAL")
    print("=" * 60)

    sequencer = MusicSequencer()

    print(f"Tempo configurado: {sequencer.bpm} BPM")
    print("Compás: 4/4")
    print("Kit de batería: SoundFont 32X DAC")
    print(f"Notas de batería: {DRUM_NOTES}")

    scenarios = [
        ("Una persona", MusicState(people_count=1, movement=0.25)),
        ("Dos personas", MusicState(people_count=2, movement=0.45)),
        ("Tres personas", MusicState(people_count=3, movement=0.70)),
        ("Cuatro personas", MusicState(people_count=4, movement=0.90)),
    ]

    for bar_number, (label, state) in enumerate(scenarios, start=1):
        events, decision = sequencer.create_bar(bar_number, state)

        print(f"\n--- Compás {bar_number}: {label} ---")
        print(f"Modo: {decision.mode}")
        print(f"Acorde: {decision.chord}")
        print(f"Capas: {decision.active_roles}")
        print(f"Eventos generados: {len(events)}")

        for event in events:
            print(
                f"Pulso {event.beat:>3} | "
                f"{event.instrument:<7} | "
                f"MIDI {event.midi_note:>3} | "
                f"Duración {event.duration_beats:.2f} | "
                f"Velocidad {event.velocity}"
            )

        sequencer.director.advance_bar()

    print("\nPrueba del secuenciador finalizada.")
