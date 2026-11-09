"""
Diagnóstico de presets disponibles en el SoundFont de RESONANTIA.

Guardar como: src/list_soundfont_presets.py
Ejecutar desde la raíz del proyecto:
    python src/list_soundfont_presets.py

Busca el nombre 32X DAC y muestra el banco/programa REAL que
FluidSynth encuentra dentro del archivo SF2.
"""

import ctypes
import os
from pathlib import Path

SOUNDFONT_NAME = "The_Absolute_Sega_FM_Soundfont_V2.sf2"


def main():
    if os.name != "nt":
        raise OSError("Este diagnóstico está preparado para Windows.")

    root = Path(__file__).resolve().parent.parent
    bin_dir = root / "fluidsynth-v2.6.2-win10-x64-cpp11" / "bin"
    sf2_path = root / "soundfonts" / SOUNDFONT_NAME
    dll_path = bin_dir / "libfluidsynth-3.dll"

    if not dll_path.exists():
        raise FileNotFoundError(f"No se encontró: {dll_path}")
    if not sf2_path.exists():
        raise FileNotFoundError(f"No se encontró: {sf2_path}")

    dll_directory = os.add_dll_directory(str(bin_dir))
    settings = None
    synth = None

    try:
        dll = ctypes.CDLL(str(dll_path))

        dll.new_fluid_settings.restype = ctypes.c_void_p
        dll.fluid_settings_setnum.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double
        ]
        dll.fluid_settings_setnum.restype = ctypes.c_int
        dll.new_fluid_synth.argtypes = [ctypes.c_void_p]
        dll.new_fluid_synth.restype = ctypes.c_void_p
        dll.fluid_synth_sfload.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
        ]
        dll.fluid_synth_sfload.restype = ctypes.c_int

        # Funciones para recorrer los presets contenidos en el SoundFont.
        dll.fluid_synth_get_sfont_by_id.argtypes = [
            ctypes.c_void_p, ctypes.c_int
        ]
        dll.fluid_synth_get_sfont_by_id.restype = ctypes.c_void_p

        dll.fluid_sfont_iteration_start.argtypes = [ctypes.c_void_p]
        dll.fluid_sfont_iteration_start.restype = None

        dll.fluid_sfont_iteration_next.argtypes = [ctypes.c_void_p]
        dll.fluid_sfont_iteration_next.restype = ctypes.c_void_p

        dll.fluid_preset_get_banknum.argtypes = [ctypes.c_void_p]
        dll.fluid_preset_get_banknum.restype = ctypes.c_int

        dll.fluid_preset_get_num.argtypes = [ctypes.c_void_p]
        dll.fluid_preset_get_num.restype = ctypes.c_int

        dll.fluid_preset_get_name.argtypes = [ctypes.c_void_p]
        dll.fluid_preset_get_name.restype = ctypes.c_char_p

        dll.delete_fluid_synth.argtypes = [ctypes.c_void_p]
        dll.delete_fluid_synth.restype = None
        dll.delete_fluid_settings.argtypes = [ctypes.c_void_p]
        dll.delete_fluid_settings.restype = None

        settings = dll.new_fluid_settings()
        if not settings:
            raise RuntimeError("No se pudieron crear los ajustes.")

        dll.fluid_settings_setnum(
            settings, b"synth.sample-rate", 44100.0
        )

        synth = dll.new_fluid_synth(settings)
        if not synth:
            raise RuntimeError("No se pudo crear FluidSynth.")

        sfid = dll.fluid_synth_sfload(
            synth, str(sf2_path).encode("utf-8"), 1
        )
        if sfid == -1:
            raise RuntimeError("No se pudo cargar el SoundFont.")

        sfont = dll.fluid_synth_get_sfont_by_id(synth, sfid)
        if not sfont:
            raise RuntimeError("No se pudo acceder al SoundFont cargado.")

        print(f"\nSoundFont: {sf2_path.name}")
        print(f"SoundFont ID: {sfid}")
        print("\nPRESETS QUE FLUIDSYNTH RECONOCE")
        print("-" * 72)

        matches = []
        total = 0

        dll.fluid_sfont_iteration_start(sfont)
        while True:
            preset_ptr = dll.fluid_sfont_iteration_next(sfont)
            if not preset_ptr:
                break

            bank = dll.fluid_preset_get_banknum(preset_ptr)
            program = dll.fluid_preset_get_num(preset_ptr)
            raw_name = dll.fluid_preset_get_name(preset_ptr)
            name = raw_name.decode("utf-8", errors="replace") if raw_name else "(sin nombre)"

            total += 1
            if "32X" in name.upper() or "DAC" in name.upper():
                matches.append((bank, program, name))

        print(f"Total de presets encontrados: {total}")

        if matches:
            print("\nCOINCIDENCIAS CON '32X' O 'DAC':")
            for bank, program, name in matches:
                print(
                    f"Nombre: {name}\n"
                    f"Banco decimal: {bank}\n"
                    f"Programa decimal: {program}\n"
                    f"Banco hexadecimal: 0x{bank:X}\n"
                    f"Programa hexadecimal: 0x{program:X}\n"
                    + "-" * 50
                )
        else:
            print("\nNo apareció ningún nombre que contenga 32X o DAC.")
            print("Se muestran los primeros 40 presets para inspección:")

            # Reiniciar la iteración para imprimir una muestra.
            shown = 0
            dll.fluid_sfont_iteration_start(sfont)
            while shown < 40:
                preset_ptr = dll.fluid_sfont_iteration_next(sfont)
                if not preset_ptr:
                    break
                bank = dll.fluid_preset_get_banknum(preset_ptr)
                program = dll.fluid_preset_get_num(preset_ptr)
                raw_name = dll.fluid_preset_get_name(preset_ptr)
                name = raw_name.decode("utf-8", errors="replace") if raw_name else "(sin nombre)"
                print(f"Banco {bank:5d} | Programa {program:3d} | {name}")
                shown += 1

        print("\nCopia aquí todo el resultado, especialmente las coincidencias.")

    finally:
        if synth:
            dll.delete_fluid_synth(synth)
        if settings:
            dll.delete_fluid_settings(settings)
        dll_directory.close()


if __name__ == "__main__":
    main()
