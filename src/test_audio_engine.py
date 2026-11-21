"""Prueba manual de audio; no se ejecuta al descubrir automáticamente unittest.

Para escuchar el motor en Windows con FluidSynth/SoundFont configurados:
    python -m unittest src.test_audio_engine -v
La prueba se omite si RESONANTIA_AUDIO_TEST no está definido en 1.
"""
import os
import time
import unittest

from audio_engine import AudioEngine


@unittest.skipUnless(
    os.environ.get("RESONANTIA_AUDIO_TEST") == "1",
    "Prueba de hardware opcional: define RESONANTIA_AUDIO_TEST=1 para ejecutarla.",
)
class AudioEngineSmokeTest(unittest.TestCase):
    def test_basic_notes_and_drums(self):
        audio = AudioEngine()
        try:
            audio.start()
            audio.note_on(60, 90, channel=0)
            time.sleep(0.25)
            audio.note_off(60, channel=0)
            for drum in ("kick", "hihat", "snare"):
                audio.trigger_drum(drum)
                time.sleep(0.2)
        finally:
            audio.close()


if __name__ == "__main__":
    unittest.main()
