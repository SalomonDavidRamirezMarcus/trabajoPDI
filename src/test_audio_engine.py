from audio_engine import AudioEngine
import time

audio = AudioEngine()

try:
    audio.start()

    print("Probando melodía...")
    audio.note_on(60, 100, channel=0)
    time.sleep(0.5)
    audio.note_off(60, channel=0)

    print("Probando batería...")
    audio.trigger_drum("kick")
    time.sleep(0.5)

    audio.trigger_drum("hihat")
    time.sleep(0.5)

    audio.trigger_drum("snare")
    time.sleep(1)

finally:
    audio.close()