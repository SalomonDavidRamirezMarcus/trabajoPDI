"""
Audición completa de RESONANTIA sin cámara ni interfaz visual.

Ejecutar desde la raíz del repositorio:
python src/probar_resonantia_completo.py

Este archivo utiliza las notas, duraciones y velocidades que genera
music_sequencer.py para el acompañamiento en tresillos.
"""

import heapq
import time
import itertools

from audio_engine import AudioEngine
import music_sequencer
from music_sequencer import MusicSequencer
from music_director import MusicState


# ============================================================
# BATERÍA ORIGINAL CONFIRMADA
# ============================================================

DRUM_NOTES = {
    "kick": 74,
    "hihat": 70,
    "snare": 77,
}


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

BARS = 16

SOUNDFONT = "The_Absolute_Sega_FM_Soundfont_V2.sf2"

SAMPLE_RATE = 44100
GAIN = 0.7


# ============================================================
# INSTRUMENTOS
# ============================================================

INSTRUMENTS = {
    "melody": (0, 48, 0),
    "bass": (0, 32, 1),
    "chords": (0, 0, 2),

    # OPL4op Brass
    # Banco FluidSynth 5, programa 65.
    # Canal MIDI 4 (índice 3).
    "arpeggio": (5, 65, 3),
}


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def main():

    # Aplicar las notas de batería confirmadas.
    music_sequencer.DRUM_NOTES.update(DRUM_NOTES)
    AudioEngine.DRUM_NOTES = DRUM_NOTES.copy()

    sequencer = MusicSequencer()

    bpm = sequencer.bpm
    beat_seconds = 60.0 / bpm
    bar_seconds = beat_seconds * 4

    # ========================================================
    # ESTADO SIMULADO: CUATRO PARTICIPANTES
    # ========================================================

    simulated_state = MusicState(
        people_count=4,
        contact_detected=True,
        synchrony=0.85,
        movement=0.85,
        arm_opening=0.75,
    )

    states = [simulated_state for _ in range(BARS)]

    events, _ = sequencer.create_progression(states)

    # ========================================================
    # MOTOR DE AUDIO
    # ========================================================

    engine = AudioEngine(
        soundfont_name=SOUNDFONT,
        sample_rate=SAMPLE_RATE,
        gain=GAIN,
        bank=0,
        preset=48,
    )

    # ========================================================
    # COLA DE EVENTOS
    # ========================================================

    queue = []
    event_order = itertools.count()

    for event in events:

        absolute_beat = (
            (event.bar - 1) * 4
            + event.beat
        )

        # ----------------------------------------------------
        # BATERÍA: conservar comportamiento original
        # ----------------------------------------------------

        if event.instrument in DRUM_NOTES:

            heapq.heappush(
                queue,
                (
                    absolute_beat,
                    0,
                    next(event_order),
                    "on",
                    event,
                    None,
                ),
            )

            continue

        # ----------------------------------------------------
        # NOTAS: usar las generadas por music_sequencer
        # ----------------------------------------------------

        midi_note = event.midi_note

        # event.duration_beats está expresado en beats.
        # No convertirlo a segundos ni usar una duración fija.
        duration = max(0.05, event.duration_beats)

        # Evento ON.
        heapq.heappush(
            queue,
            (
                absolute_beat,
                0,
                next(event_order),
                "on",
                event,
                midi_note,
            ),
        )

        # Evento OFF.
        off_beat = absolute_beat + duration

        heapq.heappush(
            queue,
            (
                off_beat,
                1,
                next(event_order),
                "off",
                event,
                midi_note,
            ),
        )

    # ========================================================
    # INFORMACIÓN
    # ========================================================

    total_seconds = BARS * bar_seconds

    print("=" * 60)
    print("RESONANTIA | AUDICIÓN MUSICAL COMPLETA")
    print(f"Tempo: {bpm} BPM")
    print("Compás: 4/4")
    print(f"Compases: {BARS}")
    print(f"Duración aproximada: {total_seconds:.1f} segundos")

    print()
    print("Capas:")
    print("- Melodía original")
    print("- Bajo original")
    print("- Acordes originales")
    print("- Batería original")
    print("- Acompañamiento rítmico en tresillos: OPL4op Brass")

    print()
    print("Acompañamiento: notas, duración y velocidad del secuenciador")
    print("Duración de las notas: según event.duration_beats")

    print(
        f"Batería: kick {DRUM_NOTES['kick']}, "
        f"hihat {DRUM_NOTES['hihat']}, "
        f"snare {DRUM_NOTES['snare']}"
    )

    print()
    print("Cámara: desactivada")
    print("Interfaz: desactivada")
    print("Iniciando reproducción...")
    print("Ctrl+C para detener")
    print("=" * 60)

    # ========================================================
    # REPRODUCCIÓN
    # ========================================================

    try:

        engine.start()

        # Seleccionar cada preset una sola vez.
        for name, config in INSTRUMENTS.items():

            bank, preset, channel = config

            engine.select_instrument(
                bank,
                preset,
                channel,
            )

        start = time.perf_counter() + 0.25

        while queue:

            (
                beat,
                priority,
                order,
                action,
                event,
                midi_note,
            ) = heapq.heappop(queue)

            target = start + beat * beat_seconds

            delay = target - time.perf_counter()

            if delay > 0:
                time.sleep(delay)

            # ------------------------------------------------
            # BATERÍA
            # ------------------------------------------------

            if event.instrument in DRUM_NOTES:

                if action == "on":

                    engine.trigger_drum(
                        event.instrument,
                        event.velocity,
                    )

                continue

            # ------------------------------------------------
            # INSTRUMENTOS MELODICOS
            # ------------------------------------------------

            configuration = INSTRUMENTS.get(
                event.instrument
            )

            if configuration is None:

                print(
                    "Instrumento sin configuración:",
                    event.instrument,
                )

                continue

            bank, preset, channel = configuration

            if action == "off":

                engine.note_off(
                    midi_note,
                    channel=channel,
                )

            else:

                # Subir un poco el volumen percibido SOLO del sinte
                # OPL4op Brass, conservando los acentos del secuenciador.
                # MIDI admite velocidades de 1 a 127.
                if event.instrument == "arpeggio":
                    velocity = min(127, event.velocity + 18)
                else:
                    velocity = event.velocity

                engine.note_on(
                    midi_note,
                    velocity,
                    channel=channel,
                )

        time.sleep(1.5)

        print()
        print("Audición terminada.")

    except KeyboardInterrupt:

        print()
        print("Audición detenida por el usuario.")

    finally:

        engine.close()


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":
    main()
