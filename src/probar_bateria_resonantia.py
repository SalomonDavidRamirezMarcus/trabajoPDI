"""Prueba aislada de batería de RESONANTIA. No abre la cámara."""
import time
from audio_engine import AudioEngine

BPM = 122
BEAT = 60.0 / BPM
BARS = 4  # cuatro compases; duración aproximada: 7,9 segundos
SOUNDFONT = "The_Absolute_Sega_FM_Soundfont_V2.sf2"


def main():
    engine = AudioEngine(
        soundfont_name=SOUNDFONT,
        sample_rate=44100,
        gain=0.7,
        bank=0,
        preset=48,
    )
    try:
        engine.start()
        print("Prueba de batería: kick, snare y hi-hat. Cámara desactivada.")
        print("Reproduciendo 4 compases...")
        start = time.perf_counter()
        total_beats = BARS * 4
        for eighth in range(total_beats * 2):
            target = start + eighth * (BEAT / 2)
            now = time.perf_counter()
            if target > now:
                time.sleep(target - now)
            beat = eighth / 2
            if beat.is_integer() and int(beat) % 4 in (0, 1, 2, 3):
                beat_in_bar = int(beat) % 4
                if beat_in_bar in (0, 1, 2, 3):
                    engine.trigger_drum("kick", 101 if beat_in_bar == 0 else 96)
                if beat_in_bar in (1, 3):
                    engine.trigger_drum("snare", 84)
            engine.trigger_drum("hihat", 48 if eighth % 2 == 0 else 36)
        print("Prueba terminada.")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
