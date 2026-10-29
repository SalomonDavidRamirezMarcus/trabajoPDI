
"""
Resonantia - Director musical
Decide cómo evoluciona la composición según la interacción humana.
"""

from dataclasses import dataclass, field

from music_theory import HarmonyEngine


@dataclass
class MusicState:
    """Información simplificada recibida del sistema de visión."""

    people_count: int = 0
    contact_detected: bool = False
    synchrony: float = 0.0


@dataclass
class MusicDecision:
    """Decisión musical que utilizará posteriormente el motor de audio."""

    mode: str
    chord: str
    bass_enabled: bool
    drums_enabled: bool
    harmony_enabled: bool
    melody_density: float
    intensity: float
    events: list[str] = field(default_factory=list)


class MusicDirector:
    """Traduce las interacciones humanas en decisiones musicales."""

    def __init__(self, harmony: HarmonyEngine | None = None):
        self.harmony = harmony or HarmonyEngine()

    def advance_bar(self) -> str:
        """
        Avanza al siguiente acorde.
        Llamar una vez al terminar cada compás musical.
        """
        return self.harmony.advance_chord()

    def update(self, state: MusicState) -> MusicDecision:
        """Calcula las capas musicales según la situación actual."""

        if state.people_count < 0:
            raise ValueError("people_count no puede ser negativo.")

        if not 0.0 <= state.synchrony <= 1.0:
            raise ValueError("synchrony debe estar entre 0 y 1.")

        # Estado 1: no hay personas.
        if state.people_count == 0:
            mode = "silence"
            bass = False
            drums = False
            harmony = False
            density = 0.0
            intensity = 0.0
            events = ["fade_out_layers"]

        # Estado 2: contacto entre dos o más personas.
        elif state.contact_detected and state.people_count >= 2:
            mode = "connection"
            bass = True
            drums = True
            harmony = True
            density = 0.9
            intensity = 0.8
            events = [
                "activate_shared_chord",
                "synchronize_bass_and_drums",
                "increase_harmonic_density",
            ]

        # Estado 3: varias personas sin contacto detectado.
        elif state.people_count >= 2:
            mode = "exploration"
            bass = state.synchrony >= 0.5
            drums = True
            harmony = False
            density = 0.5
            intensity = 0.45
            events = ["play_independent_melodies"]

            if bass:
                events.append("introduce_rhythmic_bass")

        # Estado 4: una persona.
        else:
            mode = "solo"
            bass = False
            drums = False
            harmony = False
            density = 0.3
            intensity = 0.3
            events = ["play_individual_melody"]

        return MusicDecision(
            mode=mode,
            chord=self.harmony.current_chord,
            bass_enabled=bass,
            drums_enabled=drums,
            harmony_enabled=harmony,
            melody_density=density,
            intensity=intensity,
            events=events,
        )


if __name__ == "__main__":
    director = MusicDirector()

    scenarios = [
        (
            "Sin personas",
            MusicState(),
        ),
        (
            "Una persona",
            MusicState(people_count=1),
        ),
        (
            "Dos personas",
            MusicState(people_count=2, synchrony=0.2),
        ),
        (
            "Dos personas sincronizadas",
            MusicState(people_count=2, synchrony=0.8),
        ),
        (
            "Contacto",
            MusicState(
                people_count=2,
                contact_detected=True,
                synchrony=0.8,
            ),
        ),
    ]

    print("=== RESONANTIA: DIRECTOR MUSICAL ===")

    for name, state in scenarios:
        decision = director.update(state)

        print(f"\n--- {name} ---")
        print(f"Modo musical: {decision.mode}")
        print(f"Acorde: {decision.chord}")
        print(f"Bajo: {decision.bass_enabled}")
        print(f"Percusión: {decision.drums_enabled}")
        print(f"Armonía compartida: {decision.harmony_enabled}")
        print(f"Densidad melódica: {decision.melody_density}")
        print(f"Intensidad: {decision.intensity}")
        print(f"Eventos: {', '.join(decision.events)}")

    print("\n=== PRUEBA DE PROGRESIÓN ARMÓNICA ===")

    for _ in range(4):
        print(f"Acorde actual: {director.harmony.current_chord}")
        director.advance_bar()
