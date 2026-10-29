
"""
Resonantia - Secuenciador musical integrado
Combina las decisiones del director musical con la generacion
de eventos de bajo, acordes, melodia y percusion.
Todavia no reproduce sonido.
"""

from dataclasses import dataclass

from music_theory import HarmonyEngine, CHORDS
from music_director import MusicDirector, MusicState


@dataclass
class MusicalEvent:
    bar: int
    beat: float
    instrument: str
    midi_note: int
    duration_beats: float
    velocity: int
    chord: str
    mode: str


class MusicSequencer:
    def __init__(self, director=None):
        self.director = director or MusicDirector()
        self.harmony = self.director.harmony
        self.bpm = self.harmony.config.bpm

    @staticmethod
    def pitch_class_to_midi(pitch_class, minimum, maximum):
        """Convierte una clase de nota en una nota MIDI del registro elegido."""
        candidates = [
            note
            for note in range(minimum, maximum + 1)
            if note % 12 == pitch_class
        ]

        if not candidates:
            raise ValueError(
                f"No hay una nota MIDI para la clase {pitch_class} "
                f"entre {minimum} y {maximum}."
            )

        return candidates[0]

    def add_event(
        self, events, bar, beat, instrument, note,
        duration, velocity, chord, mode
    ):
        events.append(
            MusicalEvent(
                bar=bar,
                beat=beat,
                instrument=instrument,
                midi_note=note,
                duration_beats=duration,
                velocity=velocity,
                chord=chord,
                mode=mode,
            )
        )

    def create_bar(self, bar_number, state):
        """Genera musica segun el estado humano recibido."""
        decision = self.director.update(state)
        chord_name = decision.chord
        chord_notes = CHORDS[chord_name]
        events = []

        # Sin personas: no se generan notas nuevas.
        if decision.mode == "silence":
            return events, decision

        # Bajo: solo cuando el director lo habilita.
        if decision.bass_enabled:
            root_pitch = chord_notes[0]
            bass_note = self.pitch_class_to_midi(
                root_pitch, 28, 43
            )

            for beat in (0, 2):
                self.add_event(
                    events, bar_number, beat, "bass",
                    bass_note, 1.5, 95, chord_name, decision.mode
                )

        # Acordes: se activan especialmente durante el contacto.
        if decision.harmony_enabled:
            for pitch in chord_notes:
                chord_note = self.pitch_class_to_midi(
                    pitch, 60, 76
                )
                self.add_event(
                    events, bar_number, 0, "chords",
                    chord_note, 4, 70, chord_name, decision.mode
                )

        # Melodia: aumenta la cantidad de notas con la densidad.
        if decision.melody_density > 0:
            melody_pattern = (0, 2, 3, 2)

            if decision.melody_density >= 0.8:
                melody_beats = (0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5)
            elif decision.melody_density >= 0.5:
                melody_beats = (0, 1, 2, 3)
            else:
                melody_beats = (0, 2)

            for index, beat in enumerate(melody_beats):
                chord_index = melody_pattern[index % len(melody_pattern)]
                pitch = chord_notes[chord_index % len(chord_notes)]
                melody_note = self.pitch_class_to_midi(
                    pitch, 72, 88
                )

                self.add_event(
                    events, bar_number, beat, "melody",
                    melody_note, 0.4 if len(melody_beats) > 4 else 0.75,
                    78, chord_name, decision.mode
                )

        # Percusion basica: notas MIDI convencionales de bateria.
        if decision.drums_enabled:
            kick_note = 36
            hat_note = 42

            for beat in (0, 2):
                self.add_event(
                    events, bar_number, beat, "kick",
                    kick_note, 0.25, 100, chord_name, decision.mode
                )

            for beat in (0, 1, 2, 3):
                self.add_event(
                    events, bar_number, beat, "hihat",
                    hat_note, 0.2, 55, chord_name, decision.mode
                )

        return events, decision

    def create_progression(self, states):
        """Genera un compas por cada estado humano recibido."""
        all_events = []
        results = []

        for bar_number, state in enumerate(states, start=1):
            events, decision = self.create_bar(bar_number, state)
            all_events.extend(events)

            results.append({
                "bar": bar_number,
                "state": state,
                "decision": decision,
                "events": events,
            })

            # El siguiente compas utiliza el siguiente acorde.
            self.director.advance_bar()

        return all_events, results


if __name__ == "__main__":
    director = MusicDirector()
    sequencer = MusicSequencer(director)

    scenarios = [
        ("Una persona", MusicState(people_count=1)),
        ("Dos personas", MusicState(people_count=2, synchrony=0.2)),
        (
            "Personas sincronizadas",
            MusicState(people_count=2, synchrony=0.8),
        ),
        (
            "Contacto entre personas",
            MusicState(
                people_count=2,
                contact_detected=True,
                synchrony=0.8,
            ),
        ),
    ]

    states = [state for _, state in scenarios]
    all_events, results = sequencer.create_progression(states)

    print("=== RESONANTIA: SECUENCIADOR INTEGRADO ===")
    print(f"Tempo: {sequencer.bpm} BPM")
    print("Compas: 4/4")
    print("Progresion: Am9 -> Fmaj7 -> Cmaj7 -> G6")

    for scenario, result in zip(scenarios, results):
        decision = result["decision"]

        print(f"\n--- Compas {result['bar']}: {scenario[0]} ---")
        print(f"Modo: {decision.mode}")
        print(f"Acorde: {decision.chord}")
        print(f"Intensidad: {decision.intensity}")
        print(f"Eventos musicales: {len(result['events'])}")

        for event in result["events"]:
            print(
                f"Tiempo {event.beat:>3} | "
                f"{event.instrument:7} | "
                f"MIDI {event.midi_note:2} | "
                f"velocidad {event.velocity}"
            )

    print(f"\nTotal de eventos generados: {len(all_events)}")
    print("Prueba terminada: no se ha reproducido audio.")
