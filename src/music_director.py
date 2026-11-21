"""
RESONANTIA - Director musical

Responsabilidad:
    Traducir el estado general de los participantes en decisiones musicales.

Criterios de diseño:
    - El director NO controla el tempo. Todos los instrumentos comparten el
      reloj musical global administrado por music_clock.py.
    - La energía del movimiento modifica densidad e intensidad, no la velocidad
      de reproducción de cada instrumento.
    - Los roles se habilitan progresivamente según la cantidad de personas.
    - Esta versión asigna capas por cantidad de participantes. La asignación
      persistente por track_id se implementará cuando la integración entregue
      los identificadores individuales al director.

Compatibilidad:
    Conserva people_count, contact_detected y synchrony de la versión anterior.
    Añade movement y arm_opening como parámetros opcionales. El main.py actual
    puede seguir enviando el movimiento por MusicWorker.update_state().
"""

from dataclasses import dataclass, field
from math import isfinite
from typing import Optional

from music_theory import HarmonyEngine


# ============================================================
# 1. ESTADO RECIBIDO DESDE VISIÓN Y ANÁLISIS DE MOVIMIENTO
# ============================================================

@dataclass
class MusicState:
    """Resumen del estado colectivo en un instante de la experiencia."""

    people_count: int = 0
    contact_detected: bool = False
    synchrony: float = 0.0
    movement: float = 0.0
    arm_opening: float = 0.0
    motion_phase: str = "stillness"
    motion_onset: float = 0.0
    direction_change: float = 0.0
    acceleration: float = 0.0

    def __post_init__(self) -> None:
        """Valida los datos para evitar decisiones musicales inconsistentes."""
        if isinstance(self.people_count, bool) or not isinstance(self.people_count, int):
            raise TypeError("people_count debe ser un número entero.")
        if self.people_count < 0:
            raise ValueError("people_count no puede ser negativo.")

        if not isinstance(self.contact_detected, bool):
            raise TypeError("contact_detected debe ser booleano.")

        self.synchrony = self._validate_unit_interval(self.synchrony, "synchrony")
        self.movement = self._validate_unit_interval(self.movement, "movement")
        self.arm_opening = self._validate_unit_interval(self.arm_opening, "arm_opening")
        if self.motion_phase not in {"stillness", "attack", "sustain", "release"}:
            raise ValueError("motion_phase no es una fase reconocida.")
        self.motion_onset = self._validate_unit_interval(self.motion_onset, "motion_onset")
        self.direction_change = self._validate_unit_interval(self.direction_change, "direction_change")
        self.acceleration = self._validate_unit_interval(self.acceleration, "acceleration")

    @staticmethod
    def _validate_unit_interval(value: float, field_name: str) -> float:
        """Convierte a float y valida que el valor esté entre 0 y 1."""
        if isinstance(value, bool):
            raise TypeError(f"{field_name} debe ser numérico, no booleano.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{field_name} debe ser numérico.") from exc

        if not isfinite(number):
            raise ValueError(f"{field_name} debe ser un número finito.")
        if not 0.0 <= number <= 1.0:
            raise ValueError(f"{field_name} debe estar entre 0 y 1.")
        return number


# ============================================================
# 2. DECISIÓN MUSICAL
# ============================================================

@dataclass
class MusicDecision:
    """Resultado que consume el secuenciador musical."""

    mode: str
    chord: str
    bass_enabled: bool
    drums_enabled: bool
    harmony_enabled: bool
    melody_density: float
    intensity: float
    active_roles: tuple[str, ...] = ()
    events: list[str] = field(default_factory=list)


# ============================================================
# 3. DIRECTOR MUSICAL
# ============================================================

