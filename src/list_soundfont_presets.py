
"""
Diagnóstico completo de bancos y presets del SoundFont de RESONANTIA.

Guardar como:
    src/list_soundfont_presets.py

Ejecutar desde la raíz del proyecto:
    python src/list_soundfont_presets.py

Busca todos los presets de voz y muestra el banco/programa
real que FluidSynth reconoce.
"""

import ctypes
import os
from pathlib import Path

SOUNDFONT_NAME = "The_Absolute_Sega_FM_Soundfont_V2.sf2"

# Palabras clave para identificar sonidos de voz.
VOICE_KEYWORDS = (
    "VOICE",
    "VOCAL",
    "VOCALS",
    "SPEECH",
    "TALK",
    "SING",
    "SINGER",
    "CHOIR",
    "HUMAN",
    "FORMANT",
    "VOWEL",
)


def main():
    if os.name != "nt":
        raise OSError("Este diagnóstico está preparado para Windows.")

    root = Path(__file__).resolve().parent.parent

    bin_dir = (
        root
        / "fluidsynth-v2.6.2-win10-x64-cpp11"
        / "bin"
    )

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

        # --------------------------------------------------
        # Configuración de FluidSynth
        # --------------------------------------------------

        dll.new_fluid_settings.restype = ctypes.c_void_p

        dll.fluid_settings_setnum.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_double,
        ]
        dll.fluid_settings_setnum.restype = ctypes.c_int

        dll.new_fluid_synth.argtypes = [ctypes.c_void_p]
        dll.new_fluid_synth.restype = ctypes.c_void_p

        dll.fluid_synth_sfload.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        dll.fluid_synth_sfload.restype = ctypes.c_int

        # --------------------------------------------------
        # Acceso a los presets del SoundFont
        # --------------------------------------------------

        dll.fluid_synth_get_sfont_by_id.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        dll.fluid_synth_get_sfont_by_id.restype = ctypes.c_void_p

        dll.fluid_sfont_iteration_start.argtypes = [
            ctypes.c_void_p
        ]
        dll.fluid_sfont_iteration_start.restype = None

        dll.fluid_sfont_iteration_next.argtypes = [
            ctypes.c_void_p
        ]
        dll.fluid_sfont_iteration_next.restype = ctypes.c_void_p

        dll.fluid_preset_get_banknum.argtypes = [
            ctypes.c_void_p
        ]
        dll.fluid_preset_get_banknum.restype = ctypes.c_int

        dll.fluid_preset_get_num.argtypes = [
            ctypes.c_void_p
        ]
        dll.fluid_preset_get_num.restype = ctypes.c_int

        dll.fluid_preset_get_name.argtypes = [
            ctypes.c_void_p
        ]
        dll.fluid_preset_get_name.restype = ctypes.c_char_p

        # --------------------------------------------------
        # Liberación de recursos
        # --------------------------------------------------

        dll.delete_fluid_synth.argtypes = [
            ctypes.c_void_p
        ]
        dll.delete_fluid_synth.restype = None

        dll.delete_fluid_settings.argtypes = [
            ctypes.c_void_p
        ]
        dll.delete_fluid_settings.restype = None

        # --------------------------------------------------
        # Crear sintetizador y cargar SoundFont
        # --------------------------------------------------

        settings = dll.new_fluid_settings()

        if not settings:
            raise RuntimeError(
                "No se pudieron crear los ajustes."
            )

        dll.fluid_settings_setnum(
            settings,
            b"synth.sample-rate",
            44100.0,
        )

        synth = dll.new_fluid_synth(settings)

        if not synth:
            raise RuntimeError(
                "No se pudo crear FluidSynth."
            )

        sfid = dll.fluid_synth_sfload(
            synth,
            str(sf2_path).encode("utf-8"),
            1,
        )

        if sfid == -1:
            raise RuntimeError(
                "No se pudo cargar el SoundFont."
            )

        sfont = dll.fluid_synth_get_sfont_by_id(
            synth,
            sfid,
        )

        if not sfont:
            raise RuntimeError(
                "No se pudo acceder al SoundFont."
            )

        print("\nSoundFont:", sf2_path.name)
        print("SoundFont ID:", sfid)

        print("\n" + "=" * 90)
        print("TODOS LOS BANCOS Y PRESETS")
        print("=" * 90)

        presets = []
        banks = set()

        dll.fluid_sfont_iteration_start(sfont)

        while True:
            preset_ptr = dll.fluid_sfont_iteration_next(
                sfont
            )

            if not preset_ptr:
                break

            bank = dll.fluid_preset_get_banknum(
                preset_ptr
            )

            program = dll.fluid_preset_get_num(
                preset_ptr
            )

            raw_name = dll.fluid_preset_get_name(
                preset_ptr
            )

            name = (
                raw_name.decode(
                    "utf-8",
                    errors="replace",
                )
                if raw_name
                else "(sin nombre)"
            )

            presets.append((bank, program, name))
            banks.add(bank)

        # --------------------------------------------------
        # Mostrar bancos disponibles
        # --------------------------------------------------

        print("\nBANCOS ENCONTRADOS:")
        print("-" * 90)

        for bank in sorted(banks):
            cantidad = sum(
                1 for b, _, _ in presets if b == bank
            )

            print(
                f"Banco {bank:5d} "
                f"| Hex 0x{bank:02X} "
                f"| Presets: {cantidad}"
            )

        # --------------------------------------------------
        # Mostrar todos los presets
        # --------------------------------------------------

        print("\nLISTADO COMPLETO:")
        print("-" * 90)

        for bank, program, name in sorted(
            presets,
            key=lambda item: (
                item[0],
                item[1],
                item[2],
            ),
        ):
            print(
                f"Banco {bank:5d} "
                f"| Programa {program:3d} "
                f"| Bank Hex 0x{bank:02X} "
                f"| Program Hex 0x{program:02X} "
                f"| {name}"
            )

        # --------------------------------------------------
        # Buscar presets relacionados con voz
        # --------------------------------------------------

        voice_matches = []

        for bank, program, name in presets:
            upper_name = name.upper()

            if any(
                keyword in upper_name
                for keyword in VOICE_KEYWORDS
            ):
                voice_matches.append(
                    (bank, program, name)
                )

        print("\n" + "=" * 90)
        print("PRESETS RELACIONADOS CON VOZ")
        print("=" * 90)

        if voice_matches:
            for bank, program, name in voice_matches:
                print(
                    f"Nombre: {name}\n"
                    f"Banco decimal: {bank}\n"
                    f"Programa decimal: {program}\n"
                    f"Banco hexadecimal: 0x{bank:02X}\n"
                    f"Programa hexadecimal: 0x{program:02X}\n"
                    + "-" * 60
                )
        else:
            print(
                "No se encontraron nombres que coincidan "
                "con las palabras clave."
            )

        print("\nTotal de presets:", len(presets))
        print("Total de bancos:", len(banks))

        print(
            "\nCopia el resultado completo, "
            "especialmente la sección de voz."
        )

    finally:
        if synth:
            dll.delete_fluid_synth(synth)

        if settings:
            dll.delete_fluid_settings(settings)

        dll_directory.close()


if __name__ == "__main__":
    main()
