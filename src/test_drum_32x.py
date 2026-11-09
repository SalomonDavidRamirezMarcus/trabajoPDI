"""
Prueba aislada del preset 32X DAC del SoundFont de RESONANTIA.

Guardar como: src/test_drum_32x.py
Ejecutar desde la carpeta raíz del proyecto:
    python src/test_drum_32x.py

Prueba el banco/preset mostrado en FL Studio:
    Banco 0x4000 (16384), programa 0x5C (92)

NOTA: C5/D5/E5 se prueban inicialmente como MIDI 72/74/76.
La numeración de octavas puede variar entre programas.
"""

import ctypes
import os
import time
from pathlib import Path

import numpy as np
import sounddevice as sd


SAMPLE_RATE = 44100
BLOCK_SIZE = 512
SOUNDFONT_NAME = "The_Absolute_Sega_FM_Soundfont_V2.sf2"

# Identificadores leídos de la captura de FL Studio.
BANK = 0x4000
PRESET = 0x5C

# Mapeo provisional según la referencia C5/D5/E5 del usuario.
DRUM_CHANNEL = 9  # Canal MIDI 10; los índices de FluidSynth empiezan en 0.
DRUM_NOTES = {
    "KICK (C5)": 72,
    "HI-HAT (D5)": 74,
    "SNARE (E5)": 76,
}


def configure_dll(dll):
    """Declara las firmas ctypes utilizadas en esta prueba."""
    dll.new_fluid_settings.restype = ctypes.c_void_p

    dll.fluid_settings_setnum.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double
    ]
    dll.fluid_settings_setnum.restype = ctypes.c_int

    dll.fluid_settings_setint.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    ]
    dll.fluid_settings_setint.restype = ctypes.c_int

    dll.new_fluid_synth.argtypes = [ctypes.c_void_p]
    dll.new_fluid_synth.restype = ctypes.c_void_p

    dll.fluid_synth_sfload.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    ]
    dll.fluid_synth_sfload.restype = ctypes.c_int

    dll.fluid_synth_program_select.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int
    ]
    dll.fluid_synth_program_select.restype = ctypes.c_int

    dll.fluid_synth_noteon.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int
    ]
    dll.fluid_synth_noteon.restype = ctypes.c_int

    dll.fluid_synth_noteoff.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int
    ]
    dll.fluid_synth_noteoff.restype = ctypes.c_int

    dll.fluid_synth_write_float.argtypes = [
        ctypes.c_void_p, ctypes.c_int,
        ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int
    ]
    dll.fluid_synth_write_float.restype = ctypes.c_int

    dll.delete_fluid_synth.argtypes = [ctypes.c_void_p]
    dll.delete_fluid_synth.restype = None

    dll.delete_fluid_settings.argtypes = [ctypes.c_void_p]
    dll.delete_fluid_settings.restype = None


def main():
    if os.name != "nt":
        raise OSError("Esta prueba está preparada para Windows.")

    project_root = Path(__file__).resolve().parent.parent
    bin_dir = (
        project_root
        / "fluidsynth-v2.6.2-win10-x64-cpp11"
        / "bin"
    )
    sf2_path = project_root / "soundfonts" / SOUNDFONT_NAME
    dll_path = bin_dir / "libfluidsynth-3.dll"

    for path, label in (
        (dll_path, "DLL de FluidSynth"),
        (sf2_path, "SoundFont"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"No se encontró {label}: {path}")

    dll_directory = os.add_dll_directory(str(bin_dir))
    settings = None
    synth = None
    stream = None

    try:
        dll = ctypes.CDLL(str(dll_path))
        configure_dll(dll)

        settings = dll.new_fluid_settings()
        if not settings:
            raise RuntimeError("No se pudieron crear los ajustes de FluidSynth.")

        dll.fluid_settings_setnum(
            settings, b"synth.sample-rate", float(SAMPLE_RATE)
        )
        dll.fluid_settings_setnum(settings, b"synth.gain", 0.7)
        dll.fluid_settings_setint(settings, b"synth.polyphony", 128)

        synth = dll.new_fluid_synth(settings)
        if not synth:
            raise RuntimeError("No se pudo crear el sintetizador.")

        sfid = dll.fluid_synth_sfload(
            synth, str(sf2_path).encode("utf-8"), 1
        )
        if sfid == -1:
            raise RuntimeError("FluidSynth no pudo cargar el SoundFont.")

        print(f"\nSoundFont cargado: {sf2_path.name}")
        print(f"SoundFont ID: {sfid}")
        print(f"Intentando banco {BANK} (0x{BANK:X}), "
              f"programa {PRESET} (0x{PRESET:X})")
        print(f"Canal MIDI: {DRUM_CHANNEL + 1}")

        result = dll.fluid_synth_program_select(
            synth, DRUM_CHANNEL, sfid, BANK, PRESET
        )
        print(f"Resultado de program_select: {result}")
        if result != 0:
            raise RuntimeError(
                "FluidSynth no pudo seleccionar ese banco/programa. "
                "No continúes con la integración hasta revisar el banco."
            )

        def audio_callback(outdata, frames, time_info, status):
            left = (ctypes.c_float * frames)()
            right = (ctypes.c_float * frames)()
            result = dll.fluid_synth_write_float(
                synth, frames,
                left, 0, 1,
                right, 0, 1
            )
            if result != 0:
                outdata.fill(0)
                return
            outdata[:, 0] = np.ctypeslib.as_array(left)
            outdata[:, 1] = np.ctypeslib.as_array(right)

        stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=2,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=audio_callback,
        )
        stream.start()
        time.sleep(0.25)

        print("\nEscucharás tres golpes por separado.")
        for label, midi_note in DRUM_NOTES.items():
            print(f"Reproduciendo {label} — MIDI {midi_note}")
            result = dll.fluid_synth_noteon(
                synth, DRUM_CHANNEL, midi_note, 110
            )
            print(f"  note_on result: {result}")
            time.sleep(0.45)
            dll.fluid_synth_noteoff(synth, DRUM_CHANNEL, midi_note)
            time.sleep(0.55)

        print("\nPrueba terminada.")
        print("Anota si cada sonido corresponde al instrumento esperado.")

    finally:
        if stream is not None:
            stream.stop()
            stream.close()
        if synth:
            dll.delete_fluid_synth(synth)
        if settings:
            dll.delete_fluid_settings(settings)
        dll_directory.close()


if __name__ == "__main__":
    main()