class MusicDirector:
    """Decide qué capas musicales están activas y cómo se expresan."""

    # Orden de incorporación de las capas según participantes detectados.
    # Una persona: melodía.
    # Dos personas: melodía + bajo.
    # Tres personas: melodía + bajo + batería.
    # Cuatro o más: se añade armonía.
    ROLE_THRESHOLDS = (
        (1, "melody"),
        (2, "bass"),
        (3, "drums"),
        (4, "harmony"),
    )

    def __init__(self, harmony: Optional[HarmonyEngine] = None) -> None:
        """Inicializa el director con el motor armónico compartido."""
        self.harmony = harmony if harmony is not None else HarmonyEngine()

    def advance_bar(self) -> str:
        """Avanza la progresión armónica una posición.

        Debe llamarse exactamente una vez al completar un compás, desde el
        secuenciador o director de arreglos; nunca desde cada fotograma.
        """
        return self.harmony.advance_chord()

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        """Limita un valor al intervalo indicado."""
        return max(minimum, min(maximum, value))

    def _roles_for_people(self, people_count: int) -> tuple[str, ...]:
        """Devuelve las capas disponibles según el número de participantes."""
        roles = []
        for minimum_people, role in self.ROLE_THRESHOLDS:
            if people_count >= minimum_people:
                roles.append(role)
        return tuple(roles)

    def update(self, state: MusicState) -> MusicDecision:
        """Calcula la decisión musical a partir del estado humano colectivo.

        El movimiento modifica la densidad y la intensidad. La sincronía y la
        interacción colectiva influyen en el modo y en los eventos musicales.
        Ningún parámetro cambia el BPM ni crea relojes individuales.
        """
        if not isinstance(state, MusicState):
            raise TypeError("state debe ser una instancia de MusicState.")

        people = state.people_count
        chord = self.harmony.current_chord

        # --------------------------------------------------------
        # Estado 1: espacio vacío
        # --------------------------------------------------------
        if people == 0:
            return MusicDecision(
                mode="silence",
                chord=chord,
                bass_enabled=False,
                drums_enabled=False,
                harmony_enabled=False,
                melody_density=0.0,
                intensity=0.0,
                active_roles=(),
                events=["fade_out_layers", "keep_global_clock"],
            )

        # --------------------------------------------------------
        # Estado 2: asignación progresiva de capas
        # --------------------------------------------------------
        roles = self._roles_for_people(people)
        bass_enabled = "bass" in roles
        drums_enabled = "drums" in roles
        harmony_enabled = "harmony" in roles

        # La sincronía elevada y la proximidad/interacción detectada indican
        # una experiencia colectiva más conectada. El contacto es una
        # estimación visual, no una confirmación física de que se tocaron.
        if people >= 2 and state.contact_detected:
            mode = "connection"
        elif people >= 2:
            mode = "exploration"
        else:
            mode = "solo"

        # La densidad responde principalmente al movimiento. La sincronía
        # añade un pequeño impulso colectivo, sin convertirla en tempo.
        density = 0.25 + (state.movement * 0.52) + (state.synchrony * 0.10)
        density += state.direction_change * 0.08
        density += state.acceleration * 0.06
        if mode == "connection":
            density += 0.05
        if state.motion_phase == "attack":
            density += 0.08 + state.motion_onset * 0.10
        elif state.motion_phase == "release":
            density *= 0.72
        elif state.motion_phase == "stillness":
            density *= 0.55
        density = self._clamp(density, 0.08, 0.95)

        # La apertura de brazos modifica la intensidad expresiva. Se evita
        # que un único parámetro lleve la mezcla al máximo demasiado pronto.
        intensity = (
            0.20
            + state.movement * 0.42
            + state.direction_change * 0.12
            + state.acceleration * 0.10
            + state.arm_opening * 0.15
            + state.synchrony * 0.10
        )
        if mode == "connection":
            intensity += 0.05
        if state.motion_phase == "attack":
            intensity += 0.12 + state.motion_onset * 0.12
        elif state.motion_phase == "release":
            intensity *= 0.78
        elif state.motion_phase == "stillness":
            intensity *= 0.65
        intensity = self._clamp(intensity, 0.08, 0.95)

        # --------------------------------------------------------
        # Eventos semánticos para el secuenciador/arreglista
        # --------------------------------------------------------
        events = ["shared_tempo", "quantized_changes", f"motion_phase:{state.motion_phase}"]
        if state.direction_change >= 0.35:
            events.append("movement_direction_change")
        if state.acceleration >= 0.35:
            events.append("movement_acceleration")
        if state.motion_phase == "attack":
            events.append("motion_phrase_attack")
        elif state.motion_phase == "release":
            events.append("motion_phrase_release")
        elif state.motion_phase == "stillness":
            events.append("motion_phrase_stillness")

        if mode == "solo":
            events.append("play_individual_melody")
        elif mode == "exploration":
            events.append("develop_collective_groove")
            if state.synchrony >= 0.5:
                events.append("introduce_synchronized_variation")
        else:
            events.extend((
                "activate_shared_chord",
                "synchronize_bass_and_drums",
                "increase_collective_variation",
            ))

        if bass_enabled:
            events.append("enable_bass_layer")
        if drums_enabled:
            events.append("enable_synthfont_drums")
        if harmony_enabled:
            events.append("enable_harmonic_layer")

        return MusicDecision(
            mode=mode,
            chord=chord,
            bass_enabled=bass_enabled,
            drums_enabled=drums_enabled,
            harmony_enabled=harmony_enabled,
            melody_density=density,
            intensity=intensity,
            active_roles=roles,
            events=events,
        )


