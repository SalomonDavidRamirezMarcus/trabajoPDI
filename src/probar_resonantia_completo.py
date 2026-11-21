"""Audicion completa de RESONANTIA sin camara ni interfaz visual.
Ejecutar desde la raiz del repositorio: python src/probar_resonantia_completo.py
"""
import heapq
import time
import itertools

from audio_engine import AudioEngine
import music_sequencer
from music_sequencer import MusicSequencer
from music_director import MusicState

# Sonidos de bateria elegidos y confirmados por Jose al escucharlos.
DRUM_NOTES = {
    "kick": 74,
    "hihat": 70,
    "snare": 77,
}

BARS = 16                 # Aproximadamente 31 segundos a 122 BPM
SOUNDFONT = "The_Absolute_Sega_FM_Soundfont_V2.sf2"
MELODIC_BANK = 0
MELODIC_PRESET = 48        # Piano/acoustic grand usado en la prueba anterior


def main():
    # Actualiza las dos referencias: el generador de eventos y el motor MIDI.
    music_sequencer.DRUM_NOTES.update(DRUM_NOTES)
    AudioEngine.DRUM_NOTES = DRUM_NOTES.copy()

    sequencer = MusicSequencer()
    bpm = sequencer.bpm
    beat_seconds = 60.0 / bpm
    bar_seconds = beat_seconds * 4


    # Estado fijo equivalente a una escena con cuatro participantes activos.
    # Asi se habilitan melodia, bajo, bateria y armonia sin abrir la camara.
    simulated_state = MusicState(
        people_count=4,
        contact_detected=True,
        synchrony=0.85,
        movement=0.85,
        arm_opening=0.75,
    )
    states = [simulated_state for _ in range(BARS)]
    events, _ = sequencer.create_progression(states)

    engine = AudioEngine(
        soundfont_name=SOUNDFONT,
        sample_rate=44100,
        gain=0.7,
        bank=MELODIC_BANK,
        preset=MELODIC_PRESET,
    )

    # Cola de eventos: todos los instrumentos comparten el mismo reloj.
    # Cada item: (tiempo_en_beats, prioridad, tipo, evento)
    queue = []
    event_order = itertools.count()  # Desempate para eventos simultaneos.
    for event in events:
        absolute_beat = (event.bar - 1) * 4 + event.beat
        if event.instrument in DRUM_NOTES:
            heapq.heappush(queue, (absolute_beat, 0, next(event_order), "on", event))
        else:
            heapq.heappush(queue, (absolute_beat, 0, next(event_order), "on", event))
            off_beat = absolute_beat + max(0.05, event.duration_beats)
            heapq.heappush(queue, (off_beat, 1, next(event_order), "off", event))

    total_seconds = BARS * bar_seconds
    print("=" * 58)
    print("RESONANTIA | AUDICION MUSICAL COMPLETA")
    print(f"Tempo: {bpm} BPM | Compas: 4/4 | Compases: {BARS}")
    print(f"Duracion aproximada: {total_seconds:.1f} segundos")
    print("Capas simuladas: melodia + bajo + acordes + bateria")
    print(f"Bateria MIDI: kick {74}, hihat {70}, snare {77}")
    print("Camara e interfaz: desactivadas")
    print("Iniciando reproduccion... (Ctrl+C para detener)")
    print("=" * 58)

    try:
        engine.start()
        start = time.perf_counter() + 0.25
        while queue:
            beat, priority, order, action, event = heapq.heappop(queue)
            target = start + beat * beat_seconds
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

            if action == "off":
                engine.note_off(event.midi_note, channel=engine.MELODIC_CHANNEL)
            elif event.instrument in DRUM_NOTES:
                engine.trigger_drum(event.instrument, event.velocity)
            else:
                engine.note_on(
                    event.midi_note,
                    event.velocity,
                    channel=engine.MELODIC_CHANNEL,
                )

        # Deja sonar el final de las notas y la reverberacion.
        time.sleep(1.5)
        print("Audicion terminada.")
    except KeyboardInterrupt:
        print("Audicion detenida por el usuario.")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
