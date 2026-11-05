
"""
RESONANTIA - Motor de audio
Integra FluidSynth con Python para reproducir instrumentos SoundFont.

No necesita FL Studio ni loopMIDI.
"""

import os
import ctypes
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd


class AudioEngine:
    """Motor de reproducción musical de Resonantia."""

    def __init__(
        self,
        soundfont_name="The_Absolute_Sega_FM_Soundfont_V2.sf2",
        sample_rate=44100,
        gain=0.7,
        bank=0,
        preset=0
    ):
        self.sample_rate = sample_rate
        self.gain = gain
        self.bank = bank
        self.preset = preset

        self.root_dir = Path(__file__).resolve().parent.parent

        self.bin_dir = (
            self.root_dir
            / "fluidsynth-v2.6.2-win10-x64-cpp11"
            / "bin"
        )

        self.soundfont_path = (
            self.root_dir
            / "soundfonts"
            / soundfont_name
        )

        self.synth = None
        self.settings = None
        self.stream = None
        self.soundfont_id = None
        self.dll = None
        self._dll_directory = None
        self._lock = threading.Lock()
        self._running = False

        self._load_library()
        self._configure_functions()
        self._initialize_synth()

    # ---------------------------------------------------------
    # 1. CARGAR FLUIDSYNTH
    # ---------------------------------------------------------

    def _load_library(self):

        if os.name != "nt":
            raise OSError(
                "Esta configuración de FluidSynth está preparada "
                "para Windows."
            )

        dll_path = self.bin_dir / "libfluidsynth-3.dll"

        if not dll_path.exists():
            raise FileNotFoundError(
                f"No se encontró FluidSynth: {dll_path}"
            )

        if not self.soundfont_path.exists():
            raise FileNotFoundError(
                f"No se encontró el SoundFont: {self.soundfont_path}"
            )

        # Permite encontrar las DLL dependientes.
        self._dll_directory = os.add_dll_directory(
            str(self.bin_dir)
        )

        self.dll = ctypes.CDLL(str(dll_path))

    # ---------------------------------------------------------
    # 2. CONFIGURAR FUNCIONES DE LA BIBLIOTECA
    # ---------------------------------------------------------

    def _configure_functions(self):

        dll = self.dll

        dll.new_fluid_settings.restype = ctypes.c_void_p

        dll.fluid_settings_setnum.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_double
        ]
        dll.fluid_settings_setnum.restype = ctypes.c_int

        dll.fluid_settings_setint.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int
        ]
        dll.fluid_settings_setint.restype = ctypes.c_int

        dll.new_fluid_synth.argtypes = [
            ctypes.c_void_p
        ]
        dll.new_fluid_synth.restype = ctypes.c_void_p

        dll.fluid_synth_sfload.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int
        ]
        dll.fluid_synth_sfload.restype = ctypes.c_int

        dll.fluid_synth_program_select.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int
        ]
        dll.fluid_synth_program_select.restype = ctypes.c_int

        dll.fluid_synth_noteon.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int
        ]
        dll.fluid_synth_noteon.restype = ctypes.c_int

        dll.fluid_synth_noteoff.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int
        ]
        dll.fluid_synth_noteoff.restype = ctypes.c_int

        dll.fluid_synth_all_sounds_off.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int
        ]
        dll.fluid_synth_all_sounds_off.restype = ctypes.c_int

        dll.fluid_synth_set_gain.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float
        ]
        dll.fluid_synth_set_gain.restype = None

        float_pointer = ctypes.POINTER(ctypes.c_float)

        dll.fluid_synth_write_float.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            float_pointer,
            ctypes.c_int,
            ctypes.c_int,
            float_pointer,
            ctypes.c_int,
            ctypes.c_int
        ]
        dll.fluid_synth_write_float.restype = ctypes.c_int

        dll.delete_fluid_synth.argtypes = [ctypes.c_void_p]
        dll.delete_fluid_synth.restype = None

        dll.delete_fluid_settings.argtypes = [ctypes.c_void_p]
        dll.delete_fluid_settings.restype = None

    # ---------------------------------------------------------
    # 3. INICIALIZAR EL SINTETIZADOR
    # ---------------------------------------------------------

    def _initialize_synth(self):

        self.settings = self.dll.new_fluid_settings()

        if not self.settings:
            raise RuntimeError(
                "No se pudieron crear los ajustes de FluidSynth."
            )

        self.dll.fluid_settings_setnum(
            self.settings,
            b"synth.sample-rate",
            float(self.sample_rate)
        )

        self.dll.fluid_settings_setnum(
            self.settings,
            b"synth.gain",
            float(self.gain)
        )

        self.dll.fluid_settings_setint(
            self.settings,
            b"synth.polyphony",
            256
        )

        self.synth = self.dll.new_fluid_synth(
            self.settings
        )

        if not self.synth:
            raise RuntimeError(
                "No se pudo inicializar el sintetizador."
            )

        self.soundfont_id = self.dll.fluid_synth_sfload(
            self.synth,
            str(self.soundfont_path).encode("utf-8"),
            1
        )

        if self.soundfont_id == -1:
            raise RuntimeError(
                "FluidSynth no pudo cargar el SoundFont."
            )

        self.select_instrument(self.bank, self.preset)

        print("RESONANTIA: motor de audio inicializado.")
        print(f"SoundFont: {self.soundfont_path.name}")
        print(f"Frecuencia: {self.sample_rate} Hz")

    # ---------------------------------------------------------
    # 4. SELECCIONAR INSTRUMENTO
    # ---------------------------------------------------------

    def select_instrument(self, bank=0, preset=0, channel=0):

        with self._lock:

            result = self.dll.fluid_synth_program_select(
                self.synth,
                channel,
                self.soundfont_id,
                bank,
                preset
            )

        if result != 0:
            raise RuntimeError(
                f"No se pudo seleccionar el instrumento "
                f"bank={bank}, preset={preset}."
            )

        self.bank = bank
        self.preset = preset

        print(
            f"Instrumento seleccionado: "
            f"banco {bank}, programa {preset}"
        )

    # ---------------------------------------------------------
    # 5. CONTROLAR NOTAS MIDI
    # ---------------------------------------------------------

    def note_on(self, midi_note, velocity=90, channel=0):

        if not 0 <= midi_note <= 127:
            raise ValueError("La nota MIDI debe estar entre 0 y 127.")

        if not 1 <= velocity <= 127:
            raise ValueError("La velocidad debe estar entre 1 y 127.")

        with self._lock:

            result = self.dll.fluid_synth_noteon(
                self.synth,
                channel,
                midi_note,
                velocity
            )

        if result != 0:
            raise RuntimeError("No se pudo iniciar la nota.")

    def note_off(self, midi_note, channel=0):

        with self._lock:

            result = self.dll.fluid_synth_noteoff(
                self.synth,
                channel,
                midi_note
            )


            print(f"NOTE OFF MIDI {midi_note}: resultado {result}")

            return result

    def all_sounds_off(self, channel=0):

        with self._lock:

            self.dll.fluid_synth_all_sounds_off(
                self.synth,
                channel
            )

    # ---------------------------------------------------------
    # 6. GENERAR AUDIO EN TIEMPO REAL
    # ---------------------------------------------------------

    def _audio_callback(self, outdata, frames, time_info, status):

        left = (ctypes.c_float * frames)()
        right = (ctypes.c_float * frames)()

        with self._lock:

            result = self.dll.fluid_synth_write_float(
                self.synth,
                frames,
                left,
                0,
                1,
                right,
                0,
                1
            )

        if result != 0:
            outdata.fill(0)
            return

        left_array = np.ctypeslib.as_array(left)
        right_array = np.ctypeslib.as_array(right)

        outdata[:, 0] = left_array
        outdata[:, 1] = right_array

    # ---------------------------------------------------------
    # 7. INICIAR Y DETENER AUDIO
    # ---------------------------------------------------------

    def start(self):

        if self._running:
            return

        self.stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=2,
            dtype="float32",
            blocksize=512,
            callback=self._audio_callback
        )

        self.stream.start()
        self._running = True

        print("RESONANTIA: salida de audio activa.")

    def stop(self):

        if self.stream is not None:

            self.stream.stop()
            self.stream.close()
            self.stream = None

        self._running = False
        self.all_sounds_off()

        print("RESONANTIA: audio detenido.")

    # ---------------------------------------------------------
    # 8. CERRAR MOTOR
    # ---------------------------------------------------------

    def close(self):

        self.stop()

        if self.synth:
            self.dll.delete_fluid_synth(self.synth)
            self.synth = None

        if self.settings:
            self.dll.delete_fluid_settings(self.settings)
            self.settings = None

        if self._dll_directory:
            self._dll_directory.close()
            self._dll_directory = None

        print("RESONANTIA: motor cerrado correctamente.")