# ============================================================
# 4. PRUEBAS MANUALES DEL DIRECTOR
# ============================================================

if __name__ == "__main__":
    director = MusicDirector()

    scenarios = [
        ("Sin personas", MusicState()),
        ("Una persona", MusicState(people_count=1, movement=0.20)),
        ("Dos personas", MusicState(people_count=2, movement=0.45, synchrony=0.20)),
        ("Dos personas sincronizadas", MusicState(people_count=2, movement=0.65, synchrony=0.80)),
        ("Tres personas: entra batería", MusicState(people_count=3, movement=0.70, synchrony=0.60)),
        ("Cuatro personas: entra armonía", MusicState(people_count=4, movement=0.85, arm_opening=0.70, synchrony=0.80)),
        ("Interacción colectiva", MusicState(people_count=3, contact_detected=True, movement=0.90, arm_opening=0.80, synchrony=0.90)),
    ]

    print("=" * 60)
    print("RESONANTIA - PRUEBA DEL DIRECTOR MUSICAL")
    print("=" * 60)

    for scenario_name, scenario_state in scenarios:
        decision = director.update(scenario_state)
        print(f"\n--- {scenario_name} ---")
        print(f"Modo: {decision.mode}")
        print(f"Acorde: {decision.chord}")
        print(f"Roles activos: {', '.join(decision.active_roles) or 'ninguno'}")
        print(f"Bajo: {decision.bass_enabled}")
        print(f"Batería: {decision.drums_enabled}")
        print(f"Armonía: {decision.harmony_enabled}")
        print(f"Densidad melódica: {decision.melody_density:.2f}")
        print(f"Intensidad: {decision.intensity:.2f}")
        print(f"Eventos: {', '.join(decision.events)}")

    print("\n--- Prueba de progresión armónica ---")
    for _ in range(4):
        print(f"Acorde actual: {director.harmony.current_chord}")
        director.advance_bar()

    print("\n--- Pruebas de validación ---")
    invalid_cases = [
        {"people_count": -1},
        {"people_count": 1, "synchrony": 1.5},
        {"people_count": 1, "movement": -0.1},
    ]
    for case in invalid_cases:
        try:
            MusicState(**case)
        except (TypeError, ValueError) as error:
            print(f"Validación correcta para {case}: {error}")
        else:
            raise AssertionError(f"La validación no rechazó {case}")

    print("\nTodas las pruebas del director finalizaron correctamente.")
