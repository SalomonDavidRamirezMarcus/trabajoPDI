
"""
RESONANTIA - Integración principal
Cámara + visión artificial + director musical
+ secuenciador + motor FluidSynth.

Ejecutar desde la raíz:
    python main.py
"""

import base64
import queue
import heapq
import itertools
import math
import sys
import time
import threading
from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import cv2
import mediapipe as mp

# Permite utilizar los módulos existentes dentro de src.
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

sys.path.insert(0, str(SRC))

import vision
import logic

from music_director import MusicDirector, MusicState
from music_sequencer import MusicSequencer, MusicalEvent
from audio_engine import AudioEngine
from motion_phrase import MotionPhraseDetector


# ---------------------------------------------------------
# CONFIGURACIÓN MUSICAL
# ---------------------------------------------------------

CAMERA_INDEX = 0
BPM = 122

SOUNDFONT = "The_Absolute_Sega_FM_Soundfont_V2.sf2"

# Instrumentos iniciales del SoundFont.
# Los programas se numeran desde cero.
INSTRUMENTS = {
    "melody": (0, 48),  # Strings
    "bass": (0, 32),    # Acoustic Bass
    "chords": (0, 0),   # Acoustic Piano
    "arpeggio": (5, 65),  # OPL4op Brass: banco FluidSynth 5, programa 65
}

CHANNELS = {
    "melody": 0,
    "bass": 1,
    "chords": 2,
    "arpeggio": 3,
}


# ---------------------------------------------------------
# CONTROLADOR DE AUDIO
# ---------------------------------------------------------

class _NoteOffScheduler:
    """Un único hilo agenda los apagados MIDI; evita un Timer por nota."""

    def __init__(self, callback):
        self.callback = callback
        self.condition = threading.Condition()
        self.queue = []
        self.sequence = itertools.count()
        self.closed = False
        self.thread = threading.Thread(
            target=self._run, name="ResonantiaNoteOff", daemon=True
        )
        self.thread.start()

    def schedule(self, delay, note, channel):
        deadline = time.monotonic() + max(0.0, float(delay))
        with self.condition:
            if self.closed:
                return
            heapq.heappush(
                self.queue, (deadline, next(self.sequence), note, channel)
            )
            self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                while not self.closed and not self.queue:
                    self.condition.wait()
                if self.closed:
                    return
                deadline, _, note, channel = self.queue[0]
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self.condition.wait(timeout=remaining)
                    continue
                heapq.heappop(self.queue)
            try:
                self.callback(note, channel)
            except Exception as exc:
                print(f"RESONANTIA: error al apagar nota: {exc}")

    def close(self):
        with self.condition:
            self.closed = True
            self.queue.clear()
            self.condition.notify_all()
        self.thread.join(timeout=1.5)


class ResonantiaAudio:

    def __init__(self):

        self.engine = AudioEngine(
            soundfont_name=SOUNDFONT,
            sample_rate=44100,
            gain=0.7,
            bank=0,
            preset=48,
        )

        self.engine.start()

        self.lock = threading.Lock()
        self.active = True

        # Seleccionar un instrumento por canal.
        for instrument, (bank, preset) in INSTRUMENTS.items():

            channel = CHANNELS[instrument]

            self.engine.select_instrument(
                bank=bank,
                preset=preset,
                channel=channel,
            )

    def play_event(self, event):

        instrument = event.instrument

        # Percusión sintetizada: no utiliza notas melódicas ni canales SoundFont.
        if instrument in ("kick", "snare", "hihat"):
            self.engine.trigger_drum(instrument, event.velocity)
            return

        channel = CHANNELS.get(instrument)

        if channel is None:
            return

        velocity = max(
            1,
            min(127, int(event.velocity))
        )

        with self.lock:

            self.engine.note_on(
                event.midi_note,
                velocity=velocity,
                channel=channel,
            )

        duration = (
            event.duration_beats * 60.0 / BPM
        )

        # El apagado se programa sin bloquear la cámara.
        threading.Timer(
            duration,
            self.stop_note,
            args=(event.midi_note, channel),
        ).start()

    def stop_note(self, note, channel):

        if not self.active:
            return

        with self.lock:
            self.engine.note_off(
                note,
                channel=channel,
            )

    def silence(self):

        with self.lock:
            for channel in CHANNELS.values():
                self.engine.all_sounds_off(channel)

            # La percusión utiliza el canal MIDI 10 (índice FluidSynth 9).
            self.engine.all_sounds_off(9)

    def close(self):

        self.active = False
        self.silence()
        self.engine.close()


# ---------------------------------------------------------
# REPRODUCCIÓN DE UN COMPÁS
# ---------------------------------------------------------

def play_bar(events, audio, bpm, stop_event=None):
    """Reproduce un compás sin impedir que la sesión se detenga con rapidez."""
    seconds_per_beat = 60.0 / bpm
    start = time.monotonic()

    for event in sorted(events, key=lambda item: item.beat):
        if stop_event is not None and stop_event.is_set():
            return False

        target = start + event.beat * seconds_per_beat
        remaining = target - time.monotonic()
        if remaining > 0:
            if stop_event is not None:
                if stop_event.wait(remaining):
                    return False
            else:
                time.sleep(remaining)

        if stop_event is not None and stop_event.is_set():
            return False
        audio.play_event(event)

    # Espera final del compás también interrumpible.
    remaining = start + 4 * seconds_per_beat - time.monotonic()
    if remaining > 0:
        if stop_event is not None:
            if stop_event.wait(remaining):
                return False
        else:
            time.sleep(remaining)
    return not (stop_event is not None and stop_event.is_set())


# ---------------------------------------------------------
# SISTEMA MUSICAL EN SEGUNDO PLANO
# ---------------------------------------------------------

class MusicWorker:

    def __init__(self, audio):

        self.audio = audio

        self.director = MusicDirector()

        self.sequencer = MusicSequencer(
            self.director
        )

        self.lock = threading.Lock()

        self.current_state = MusicState()
        self.latest_decision = None
        self.latest_events = ()

        # Roles seleccionados en la pantalla previa. La selección se aplica
        # por ID de seguimiento, no por la cantidad fija de capas del director.
        self.person_role_assignments = {
            1: "chords", 2: "bass", 3: "drums", 4: "arpeggio"
        }
        self.detected_person_ids = ()

        self.previous_mode = "silence"

        # Variables expresivas obtenidas del movimiento corporal.
        self.movement = 0.0
        self.arm_opening = 0.0
        self.phrase_detector = MotionPhraseDetector()
        self.motion_phrase = self.phrase_detector.update(0.0, 0.0)

        self.running = True
        self.stop_event = threading.Event()

        self.thread = threading.Thread(
            target=self.run,
            daemon=True,
        )

        self.thread.start()

    def set_person_role_assignments(self, assignments):
        """Configura los roles elegidos para las personas 1 a 4."""
        role_aliases = {
            "piano": "chords", "piano acústico": "chords",
            "acoustic piano": "chords", "acordes": "chords",
            "bajo": "bass", "batería": "drums", "percusión": "drums",
            "sintetizador": "arpeggio", "arpegiador": "arpeggio",
        }
        normalized = {}
        for person, role in (assignments or {}).items():
            try:
                person_id = int(person)
            except (TypeError, ValueError):
                continue
            if not 1 <= person_id <= 4 or not role:
                continue
            role_text = str(role).strip().lower()
            normalized[person_id] = role_aliases.get(role_text, role_text)
        with self.lock:
            self.person_role_assignments = normalized

    def update_state(self, state, movement=0.0, arm_opening=0.0,
                     delta_time=1.0 / 30.0, person_ids=()):

        with self.lock:
            self.current_state = state
            self.detected_person_ids = tuple(person_ids)
            self.motion_phrase = self.phrase_detector.update(movement, delta_time)

            # Suavizado para evitar cambios musicales bruscos entre fotogramas.
            self.movement = (
                self.movement * 0.65
                + max(0.0, min(1.0, movement)) * 0.35
            )
            self.arm_opening = (
                self.arm_opening * 0.65
                + max(0.0, min(1.0, arm_opening)) * 0.35
            )

    def run(self):

        bar_number = 1

        while self.running and not self.stop_event.is_set():

            with self.lock:
                state = self.current_state
                movement = self.movement
                arm_opening = self.arm_opening
                detected_ids = self.detected_person_ids
                assignments = dict(self.person_role_assignments)
                state.movement = movement
                state.arm_opening = arm_opening
                state.motion_phase = self.motion_phrase.phase.value
                state.motion_onset = self.motion_phrase.onset

            # El secuenciador original habilita capas por cantidad (1=melodía,
            # 2=bajo, 3=batería...). Para esta experiencia generamos el abanico
            # completo y luego dejamos SOLO los roles asignados a IDs presentes.
            if state.people_count > 0:
                generation_state = replace(state, people_count=4)
                events, decision = self.sequencer.create_bar(
                    bar_number, generation_state
                )
                # El tracker asigna IDs persistentes 1..N; las tarjetas de
                # instrumentación usan esos mismos IDs. Normalizamos al leer para
                # que una selección no quede descartada por espacios o alias.
                active_roles = {
                    str(assignments.get(int(person_id), "")).strip().lower()
                    for person_id in detected_ids
                    if assignments.get(int(person_id))
                }
                active_roles = {
                    {"piano": "chords", "acordes": "chords",
                     "piano acústico": "chords", "bajo": "bass",
                     "batería": "drums", "percusión": "drums",
                     "arpegiador": "arpeggio"}.get(role, role)
                    for role in active_roles
                }
                allowed_instruments = set()
                if "drums" in active_roles:
                    allowed_instruments.update(("kick", "snare", "hihat"))
                if "bass" in active_roles:
                    allowed_instruments.add("bass")
                if "chords" in active_roles:
                    allowed_instruments.add("chords")
                if "arpeggio" in active_roles:
                    allowed_instruments.add("arpeggio")
                events = [
                    event for event in events
                    if event.instrument in allowed_instruments
                ]

                # PIANO / ACORDES (restaurado desde la lógica musical
                # funcional anterior): esta capa debe sonar cuando el rol
                # "chords" esté asignado a una persona detectada. En el
                # secuenciador actual _create_harmony() está intencionalmente
                # vacío, así que no podemos depender de él para producir notas.
                # Generamos un acorde sostenido al inicio de cada dos compases,
                # respetando la progresión y el canal SoundFont del piano.
                if "chords" in active_roles and bar_number % 2 == 1:
                    chord_name = decision.chord
                    try:
                        chord_pitch_classes = self.sequencer.harmony.get_chord_notes(
                            chord_name
                        )
                    except (AttributeError, TypeError, ValueError):
                        chord_pitch_classes = ()

                    # Sustituimos cualquier evento de acordes que venga del
                    # secuenciador: algunas versiones lo entregan como un toque
                    # corto. La capa de piano debe conservar el acorde durante
                    # los dos compases completos (8 pulsos), como en la versión
                    # funcional anterior. No se modifican los demás instrumentos.
                    events = [
                        event for event in events
                        if event.instrument != "chords"
                    ]
                    for pitch_class in chord_pitch_classes:
                        midi_note = self.sequencer._pitch_class_to_midi(
                            int(pitch_class), 60, 76, reference_note=67
                        )
                        events.append(MusicalEvent(
                            bar=bar_number,
                            beat=0.0,
                            instrument="chords",
                            midi_note=midi_note,
                            duration_beats=8.0,
                            velocity=88,
                            chord=chord_name,
                            mode=decision.mode,
                        ))

                    # El panel y el director reflejan el rol real, no la
                    # habilitación automática por número de participantes.
                    decision.harmony_enabled = True

                decision.bass_enabled = "bass" in active_roles
                decision.drums_enabled = "drums" in active_roles
                decision.harmony_enabled = "chords" in active_roles
                decision.arpeggio_enabled = "arpeggio" in active_roles
                decision.active_roles = tuple(sorted(active_roles))
                decision.melody_density = 0.0
            else:
                events, decision = self.sequencer.create_bar(bar_number, state)

            # El cuerpo modifica la interpretación de cada compás:
            # brazos abiertos = melodía más aguda; movimiento = más energía.
            expressive_events = []
            melody_events = []

            for event in events:
                expressive = event

                if expressive.instrument == "melody":
                    # El piano es un acorde sostenido: no desplazar notas
                    # individuales ni convertir el acorde en acentos/arpegios.
                    expressive = replace(
                        expressive,
                        velocity=min(
                            127,
                            max(1, round(
                                expressive.velocity * (0.75 + movement * 0.45)
                            )),
                        ),
                    )

                elif expressive.instrument in ("bass", "chords", "arpeggio"):
                    expressive = replace(
                        expressive,
                        velocity=min(
                            127,
                            max(1, round(
                                expressive.velocity * (0.80 + movement * 0.35)
                            )),
                        ),
                    )

                expressive_events.append(expressive)

            events = expressive_events
            with self.lock:
                self.latest_decision = decision
                self.latest_events = tuple(events)

            if decision.mode == "silence":

                if self.previous_mode != "silence" and self.audio is not None:
                    self.audio.silence()

                self.previous_mode = "silence"

                if self.stop_event.wait(0.1):
                    break
                continue

            if self.previous_mode == "silence":
                print(
                    f"\nRESONANTIA: modo {decision.mode}"
                )

            elif self.previous_mode != decision.mode:
                if self.audio is not None:
                    self.audio.silence()

                print(
                    f"\nRESONANTIA: cambio a {decision.mode}"
                )

            self.previous_mode = decision.mode

            if self.audio is not None:
                play_bar(
                    events,
                    self.audio,
                    self.sequencer.bpm,
                    self.stop_event,
                )
            else:
                self.stop_event.wait(4 * 60.0 / self.sequencer.bpm)

            # La progresión cambia cada dos compases: cada acorde de piano
            # conserva su armonía durante aproximadamente cuatro segundos.
            if bar_number % 2 == 0:
                self.director.advance_bar()

            bar_number += 1

    def close(self):
        """Interrumpe el compás actual y espera a que termine el hilo musical."""
        self.running = False
        self.stop_event.set()
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=4.0)
        if self.audio is not None:
            try:
                self.audio.silence()
            except Exception as exc:
                print(f"RESONANTIA: no se pudo silenciar al detener: {exc}")


# ---------------------------------------------------------
# INTERPRETACIÓN DEL MOVIMIENTO CORPORAL
# ---------------------------------------------------------

def analyze_movement(valid_poses, tracked_poses, delta_time):
    """Obtiene movimiento y apertura usando landmarks suficientemente visibles."""
    speeds = []
    openings = []

    def visible(landmark, threshold=0.5):
        visibility = getattr(landmark, "visibility", None)
        x, y = getattr(landmark, "x", None), getattr(landmark, "y", None)
        return (
            visibility is not None and visibility >= threshold
            and x is not None and y is not None
            and math.isfinite(float(x)) and math.isfinite(float(y))
        )

    for (_landmarks, _detection), person in zip(valid_poses, tracked_poses):
        vx, vy = person.velocity
        speeds.append(math.hypot(vx, vy))
        landmarks = _landmarks
        if len(landmarks) <= 16:
            continue
        ls, rs, lw, rw = landmarks[11], landmarks[12], landmarks[15], landmarks[16]
        if not all(visible(p) for p in (ls, rs, lw, rw)):
            continue

        shoulder_width = math.hypot(ls.x - rs.x, ls.y - rs.y)
        wrist_width = math.hypot(lw.x - rw.x, lw.y - rw.y)
        if shoulder_width > 0.015:
            openings.append(wrist_width / shoulder_width)

    movement = min(1.0, (sum(speeds) / len(speeds)) / 0.9) if speeds and delta_time > 0 else 0.0
    average_opening = sum(openings) / len(openings) if openings else 0.8
    arm_opening = max(0.0, min(1.0, (average_opening - 0.8) / 1.7))
    return movement, arm_opening


# ---------------------------------------------------------
# INTERFAZ GRAFICA
# ---------------------------------------------------------

class RoundedPanel(tk.Frame):
    """Panel Tk con fondo y borde dibujados en esquinas redondeadas."""
    def __init__(self, parent, background="#191C20", border="#353B42",
                 radius=18, **kwargs):
        super().__init__(parent, bg=background, bd=0, highlightthickness=0, **kwargs)
        self._panel_bg = background
        self._panel_border = border
        self._radius = radius
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=background, bd=0)
        self.window_id = self.canvas.create_window(0, 0, anchor="nw",
                                                  window=self.content)
        self.canvas.bind("<Configure>", self._draw_panel)

    def _draw_panel(self, event=None):
        width = max(2, self.canvas.winfo_width())
        height = max(2, self.canvas.winfo_height())
        radius = min(self._radius, width/2, height/2)
        points = []
        corners = [
            (width-radius, radius, -90, 90),
            (width-radius, height-radius, 0, 90),
            (radius, height-radius, 90, 90),
            (radius, radius, 180, 90),
        ]
        import math as _math
        for cx, cy, start, extent in corners:
            for step in range(9):
                angle = _math.radians(start + extent*step/8)
                points.extend((cx + radius*_math.cos(angle),
                              cy + radius*_math.sin(angle)))
        self.canvas.delete("panel-shape")
        self.canvas.create_polygon(
            points, smooth=True, splinesteps=16,
            fill=self._panel_bg, outline=self._panel_border,
            width=1, tags="panel-shape"
        )
        inset = 9
        self.canvas.coords(self.window_id, inset, inset)
        self.canvas.itemconfigure(
            self.window_id, width=max(1, width-inset*2),
            height=max(1, height-inset*2)
        )
        self.canvas.tag_lower("panel-shape")


class ResonantiaApp:
    """Interfaz de control y visualizacion para la instalacion."""

    def __init__(self, root):
        self.root = root
        self.root.title("Resonantia | Instalacion interactiva")
        self.root.geometry("1440x900")
        self.root.minsize(1120, 720)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.rowconfigure(2, weight=1)

        self.camera_var = tk.StringVar(value=str(CAMERA_INDEX))
        self.audio_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Listo para iniciar.")
        self.count_var = tk.StringVar(value="0")
        self.contacts_var = tk.StringVar(value="0")
        self.sync_var = tk.StringVar(value="—")
        self.movement_var = tk.StringVar(value="0.00")
        self.opening_var = tk.StringVar(value="0.00")
        self.fps_var = tk.StringVar(value="0.0")
        self.mode_var = tk.StringVar(value="En espera")
        self.chord_var = tk.StringVar(value="—")
        self.layers_var = tk.StringVar(value="—")
        self.density_var = tk.StringVar(value="—")
        self.intensity_var = tk.StringVar(value="—")

        self.frame_queue = queue.Queue(maxsize=1)
        self.message_queue = queue.Queue()
        self.latest_snapshot = None
        self.video_photo = None
        self.capture_thread = None
        self.stop_event = None
        self.is_running = False
        self.is_closing = False

        # Solo se ofrecen los cuatro roles que ya existen en el motor.
        # El segundo elemento es la clave del rol, no un preset MIDI nuevo.
        self.instrument_choices = [
            ("Acordes · Piano acústico", "chords"),
            ("Bajo · Acoustic Bass", "bass"),
            ("Batería · Kit 32X DAC", "drums"),
            ("Sintetizador · OPL4op Brass", "arpeggio"),
        ]
        self.person_instruments = {}
        self.selected_player_count = 1
        self.pending_setup_return = False
        self.theme_mode = "dark"
        self.settings_window = None
        self._configure_styles()
        self._show_welcome()
        self.root.after(40, self._poll_updates)

    def _configure_styles(self):
        """Identidad visual RESONANTIA: grafito neutro y naranja otoñal."""
        palettes = {
            "dark": {
                "background": "#101214", "surface": "#191C20",
                "surface_alt": "#24282D", "border": "#353B42",
                "text": "#F4F1EA", "muted": "#A8ADB3",
                "accent": "#D97724", "accent_hover": "#F59E0B",
                "purple": "#E5A84B", "mint": "#A8BFA5",
                "danger": "#B85C2A",
            },
            "light": {
                "background": "#FAFAFC", "surface": "#FFFFFF",
                "surface_alt": "#F1F3F6", "border": "#DCE1E7",
                "text": "#29251F", "muted": "#687080",
                "accent": "#C96F1D", "accent_hover": "#A95612",
                "purple": "#9C6A2D", "mint": "#617D62",
                "danger": "#A94E25",
            },
        }
        self.colors = palettes.get(getattr(self, "theme_mode", "dark"), palettes["dark"])
        c = self.colors
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.configure(bg=c["background"])
        style.configure(".", background=c["background"], foreground=c["text"],
                        font=("Segoe UI", 10), borderwidth=0)
        style.configure("TFrame", background=c["background"])
        style.configure("Card.TFrame", background=c["surface"])
        style.configure("Metric.TFrame", background=c["surface"], relief="flat")
        style.configure("TLabel", background=c["background"], foreground=c["text"])
        style.configure("Brand.TLabel", background=c["background"],
                        foreground=c["accent"], font=("Segoe UI", 27, "bold"))
        style.configure("Eyebrow.TLabel", background=c["background"],
                        foreground=c["muted"], font=("Segoe UI", 9, "bold"))
        style.configure("Subtitle.TLabel", background=c["background"],
                        foreground=c["muted"], font=("Segoe UI", 10))
        style.configure("Video.TLabel", background=c["background"],
                        foreground=c["muted"], font=("Segoe UI", 13))
        style.configure("Status.TLabel", background=c["surface_alt"],
                        foreground=c["purple"], font=("Segoe UI", 9, "bold"),
                        padding=(12, 6))
        style.configure("Section.TLabel", background=c["background"],
                        foreground=c["text"], font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", background=c["background"],
                        foreground=c["muted"], font=("Segoe UI", 9))
        style.configure("MetricTitle.TLabel", background=c["surface"],
                        foreground=c["muted"], font=("Segoe UI", 8))
        style.configure("MetricValue.TLabel", background=c["surface"],
                        foreground=c["accent"], font=("Segoe UI", 16, "bold"))
        style.configure("TLabelFrame", background=c["surface"],
                        foreground=c["text"], bordercolor=c["border"],
                        relief="flat", borderwidth=1, padding=12)
        style.configure("TLabelFrame.Label", background=c["surface"],
                        foreground=c["muted"], font=("Segoe UI", 9, "bold"))
        style.configure("TButton", background=c["surface_alt"],
                        foreground=c["text"], padding=(14, 9),
                        font=("Segoe UI", 9, "bold"), bordercolor=c["surface_alt"],
                        relief="flat")
        style.map("TButton", background=[("active", c["surface_alt"])],
                  foreground=[("disabled", c["muted"])])
        style.configure("Accent.TButton", background=c["accent"],
                        foreground="#1A1016", padding=(17, 10),
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Accent.TButton", background=[("active", c["accent_hover"])])
        style.configure("Stop.TButton", background=c["surface_alt"],
                        foreground=c["danger"], padding=(14, 9), relief="flat")
        style.map("Stop.TButton", background=[("active", c["surface_alt"])])
        style.configure("TCheckbutton", background=c["surface"],
                        foreground=c["text"], padding=(7, 6))
        style.map("TCheckbutton", background=[("active", c["surface"])],
                  foreground=[("active", c["accent"])])
        style.configure("TCombobox", fieldbackground=c["surface_alt"],
                        background=c["surface_alt"], foreground=c["text"],
                        arrowcolor=c["accent"], padding=7, bordercolor=c["border"])
        style.map("TCombobox", fieldbackground=[("readonly", c["surface_alt"])],
                  foreground=[("readonly", c["text"])])
        style.configure("TNotebook", background=c["surface"], borderwidth=0,
                        tabmargins=(4, 5, 4, 0))
        style.configure("TNotebook.Tab", background=c["surface_alt"],
                        foreground=c["muted"], padding=(13, 10),
                        font=("Segoe UI", 9, "bold"), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", c["surface"])],
                  foreground=[("selected", c["accent"])])
        style.configure("Treeview", background=c["surface"],
                        fieldbackground=c["surface"], foreground=c["text"],
                        rowheight=31, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=c["surface_alt"],
                        foreground=c["muted"], padding=(9, 10),
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", c["surface_alt"])],
                  foreground=[("selected", c["text"])])
        style.configure("Vertical.TScrollbar", background=c["surface_alt"],
                        troughcolor=c["surface"], arrowcolor=c["muted"],
                        bordercolor=c["surface"])
        style.configure("Horizontal.TScrollbar", background=c["surface_alt"],
                        troughcolor=c["surface"], arrowcolor=c["muted"],
                        bordercolor=c["surface"])

    def _show_welcome(self):
        self._clear_screen()
        self.root.configure(bg=self.colors["background"])
        self.welcome_frame = tk.Frame(self.root, bg=self.colors["background"])
        self.welcome_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(self.welcome_frame, bg=self.colors["background"],
                          highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self.welcome_canvas = canvas

        def paint(event=None):
            canvas.delete("visual")
            w = max(canvas.winfo_width(), 900)
            h = max(canvas.winfo_height(), 600)
            # Decorative sound-wave rings and bars, not a static splash.
            canvas.create_oval(w*0.31, h*0.13, w*0.69, h*0.75,
                              outline="#353B42", width=2, tags="visual")
            canvas.create_oval(w*0.35, h*0.17, w*0.65, h*0.71,
                              outline="#353B42", width=1, tags="visual")
            canvas.create_oval(w*0.39, h*0.21, w*0.61, h*0.67,
                              outline="#242333", width=1, tags="visual")
            center_x, center_y = w/2, h*0.40
            bars = [18, 32, 48, 28, 64, 42, 78, 50, 30, 62, 38, 72, 45, 25, 55, 34, 20]
            gap = 10
            total = len(bars)*gap
            start = center_x-total/2
            for i, bar in enumerate(bars):
                color = self.colors["accent"] if i % 3 == 0 else self.colors["purple"]
                canvas.create_line(start+i*gap, center_y-bar/2,
                                  start+i*gap, center_y+bar/2,
                                  fill=color, width=4, capstyle="round",
                                  tags="visual")
            canvas.create_text(center_x, h*0.53, text="RESONANTIA",
                              fill=self.colors["text"], font=("Segoe UI", 36, "bold"),
                              tags="visual")
            canvas.create_text(center_x, h*0.59,
                              text="MOVEMENT  /  SOUND  /  INTERACTION",
                              fill=self.colors["muted"], font=("Segoe UI", 10, "bold"),
                              tags="visual")
            canvas.create_text(center_x, h*0.64,
                              text="El movimiento se convierte en música.",
                              fill=self.colors["muted"], font=("Segoe UI", 12),
                              tags="visual")
        canvas.bind("<Configure>", paint)
        self._welcome_paint = paint

        actions = tk.Frame(self.welcome_frame, bg=self.colors["background"])
        actions.place(relx=0.5, rely=0.79, anchor="center")
        self._make_button(actions, "Empezar", self._show_player_count,
                          primary=True, width=20).pack(pady=(0, 12))
        self._make_button(actions, "Salir", self.close, width=20).pack()
        tk.Label(self.welcome_frame, text="UNA EXPERIENCIA AUDIOVISUAL INTERACTIVA",
                 bg=self.colors["background"], fg="#756B5E",
                 font=("Segoe UI", 8, "bold")).place(relx=0.5, rely=0.96,
                                                    anchor="center")

    def _clear_screen(self):
        for child in self.root.winfo_children():
            child.destroy()

    def _make_button(self, parent, text, command, primary=False, width=None):
        bg = self.colors["accent"] if primary else "#29251F"
        fg = "#29251F" if primary else "#F4F1EA"
        button = tk.Button(
            parent, text=text, command=command, width=width,
            bg=bg, fg=fg, activebackground=self.colors["accent_hover"],
            activeforeground=fg, relief="flat", bd=0, cursor="hand2",
            font=("Segoe UI", 10, "bold"), padx=20, pady=12,
        )
        button.configure(highlightthickness=1,
                         highlightbackground=bg, highlightcolor=bg)
        return button

    def _show_player_count(self):
        """Pantalla visual para elegir el número de participantes."""
        self._clear_screen()
        frame = tk.Frame(self.root, bg=self.colors["background"])
        frame.pack(fill="both", expand=True, padx=42, pady=30)

        tk.Label(frame, text="PREPARA TU SESIÓN",
                 bg=self.colors["background"], fg=self.colors["accent"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(frame, text="¿Cuántas personas habrá en pantalla?",
                 bg=self.colors["background"], fg="#F4F1EA",
                 font=("Segoe UI", 25, "bold")).pack(anchor="w", pady=(8, 5))
        tk.Label(frame, text="Selecciona el número de participantes para esta experiencia.",
                 bg=self.colors["background"], fg="#A8ADB3",
                 font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 20))

        cards = tk.Frame(frame, bg=self.colors["background"])
        cards.pack(fill="both", expand=True)
        for column in range(4):
            cards.columnconfigure(column, weight=1, uniform="player")
        cards.rowconfigure(0, weight=1)

        descriptions = {
            1: "Experiencia individual",
            2: "Dúo musical",
            3: "Trío en movimiento",
            4: "Ensamble completo",
        }
        # Guardamos referencias a las tarjetas para actualizar su estilo sin
        # destruir y reconstruir toda la pantalla (evita el parpadeo al clicar).
        self.player_count_cards = {}

        for count in range(1, 5):
            selected = count == self.selected_player_count
            card = RoundedPanel(
                cards,
                background="#24282D" if selected else "#191C20",
                border=self.colors["accent"] if selected else "#353B42",
                radius=22
            )
            card.grid(row=0, column=count-1, sticky="nsew",
                      padx=8, pady=8)
            card.content.columnconfigure(0, weight=1)

            number = tk.Label(
                card.content, text=str(count),
                bg=card._panel_bg,
                fg=self.colors["accent"] if selected else "#F4F1EA",
                font=("Segoe UI", 38, "bold")
            )
            number.grid(row=0, column=0, pady=(22, 2))

            plural = tk.Label(
                card.content, text="JUGADOR" if count == 1 else "JUGADORES",
                bg=card._panel_bg, fg="#F4F1EA",
                font=("Segoe UI", 10, "bold")
            )
            plural.grid(row=1, column=0, pady=(0, 6))

            # Siluetas vectoriales sencillas: una cabeza y torso por participante.
            silhouette = tk.Canvas(
                card.content, width=210, height=105,
                bg=card._panel_bg, highlightthickness=0, bd=0
            )
            silhouette.grid(row=2, column=0, pady=(2, 8))
            self._draw_player_silhouettes(
                silhouette, count,
                self.colors["accent"] if selected else "#8B8798"
            )

            description = tk.Label(
                card.content, text=descriptions[count],
                bg=card._panel_bg, fg="#A8ADB3",
                font=("Segoe UI", 9), wraplength=190,
                justify="center"
            )
            description.grid(row=3, column=0, pady=(0, 22))

            # La tarjeta completa es el área de selección, no un botón pequeño.
            widgets = [card, card.canvas, card.content, number, plural,
                       silhouette, description]
            for widget in widgets:
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>",
                           lambda event, n=count: self._select_player_count(n))

            self.player_count_cards[count] = {
                "panel": card,
                "widgets": widgets,
                "number": number,
                "silhouette": silhouette,
                "description": description,
            }

        bottom = tk.Frame(frame, bg=self.colors["background"])
        bottom.pack(fill="x", pady=(18, 0))
        self._make_button(bottom, "Volver", self._show_welcome).pack(side="left")
        self.player_count_continue_button = self._make_button(
            bottom,
            f"Continuar con {self.selected_player_count} jugador(es)  →",
            self._show_instrument_setup,
            primary=True
        )
        self.player_count_continue_button.pack(side="right")

    def _draw_player_silhouettes(self, canvas, count, color):
        """Dibuja iconos de jugadores sin depender de archivos externos."""
        canvas.delete("all")
        spacing = 43
        total_width = (count - 1) * spacing
        start_x = 105 - total_width / 2
        for index in range(count):
            x = start_x + index * spacing
            # Cabeza
            canvas.create_oval(
                x-10, 13, x+10, 33, fill=color, outline=color
            )
            # Hombros y torso estilizados
            canvas.create_arc(
                x-19, 31, x+19, 75, start=0, extent=180,
                style="pieslice", fill=color, outline=color
            )
            canvas.create_rectangle(
                x-19, 52, x+19, 77, fill=color, outline=color
            )
            # Pequeña base redondeada
            canvas.create_oval(
                x-19, 68, x+19, 88, fill=color, outline=color
            )

    def _select_player_count(self, count):
        """Actualiza la selección visual; continuar lleva a asignar instrumentos."""
        self.selected_player_count = max(1, min(4, int(count)))
        previous = getattr(self, "person_instruments", {})
        self.person_instruments = {
            person: previous.get(person)
            for person in range(1, self.selected_player_count + 1)
        }

        # Actualización localizada: solo cambia el aspecto de las tarjetas.
        for card_count, data in getattr(self, "player_count_cards", {}).items():
            selected = card_count == self.selected_player_count
            panel = data["panel"]
            panel_bg = "#24282D" if selected else "#191C20"
            border = self.colors["accent"] if selected else "#353B42"
            panel._panel_bg = panel_bg
            panel._panel_border = border
            panel.configure(bg=panel_bg)
            panel.canvas.configure(bg=panel_bg)
            panel.content.configure(bg=panel_bg)
            for widget in data["widgets"]:
                if widget is panel or widget is panel.canvas or widget is panel.content:
                    continue
                try:
                    widget.configure(bg=panel_bg)
                except tk.TclError:
                    pass
            data["number"].configure(
                fg=self.colors["accent"] if selected else "#F4F1EA"
            )
            self._draw_player_silhouettes(
                data["silhouette"], card_count,
                self.colors["accent"] if selected else "#8B8798"
            )
            panel._draw_panel()

        button = getattr(self, "player_count_continue_button", None)
        if button is not None and button.winfo_exists():
            button.configure(
                text=f"Continuar con {self.selected_player_count} jugador(es)  →"
            )

    def _show_instrument_setup(self):
        """Asignación dinámica: solo muestra las personas elegidas."""
        self._clear_screen()
        count = self.selected_player_count
        frame = tk.Frame(self.root, bg=self.colors["background"])
        frame.pack(fill="both", expand=True, padx=42, pady=30)
        self.instrument_frame = frame

        tk.Label(frame, text="PERSONALIZA EL ENSAMBLE",
                 bg=self.colors["background"], fg=self.colors["accent"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(frame, text="Asigna un instrumento a cada persona",
                 bg=self.colors["background"], fg="#F4F1EA",
                 font=("Segoe UI", 24, "bold")).pack(anchor="w", pady=(7, 4))
        tk.Label(frame, text="Cada instrumento se usa una sola vez. Puedes quitarlo o cambiarlo.",
                 bg=self.colors["background"], fg="#A8ADB3",
                 font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 18))

        grid = tk.Frame(frame, bg=self.colors["background"])
        grid.pack(fill="both", expand=True)
        columns = 2 if count > 1 else 1
        rows = (count + columns - 1) // columns
        for column in range(columns):
            grid.columnconfigure(column, weight=1, uniform="person")
        for row in range(rows):
            grid.rowconfigure(row, weight=1, uniform="person")

        previous = getattr(self, "person_instruments", {})
        self.person_instruments = {
            person: previous.get(person)
            for person in range(1, count + 1)
        }
        self.person_cards = {}
        for index in range(1, count + 1):
            card = RoundedPanel(grid, background="#191C20",
                                border="#353B42", radius=20)
            card.grid(row=(index-1)//columns, column=(index-1)%columns,
                      sticky="nsew", padx=8, pady=8)
            card.content.columnconfigure(0, weight=1)
            tk.Label(card.content, text=f"PERSONA {index:02d}",
                     bg="#191C20", fg=self.colors["purple"],
                     font=("Segoe UI", 9, "bold")).grid(
                         row=0, column=0, sticky="w", padx=20, pady=(15, 4))
            selection = self.person_instruments.get(index)
            name = tk.Label(
                card.content,
                text=selection[0] if selection else "Sin instrumento",
                bg="#191C20", fg="#F4F1EA",
                font=("Segoe UI", 16, "bold"), wraplength=460
            )
            name.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 12))
            choose = self._make_button(
                card.content,
                "↻  Cambiar instrumento" if selection else "＋  Elegir instrumento",
                lambda person=index: self._open_instrument_picker(person),
                primary=False
            )
            choose.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 15))
            self.person_cards[index] = {"card": card, "name": name,
                                        "button": choose}

        bottom = tk.Frame(frame, bg=self.colors["background"])
        bottom.pack(fill="x", pady=(16, 0))
        assigned = sum(value is not None for value in self.person_instruments.values())
        self.assignment_status = tk.Label(
            bottom, text=f"{assigned} de {count} instrumentos asignados",
            bg=self.colors["background"], fg="#A8ADB3",
            font=("Segoe UI", 9))
        self.assignment_status.pack(side="left")
        self.continue_button = self._make_button(
            bottom, "Continuar a la consola  →", self._apply_assignments,
            primary=True
        )
        self.continue_button.pack(side="right")
        self.continue_button.configure(
            state="normal" if assigned == count else "disabled"
        )
        # Un único botón de navegación: vuelve a la pantalla anterior
        # (selección de cantidad de jugadores).
        self._make_button(
            bottom, "←  Volver", self._show_player_count
        ).pack(side="right", padx=(0, 10))

    def _open_instrument_picker(self, person):
        used = {value[1] for key, value in self.person_instruments.items()
                if key != person and value}
        available = [(label, role) for label, role in self.instrument_choices
                     if role not in used]
        popup = tk.Toplevel(self.root)
        popup.title(f"Instrumento · Persona {person}")
        popup.configure(bg=self.colors["background"])
        popup.geometry("520x470")
        popup.transient(self.root)
        popup.grab_set()

        tk.Label(popup, text=f"ELIGE EL SONIDO · PERSONA {person}",
                 bg=self.colors["background"], fg=self.colors["accent"],
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=22,
                                                     pady=(22, 5))
        tk.Label(popup, text="Los instrumentos asignados a otras personas están bloqueados.",
                 bg=self.colors["background"], fg="#A8ADB3",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=22, pady=(0, 14))
        option_area = tk.Frame(popup, bg=self.colors["background"])
        option_area.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        option_canvas = tk.Canvas(option_area, bg=self.colors["background"],
                                 highlightthickness=0, bd=0)
        option_scroll = ttk.Scrollbar(option_area, orient="vertical",
                                      command=option_canvas.yview)
        option_canvas.configure(yscrollcommand=option_scroll.set)
        option_scroll.pack(side="right", fill="y")
        option_canvas.pack(side="left", fill="both", expand=True)
        list_frame = tk.Frame(option_canvas, bg=self.colors["background"])
        option_window = option_canvas.create_window(
            (0, 0), window=list_frame, anchor="nw"
        )
        list_frame.bind("<Configure>", lambda _event:
                        option_canvas.configure(scrollregion=option_canvas.bbox("all")))
        option_canvas.bind("<Configure>", lambda event:
                           option_canvas.itemconfigure(option_window, width=event.width))

        # Permite liberar la selección de esta persona sin afectar a las demás.
        self._make_button(
            list_frame, "⊖  Quitar instrumento",
            lambda: self._remove_person_instrument(person, popup),
            primary=False
        ).pack(fill="x", pady=(0, 8))
        for label, role in available:
            self._make_button(
                list_frame, f"♪   {label}",
                lambda l=label, r=role: self._set_person_instrument(
                    person, l, r, popup
                ), primary=False
            ).pack(fill="x", pady=4)

    def _remove_person_instrument(self, person, popup):
        self.person_instruments[person] = None
        self.person_cards[person]["name"].configure(text="Sin instrumento")
        self.person_cards[person]["button"].configure(text="＋  Elegir instrumento")
        popup.destroy()
        self._refresh_assignment_progress()

    def _set_person_instrument(self, person, label, role, popup):
        self.person_instruments[person] = (label, role)
        self.person_cards[person]["name"].configure(text=label)
        self.person_cards[person]["button"].configure(text="↻  Cambiar instrumento")
        popup.destroy()
        self._refresh_assignment_progress()

    def _refresh_assignment_progress(self):
        count = self.selected_player_count
        assigned = sum(self.person_instruments.get(person) is not None
                       for person in range(1, count + 1))
        self.assignment_status.configure(
            text=f"{assigned} de {count} instrumentos asignados"
        )
        self.continue_button.configure(
            state="normal" if assigned == count else "disabled"
        )

    def _apply_assignments(self):
        # Guardar la elección de rol de cada tarjeta. Los presets y canales
        # originales del motor se mantienen intactos.
        self.person_role_assignments = {
            person: selection[1]
            for person, selection in self.person_instruments.items()
            if selection is not None and person <= self.selected_player_count
        }
        # Replace the assignment screen completely; do not stack the console
        # beneath it in the same root window.
        self._clear_screen()
        self._build_dashboard()
        # _build_dashboard ya coloca dashboard_frame con grid dentro de app_shell.
        # No volver a gestionarlo con pack: mezclar pack/grid en el mismo
        # contenedor provocaba TclError y podía dejar la pantalla incompleta.
        self.root.configure(bg=self.colors["background"])

    def _return_to_setup(self):
        """Regresa a la asignación; detiene cámara/audio antes de cambiar pantalla."""
        if self.is_running:
            self.pending_setup_return = True
            self.stop()
            self.status_var.set("Cerrando la sesión para cambiar instrumentos...")
            return
        self._show_instrument_setup()

    def _show_dashboard(self):
        if hasattr(self, "dashboard_frame"):
            self.dashboard_frame.pack(fill="both", expand=True)

    def _build_dashboard(self):
        # Shell de aplicación: navegación lateral discreta + consola principal.
        self.app_shell = tk.Frame(self.root, bg=self.colors["background"])
        self.app_shell.pack(fill="both", expand=True)
        self.app_shell.columnconfigure(1, weight=1)
        self.app_shell.rowconfigure(0, weight=1)

        self.sidebar = tk.Frame(
            self.app_shell, bg=self.colors["surface"], width=190
        )
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        tk.Label(
            self.sidebar, text="♫  RESONANTIA", bg=self.colors["surface"],
            fg=self.colors["accent"], font=("Segoe UI", 15, "bold"),
            anchor="w"
        ).pack(fill="x", padx=18, pady=(24, 30))
        self._sidebar_item(self.sidebar, "⌂", "Experiencia", self._show_dashboard_view, active=True)
        self._sidebar_item(self.sidebar, "⚙", "Configuración", self._open_settings)
        tk.Frame(self.sidebar, bg=self.colors["border"], height=1).pack(
            fill="x", padx=16, pady=20
        )
        tk.Label(
            self.sidebar, text="MOVEMENT\nSOUND\nINTERACTION",
            bg=self.colors["surface"], fg=self.colors["muted"],
            font=("Segoe UI", 8, "bold"), justify="left"
        ).pack(side="bottom", anchor="w", padx=18, pady=22)

        self.dashboard_frame = tk.Frame(self.app_shell, bg=self.colors["background"])
        self.dashboard_frame.grid(row=0, column=1, sticky="nsew")
        self.dashboard_frame.columnconfigure(0, weight=1)
        self.dashboard_frame.rowconfigure(2, weight=1)

        # Cabecera de marca: personalidad visual sin alterar el flujo de la app.
        header = ttk.Frame(self.dashboard_frame, padding=(18, 8, 18, 7))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header, text="RESONANTIA", style="Brand.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header, text="MOVEMENT  /  SOUND  /  INTERACTION",
            style="Eyebrow.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(1, 3))
        ttk.Label(
            header, text="El movimiento se convierte en una experiencia musical.",
            style="Subtitle.TLabel",
        ).grid(row=2, column=0, sticky="w")
        lineup = "  ·  ".join(f"P{i}: {self.person_instruments[i][0]}" for i in range(1, self.selected_player_count + 1))
        ttk.Label(header, text=f"INSTRUMENTOS  ·  {lineup}",
                  style="Hint.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.header_state = ttk.Label(
            header, text="●  EN ESPERA", style="Status.TLabel"
        )
        self.header_state.grid(row=0, column=1, rowspan=3, sticky="e",
                              padx=(18, 0))
        self._make_button(
            header, "←  Cambiar instrumentos", self._return_to_setup,
            primary=False
        ).grid(row=3, column=1, sticky="e", pady=(8, 0), padx=(12, 0))

        # Barra de sesión: controles originales, con jerarquía y aire.
        controls = RoundedPanel(self.dashboard_frame, background=self.colors["surface"],
                                border=self.colors["border"], radius=18)
        controls.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))
        session = controls.content
        session.columnconfigure(5, weight=1)
        ttk.Label(session, text="SESIÓN", style="Eyebrow.TLabel").grid(
            row=0, column=0, sticky="w", padx=(4, 14), pady=(2, 8)
        )
        self.start_button = ttk.Button(
            session, text="▶  Iniciar experiencia", command=self.start,
            style="Accent.TButton"
        )
        self.start_button.grid(row=1, column=0, padx=(4, 4))
        self.stop_button = ttk.Button(
            session, text="■  Detener", command=self.stop, state="disabled",
            style="Stop.TButton"
        )
        self.stop_button.grid(row=1, column=1, padx=4)
        ttk.Button(session, text="Salir  ↗", command=self.close).grid(
            row=1, column=2, padx=(4, 0)
        )

        # Área principal: cámara protagonista y consola de datos.
        content = ttk.Panedwindow(self.dashboard_frame, orient=tk.HORIZONTAL)
        content.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 8))
        video_panel = RoundedPanel(content, background=self.colors["surface"],
                                   border=self.colors["border"], radius=22)
        data_panel = ttk.Frame(content, padding=(6, 4, 4, 4))
        content.add(video_panel, weight=3)
        content.add(data_panel, weight=2)
        video_panel.content.columnconfigure(0, weight=1)
        video_panel.content.rowconfigure(0, weight=1)
        video_panel.content.rowconfigure(1, weight=0)

        self.video_label = ttk.Label(
            video_panel.content,
            text="LISTO PARA CREAR SONIDO\n\n"
                 "Inicia la experiencia para activar la cámara.\n"
                 "Ubícate en un espacio iluminado y de cuerpo visible.",
            anchor="center", justify="center",
            background=self.colors["background"], foreground=self.colors["text"],
            font=("Segoe UI", 13), style="Video.TLabel",
        )
        self.video_label.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            video_panel.content,
            text="TIP  ·  Deja espacio entre participantes y evita cubrir las manos.",
            style="Hint.TLabel", wraplength=760,
        ).grid(row=1, column=0, sticky="ew", pady=(8, 2))

        data_panel.columnconfigure(0, weight=1)
        data_panel.rowconfigure(1, weight=1)
        summary = RoundedPanel(data_panel, background=self.colors["surface"],
                              border=self.colors["border"], radius=20)
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        metrics = summary.content
        for column in range(3):
            metrics.columnconfigure(column, weight=1)
        ttk.Label(metrics, text="MÉTRICAS EN VIVO",
                  style="Eyebrow.TLabel").grid(
                      row=0, column=0, columnspan=3, sticky="w",
                      padx=5, pady=(2, 5)
                  )
        self._summary_item(metrics, "Personas", self.count_var, 1, 0)
        self._summary_item(metrics, "Posibles contactos", self.contacts_var, 1, 1)
        self._summary_item(metrics, "Sincronía grupal", self.sync_var, 1, 2)
        self._summary_item(metrics, "Movimiento · 0–1", self.movement_var, 2, 0)
        self._summary_item(metrics, "Apertura de brazos", self.opening_var, 2, 1)
        self._summary_item(metrics, "Velocidad de video", self.fps_var, 2, 2)
        self._summary_item(metrics, "Modo musical", self.mode_var, 3, 0)
        self._summary_item(metrics, "Acorde actual", self.chord_var, 3, 1)

        # Un único visor con pestañas: gráficas y tablas ocupan el mismo
        # espacio, evitando paneles técnicos separados y barras redundantes.
        data_panel.rowconfigure(1, weight=1)
        self.notebook = ttk.Notebook(data_panel)
        self.notebook.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        trends_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(trends_tab, text="Tendencias")
        ttk.Label(
            trends_tab, text="Actividad de la sesión",
            style="Section.TLabel"
        ).pack(anchor="w", pady=(0, 6))
        self.metric_history = getattr(self, "metric_history", [])
        self.metric_chart = tk.Canvas(
            trends_tab, height=150, bg=self.colors["surface"],
            highlightthickness=1, highlightbackground=self.colors["border"], bd=0
        )
        self.metric_chart.pack(fill="both", expand=True)
        self.metric_chart.bind(
            "<Configure>", lambda _event: self._draw_metric_charts()
        )
        self.notebook.bind(
            "<<NotebookTabChanged>>",
            lambda _event: self._draw_metric_charts()
        )

        self.people_tree = self._add_table_tab(
            "Personas",
            (
                ("id", "ID", 48),
                ("center", "Centro (x, y)", 105),
                ("movement", "Desplazamiento", 100),
                ("vx", "Velocidad X", 85),
                ("vy", "Velocidad Y", 85),
                ("speed", "Rapidez", 75),
                ("direction", "Dirección", 80),
            ),
        )
        self.people_tree.bind("<<TreeviewSelect>>", self._show_selected_landmarks)
        self.distance_tree = self._add_table_tab(
            "Distancias",
            (
                ("first", "Persona A", 85),
                ("second", "Persona B", 85),
                ("distance", "Distancia normalizada", 145),
                ("synchrony", "Sincronía (0–1)", 120),
            ),
        )
        self.contact_tree = self._add_table_tab(
            "Contactos",
            (
                ("kind", "Tipo estimado", 175),
                ("first", "Persona A", 85),
                ("second", "Persona B", 85),
                ("point1", "Punto A (x, y)", 120),
                ("point2", "Punto B (x, y)", 120),
            ),
        )

        landmark_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(landmark_tab, text="Puntos corporales")
        ttk.Label(
            landmark_tab,
            text="Selecciona una persona para consultar sus 33 landmarks.",
            style="Hint.TLabel", wraplength=440,
        ).pack(anchor="w", pady=(0, 8))
        self.landmark_tree = self._create_tree(
            landmark_tab,
            (
                ("index", "Punto", 150),
                ("x", "X", 70),
                ("y", "Y", 70),
                ("z", "Z", 70),
                ("visibility", "Visibilidad", 95),
                ("presence", "Presencia", 95),
            ),
        )

        music_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(music_tab, text="Música")
        ttk.Label(
            music_tab, text=f"♪  {BPM} BPM     ·     La menor     ·     4/4",
            style="Section.TLabel",
        ).pack(anchor="w", pady=(0, 10))
        music_summary = ttk.Frame(music_tab, style="Card.TFrame", padding=10)
        music_summary.pack(fill="x", pady=(0, 10))
        ttk.Label(music_summary, text="Capas activas:", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Label(
            music_summary, textvariable=self.layers_var, wraplength=330,
            style="Section.TLabel",
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(music_summary, text="Densidad melódica:", style="Hint.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Label(music_summary, textvariable=self.density_var,
                  style="Section.TLabel").grid(row=1, column=1, sticky="w")
        ttk.Label(music_summary, text="Intensidad:", style="Hint.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Label(music_summary, textvariable=self.intensity_var,
                  style="Section.TLabel").grid(row=2, column=1, sticky="w")
        self.events_tree = self._create_tree(
            music_tab,
            (
                ("beat", "Tiempo (pulso)", 105),
                ("instrument", "Instrumento", 105),
                ("note", "Nota MIDI", 85),
                ("duration", "Duración", 85),
                ("velocity", "Velocidad", 85),
            ),
        )

        footer = ttk.Frame(self.dashboard_frame, padding=(18, 4, 18, 7))
        footer.grid(row=3, column=0, sticky="ew")
        ttk.Label(footer, textvariable=self.status_var,
                  style="Hint.TLabel").pack(side="left")
        ttk.Label(
            footer,
            text="Datos relativos a la imagen · Contacto estimado, no físico.",
            style="Hint.TLabel", wraplength=850,
        ).pack(side="right")

    def _draw_metric_charts(self):
        """Dibuja tres sparklines ligeras con datos reales de la sesión."""
        canvas = getattr(self, "metric_chart", None)
        if canvas is None or not canvas.winfo_exists():
            return
        width = max(300, canvas.winfo_width())
        height = max(90, canvas.winfo_height())
        canvas.delete("chart")
        palette = self.colors
        series = [
            ("Movimiento", 0, palette["accent"]),
            ("Apertura", 1, palette["purple"]),
            ("Sincronía", 2, palette["mint"]),
        ]
        history = getattr(self, "metric_history", [])
        section = width / 3
        for index, (title, key, color) in enumerate(series):
            left = index * section + 12
            right = (index + 1) * section - 12
            top, bottom = 30, height - 15
            canvas.create_text(left, 12, text=title, anchor="w",
                              fill=palette["muted"], font=("Segoe UI", 8, "bold"),
                              tags="chart")
            canvas.create_line(left, bottom, right, bottom,
                              fill=palette["border"], width=1, tags="chart")
            values = [point[key] for point in history]
            if len(values) < 2:
                values = [0.0, 0.0]
            points = []
            for i, value in enumerate(values[-45:]):
                x = left + (right-left) * i / max(1, len(values[-45:])-1)
                y = bottom - max(0.0, min(1.0, value)) * (bottom-top)
                points.extend((x, y))
            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=2,
                                  smooth=True, splinesteps=12, tags="chart")
            current = values[-1] if values else 0
            canvas.create_text(right, 12, text=f"{current:.2f}", anchor="e",
                              fill=color, font=("Segoe UI", 8, "bold"), tags="chart")

    def _sidebar_item(self, parent, icon, label, command, active=False):
        bg = self.colors["surface_alt"] if active else self.colors["surface"]
        fg = self.colors["accent"] if active else self.colors["muted"]
        item = tk.Frame(parent, bg=bg, cursor="hand2")
        item.pack(fill="x", padx=10, pady=4)
        tk.Label(item, text=icon, bg=bg, fg=fg,
                 font=("Segoe UI Symbol", 13), width=2).pack(side="left", padx=(8, 2), pady=10)
        tk.Label(item, text=label, bg=bg, fg=self.colors["text"],
                 font=("Segoe UI", 10), anchor="w").pack(side="left", padx=5)
        for widget in (item, *item.winfo_children()):
            widget.bind("<Button-1>", lambda _event: command())
        return item

    def _show_dashboard_view(self):
        # La navegación de regreso no reinicia cámara ni motor.
        if hasattr(self, "dashboard_frame") and self.dashboard_frame.winfo_exists():
            self.dashboard_frame.tkraise()

    def _open_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        win = tk.Toplevel(self.root)
        self.settings_window = win
        win.title("Resonantia · Configuración")
        win.geometry("520x510")
        win.resizable(False, False)
        win.configure(bg=self.colors["background"])
        win.transient(self.root)
        win.grab_set()

        outer = tk.Frame(win, bg=self.colors["background"])
        outer.pack(fill="both", expand=True, padx=26, pady=24)
        tk.Label(outer, text="PREFERENCIAS", bg=self.colors["background"],
                 fg=self.colors["accent"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(outer, text="Configura tu espacio",
                 bg=self.colors["background"], fg=self.colors["text"],
                 font=("Segoe UI", 22, "bold")).pack(anchor="w", pady=(5, 18))

        camera_card = RoundedPanel(outer, background=self.colors["surface"],
                                   border=self.colors["border"], radius=18)
        camera_card.pack(fill="x", pady=(0, 12))
        c = camera_card.content
        tk.Label(c, text="Cámara", bg=self.colors["surface"],
                 fg=self.colors["text"], font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=(13, 3))
        tk.Label(c, text="Elige el dispositivo que usará la experiencia.",
                 bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(0, 10))
        camera_row = tk.Frame(c, bg=self.colors["surface"])
        camera_row.pack(fill="x", padx=14, pady=(0, 14))
        camera_values = self._available_cameras()
        camera_pick = ttk.Combobox(
            camera_row, values=camera_values, state="readonly", width=12
        )
        camera_pick.set(self.camera_var.get() if self.camera_var.get() in camera_values else camera_values[0])
        camera_pick.pack(side="left")
        tk.Label(camera_row, text="Se aplicará al iniciar la próxima sesión.",
                 bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 8)).pack(side="left", padx=10)

        theme_card = RoundedPanel(outer, background=self.colors["surface"],
                                  border=self.colors["border"], radius=18)
        theme_card.pack(fill="x", pady=(0, 12))
        theme_card.configure(height=145)
        theme_card.pack_propagate(False)
        t = theme_card.content
        tk.Label(t, text="Apariencia", bg=self.colors["surface"],
                 fg=self.colors["text"], font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=(13, 3))
        tk.Label(t, text="Elige el ambiente visual de Resonantia.",
                 bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(0, 10))
        theme_row = tk.Frame(t, bg=self.colors["surface"])
        theme_row.pack(fill="x", padx=14, pady=(0, 14))
        self.theme_choice = tk.StringVar(value=self.theme_mode)
        ttk.Button(
            theme_row, text="☾  Oscuro",
            command=lambda: self._preview_theme("dark"),
        ).pack(side="left", padx=(0, 10))
        ttk.Button(
            theme_row, text="☀  Claro",
            command=lambda: self._preview_theme("light"),
        ).pack(side="left")

        actions = tk.Frame(outer, bg=self.colors["background"])
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Cerrar", command=win.destroy).pack(side="right")
        ttk.Button(
            actions, text="Guardar preferencias", style="Accent.TButton",
            command=lambda: self._save_settings(camera_pick.get(), self.theme_choice.get(), win)
        ).pack(side="right", padx=8)

    def _available_cameras(self):
        # Índices comunes. Evitamos abrir/probar cámaras desde la ventana de
        # preferencias: hacerlo puede congelar la UI o bloquear la cámara activa.
        current = str(self.camera_var.get())
        values = [str(index) for index in range(6)]
        if current not in values:
            values.insert(0, current)
        return tuple(values)


    def _preview_theme(self, mode):
        """Aplica el tema al pulsar el selector, sin exigir otro clic."""
        if hasattr(self, "theme_choice"):
            self.theme_choice.set(mode)
        self._apply_theme(mode)

    def _save_settings(self, camera, theme, window):
        if camera:
            self.camera_var.set(str(camera))
        if theme != self.theme_mode:
            self._apply_theme(theme)
        window.destroy()
        self.settings_window = None
        self.status_var.set("Preferencias guardadas. La cámara seleccionada se usará al iniciar.")

    def _apply_theme(self, mode):
        """Cambia toda la paleta de forma reversible, incluidos los paneles Tk."""
        if mode not in ("dark", "light") or mode == self.theme_mode:
            return

        old = dict(self.colors)
        self.theme_mode = mode
        self._configure_styles()
        new = self.colors

        # Tokens semánticos: cada color de la paleta anterior pasa a su
        # equivalente nuevo. Así no se confunden fondos con colores de texto.
        backgrounds = {
            old["background"]: new["background"],
            old["surface"]: new["surface"],
            old["surface_alt"]: new["surface_alt"],
            old["border"]: new["border"],
        }
        foregrounds = {
            old["text"]: new["text"], old["muted"]: new["muted"],
            old["accent"]: new["accent"],
            old["accent_hover"]: new["accent_hover"],
            old["purple"]: new["purple"], old["mint"]: new["mint"],
            old["danger"]: new["danger"],
        }
        # Colores literales de versiones previas de la interfaz.
        legacy_backgrounds = {
            "#101214": new["background"], "#191C20": new["surface"],
            "#24282D": new["surface_alt"], "#353B42": new["border"],
            "#1C1C24": new["surface"], "#1C1C22": new["surface"],
            "#242333": new["surface_alt"], "#383844": new["surface_alt"],
            "#29251F": new["surface"], "#2A2520": new["surface_alt"],
            "#45352A": new["border"], "#F5F1E8": new["background"],
            "#FFFCF6": new["surface"], "#EAE3D6": new["surface_alt"],
            "#D5C9B7": new["border"], "#FAFAFC": new["background"],
            "#FFFFFF": new["surface"], "#F1F3F6": new["surface_alt"],
            "#DCE1E7": new["border"], "#F0F1F6": new["surface_alt"],
            "#E9EAF0": new["surface_alt"], "#F8E8EE": new["surface_alt"],
            "#F5DCE7": new["surface_alt"],
        }
        legacy_foregrounds = {
            "#F4F1EA": new["text"], "#F7F3FA": new["text"],
            "#F6F2FA": new["text"], "#A8ADB3": new["muted"],
            "#A6A3B2": new["muted"], "#756B5E": new["muted"],
            "#8B8798": new["muted"], "#777582": new["muted"],
            "#555968": new["muted"], "#687080": new["muted"],
            "#454858": new["text"], "#1A1016": new["text"],
            "#D97724": new["accent"], "#F59E0B": new["accent_hover"],
            "#C96F1D": new["accent"], "#A95612": new["accent_hover"],
            "#E5A84B": new["purple"], "#9C6A2D": new["purple"],
            "#A78BFA": new["purple"], "#7655C8": new["purple"],
            "#A8BFA5": new["mint"], "#617D62": new["mint"],
            "#B85C2A": new["danger"], "#A94E25": new["danger"],
        }
        backgrounds.update(legacy_backgrounds)
        foregrounds.update(legacy_foregrounds)
        borders = dict(backgrounds)
        borders.update({old["border"]: new["border"]})

        def recolor(widget):
            if isinstance(widget, RoundedPanel):
                widget._panel_bg = backgrounds.get(widget._panel_bg, new["surface"])
                widget._panel_border = new["border"]
                widget.configure(bg=widget._panel_bg)
                widget.canvas.configure(bg=widget._panel_bg)
                widget.content.configure(bg=widget._panel_bg)
                widget._draw_panel()

            try:
                options = widget.configure()
                for option in ("background", "bg"):
                    if option in options:
                        value = widget.cget(option)
                        if isinstance(value, str) and value in backgrounds:
                            widget.configure(**{option: backgrounds[value]})
                for option in ("foreground", "fg"):
                    if option in options:
                        value = widget.cget(option)
                        if isinstance(value, str) and value in foregrounds:
                            widget.configure(**{option: foregrounds[value]})
                for option in ("highlightbackground", "highlightcolor"):
                    if option in options:
                        value = widget.cget(option)
                        if isinstance(value, str) and value in borders:
                            widget.configure(**{option: borders[value]})
            except (tk.TclError, TypeError):
                pass

            for child in widget.winfo_children():
                recolor(child)

        recolor(self.root)
        self.root.configure(bg=new["background"])
        if hasattr(self, "metric_chart"):
            self.metric_chart.configure(bg=new["surface"],
                                       highlightbackground=new["border"])
            self._draw_metric_charts()
        if hasattr(self, "player_count_cards"):
            self._select_player_count(self.selected_player_count)
        if hasattr(self, "_welcome_paint"):
            try:
                self._welcome_paint()
            except tk.TclError:
                pass
        self.root.update_idletasks()

    def _summary_item(self, parent, title, variable, row, column):
        item = RoundedPanel(parent, background=self.colors["surface"],
                            border=self.colors["border"], radius=14)
        item.grid(row=row, column=column, sticky="ew", padx=3, pady=3)
        ttk.Label(item.content, text=title, style="MetricTitle.TLabel").pack(anchor="w")
        ttk.Label(item.content, textvariable=variable, style="MetricValue.TLabel").pack(
            anchor="w", pady=(4, 0)
        )

    def _add_table_tab(self, title, columns):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text=title)
        return self._create_tree(tab, columns)

    @staticmethod
    def _create_tree(parent, columns):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)
        names = tuple(column[0] for column in columns)
        tree = ttk.Treeview(
            container, columns=names, show="headings", selectmode="browse"
        )
        scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=tree.yview
        )
        tree.configure(yscrollcommand=scrollbar.set)
        for name, heading, width in columns:
            tree.heading(name, text=heading)
            tree.column(name, width=width, minwidth=55, stretch=True)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        return tree

    def start(self):
        if self.is_running:
            return
        try:
            camera_index = int(self.camera_var.get())
        except ValueError:
            messagebox.showerror("Camara no valida", "Selecciona una camara.")
            return

        self.stop_event = threading.Event()
        self.is_running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("Iniciando camara y modelo de pose...")
        if hasattr(self, "header_state"):
            self.header_state.configure(text="●  INICIANDO",
                                       foreground=self.colors["purple"])
        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(camera_index, True, self.stop_event),
            daemon=True,
        )
        self.capture_thread.start()

    def stop(self):
        if self.stop_event is not None and self.is_running:
            self.stop_event.set()
            if hasattr(self, "stop_button") and self.stop_button.winfo_exists():
                self.stop_button.configure(state="disabled")
            self.status_var.set("Deteniendo y liberando recursos...")

    def close(self):
        if self.is_running:
            self.is_closing = True
            self.stop()
            self.status_var.set("Cerrando... espera a que se liberen los recursos.")
            return
        self.root.destroy()

    def _capture_loop(self, camera_index, audio_enabled, stop_event):
        camera = None
        audio = None
        worker = None
        try:
            if not vision.MODEL_PATH.is_file():
                raise FileNotFoundError(
                    "No se encontro el modelo de pose.\n"
                    f"Ruta esperada: {vision.MODEL_PATH}\n"
                    f"Descarga: {vision.MODEL_URL}"
                )

            camera = cv2.VideoCapture(camera_index)
            if not camera.isOpened():
                raise RuntimeError(
                    f"No se pudo abrir la camara {camera_index}. "
                    "Cierra otras aplicaciones que puedan estar usandola "
                    "o prueba otro indice."
                )

            options = mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(vision.MODEL_PATH)
                ),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_poses=vision.MAX_PEOPLE,
                min_pose_detection_confidence=0.5,
                min_pose_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            if audio_enabled:
                audio = ResonantiaAudio()
            worker = MusicWorker(audio)
            worker.set_person_role_assignments(
                getattr(self, "person_role_assignments", {})
            )
            tracker = vision.PoseTracker()
            previous_frame_time = time.monotonic()
            with mp.tasks.vision.PoseLandmarker.create_from_options(
                options
            ) as landmarker:
                self.message_queue.put(
                    ("ready", f"Camara {camera_index} activa.")
                )
                while not stop_event.is_set():
                    success, frame = camera.read()
                    if not success:
                        if not stop_event.is_set():
                            raise RuntimeError(
                                "No se pudo leer un fotograma de la camara."
                            )
                        break

                    timestamp_ns = time.monotonic_ns()
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = mp.Image(
                        image_format=mp.ImageFormat.SRGB, data=rgb
                    )
                    result = landmarker.detect_for_video(
                        image, timestamp_ns // 1_000_000
                    )

                    valid_poses = []
                    for landmarks in result.pose_landmarks:
                        detection = vision._make_detection(landmarks)
                        if detection is not None:
                            valid_poses.append((landmarks, detection))

                    tracked = tracker.update(
                        [detection for _, detection in valid_poses],
                        timestamp_ns / 1_000_000_000,
                    )
                    interactions = vision._detect_interactions(tracked)
                    synchrony = logic.calculate_group_synchrony(
                        [person.velocity for person in tracked]
                    )
                    state = MusicState(
                        people_count=len(tracked),
                        contact_detected=bool(interactions),
                        synchrony=synchrony if synchrony is not None else 0.0,
                    )

                    current_frame_time = time.monotonic()
                    delta_time = max(
                        0.001, current_frame_time - previous_frame_time
                    )
                    previous_frame_time = current_frame_time
                    movement, arm_opening = analyze_movement(
                        valid_poses, tracked, delta_time
                    )
                    worker.update_state(
                        state, movement=movement, arm_opening=arm_opening,
                        delta_time=delta_time,
                        person_ids=[person.track_id for person in tracked]
                    )

                    person_rows = []
                    landmarks_by_id = {}
                    for (pose_landmarks, _), person in zip(
                        valid_poses, tracked
                    ):
                        speed = logic.calculate_speed(person.velocity)
                        direction = logic.calculate_direction(person.velocity)
                        person_rows.append(
                            {
                                "id": person.track_id,
                                "center": person.detection.center,
                                "movement": person.movement,
                                "velocity": person.velocity,
                                "speed": speed,
                                "direction": direction,
                            }
                        )
                        landmarks_by_id[person.track_id] = [
                            {
                                "x": point.x,
                                "y": point.y,
                                "z": point.z,
                                "visibility": point.visibility,
                                "presence": point.presence,
                            }
                            for point in pose_landmarks
                        ]
                        vision._draw_pose(frame, pose_landmarks)
                        center_x = int(person.detection.center[0] * frame.shape[1])
                        center_y = int(person.detection.center[1] * frame.shape[0])
                        cv2.putText(
                            frame,
                            f"ID {person.track_id}",
                            (center_x + 8, center_y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            (0, 255, 255),
                            2,
                        )

                    pair_rows = []
                    positions = {
                        person.track_id: person.detection.center
                        for person in tracked
                    }
                    for first_id, second_id, distance in (
                        logic.calculate_pair_distances(positions)
                    ):
                        first = next(
                            person for person in tracked
                            if person.track_id == first_id
                        )
                        second = next(
                            person for person in tracked
                            if person.track_id == second_id
                        )
                        pair_rows.append(
                            {
                                "first": first_id,
                                "second": second_id,
                                "distance": distance,
                                "synchrony": logic.calculate_synchrony(
                                    first.velocity, second.velocity
                                ),
                            }
                        )

                    contact_rows = [
                        {
                            "kind": interaction.kind,
                            "first": interaction.first_id,
                            "second": interaction.second_id,
                            "point1": interaction.first_point,
                            "point2": interaction.second_point,
                        }
                        for interaction in interactions
                    ]
                    with worker.lock:
                        decision = worker.latest_decision
                        musical_events = worker.latest_events

                    mode = (
                        decision.mode
                        if decision is not None
                        else "Calculando..."
                    )
                    chord = decision.chord if decision is not None else "—"
                    layers = []
                    if decision is not None:
                        if decision.bass_enabled:
                            layers.append("bajo")
                        if decision.drums_enabled:
                            layers.append("bateria sintetizada")
                        if decision.harmony_enabled:
                            layers.append("armonía")
                        if decision.arpeggio_enabled:
                            layers.append("arpegiador (sinte)")
                        if decision.melody_density > 0:
                            layers.append("melodia")

                    self._publish_frame(
                        {
                            "frame": frame,
                            "people": person_rows,
                            "pairs": pair_rows,
                            "contacts": contact_rows,
                            "landmarks": landmarks_by_id,
                            "synchrony": synchrony,
                            "movement": movement,
                            "arm_opening": arm_opening,
                            "fps": 1.0 / delta_time,
                            "mode": mode,
                            "chord": chord,
                            "layers": layers,
                            "density": (
                                decision.melody_density
                                if decision is not None else None
                            ),
                            "intensity": (
                                decision.intensity
                                if decision is not None else None
                            ),
                            "events": [
                                {
                                    "beat": event.beat,
                                    "instrument": event.instrument,
                                    "note": event.midi_note,
                                    "duration": event.duration_beats,
                                    "velocity": event.velocity,
                                }
                                for event in musical_events
                            ],
                        }
                    )
        except Exception as error:
            self.message_queue.put(("error", str(error)))
        finally:
            cleanup = (
                (worker.close if worker is not None else None),
                (audio.close if audio is not None else None),
                (camera.release if camera is not None else None),
            )
            for cleanup_action in cleanup:
                if cleanup_action is not None:
                    try:
                        cleanup_action()
                    except Exception as error:
                        self.message_queue.put(
                            ("error", f"Error al liberar recursos: {error}")
                        )
            self.message_queue.put(("stopped", None))

    def _publish_frame(self, snapshot):
        try:
            self.frame_queue.put_nowait(snapshot)
        except queue.Full:
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
            self.frame_queue.put_nowait(snapshot)

    def _poll_updates(self):
        if not self.root.winfo_exists():
            return
        try:
            while True:
                self.latest_snapshot = self.frame_queue.get_nowait()
                self._render_snapshot(self.latest_snapshot)
        except queue.Empty:
            pass

        try:
            while True:
                message, detail = self.message_queue.get_nowait()
                if message == "ready":
                    self.status_var.set(
                        detail
                        + (
                            " Audio habilitado."
                            if self.audio_var.get()
                            else " Modo de visualizacion (sin audio)."
                        )
                    )
                elif message == "error":
                    self.status_var.set("No se pudo iniciar o continuar.")
                    messagebox.showerror("Error de Resonantia", detail)
                elif message == "stopped":
                    self.is_running = False
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    if self.is_closing:
                        self.root.destroy()
                        return
                    if self.pending_setup_return:
                        self.pending_setup_return = False
                        self._show_instrument_setup()
                        return
                    self.status_var.set("Detenido. Pulsa Iniciar para comenzar.")
        except queue.Empty:
            pass
        self.root.after(40, self._poll_updates)

    def _render_snapshot(self, snapshot):
        self.latest_snapshot = snapshot
        frame = snapshot["frame"]
        height, width = frame.shape[:2]
        available_width = self.video_label.winfo_width()
        available_height = self.video_label.winfo_height()
        display_width = max(320, min(760, available_width - 8))
        display_height = round(height * display_width / width)
        if available_height > 1 and display_height > available_height - 8:
            display_height = available_height - 8
            display_width = max(320, round(width * display_height / height))
        resized = cv2.resize(frame, (display_width, display_height))
        encoded, image_data = cv2.imencode(".png", resized)
        if not encoded:
            raise RuntimeError("No se pudo preparar el fotograma para la interfaz.")
        self.video_photo = tk.PhotoImage(
            data=base64.b64encode(image_data).decode("ascii"),
            format="png",
        )
        self.video_label.configure(image=self.video_photo, text="")

        self.count_var.set(str(len(snapshot["people"])))
        self.contacts_var.set(str(len(snapshot["contacts"])))
        self.sync_var.set(
            f"{snapshot['synchrony']:.2f}"
            if snapshot["synchrony"] is not None
            else "Sin pares en movimiento"
        )
        self.movement_var.set(f"{snapshot['movement']:.2f}")
        self.opening_var.set(f"{snapshot['arm_opening']:.2f}")
        self.fps_var.set(f"{snapshot['fps']:.1f} fps")
        self.mode_var.set(snapshot["mode"])
        self.chord_var.set(snapshot["chord"])
        self.layers_var.set(", ".join(snapshot["layers"]) or "Ninguna")
        self.density_var.set(
            f"{snapshot['density']:.2f}"
            if snapshot["density"] is not None else "—"
        )
        self.intensity_var.set(
            f"{snapshot['intensity']:.2f}"
            if snapshot["intensity"] is not None else "—"
        )
        history = getattr(self, "metric_history", None)
        if history is not None:
            history.append((
                max(0.0, min(1.0, float(snapshot.get("movement", 0.0)))),
                max(0.0, min(1.0, float(snapshot.get("arm_opening", 0.0)))),
                max(0.0, min(1.0, float(snapshot.get("synchrony") or 0.0))),
            ))
            if len(history) > 60:
                del history[:-60]
            self._draw_metric_charts()
        self._render_people(snapshot)
        self._render_pairs(snapshot)
        self._render_contacts(snapshot)
        self._render_events(snapshot)

    def _render_people(self, snapshot):
        selected = self.people_tree.selection()
        selected_id = selected[0] if selected else None
        self.people_tree.delete(*self.people_tree.get_children())
        for person in snapshot["people"]:
            center = person["center"]
            velocity = person["velocity"]
            direction = person["direction"]
            item_id = str(person["id"])
            self.people_tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    item_id,
                    f"({center[0]:.3f}, {center[1]:.3f})",
                    f"{person['movement']:.3f}",
                    f"{velocity[0]:.3f}",
                    f"{velocity[1]:.3f}",
                    f"{person['speed']:.3f}",
                    f"{direction:.1f} deg" if direction is not None else "Quieto",
                ),
            )
        if selected_id and self.people_tree.exists(selected_id):
            self.people_tree.selection_set(selected_id)
            self._show_landmarks(selected_id)
        elif snapshot["people"]:
            first_id = str(snapshot["people"][0]["id"])
            self.people_tree.selection_set(first_id)
            self._show_landmarks(first_id)
        else:
            self.landmark_tree.delete(*self.landmark_tree.get_children())

    def _render_pairs(self, snapshot):
        self.distance_tree.delete(*self.distance_tree.get_children())
        for pair in snapshot["pairs"]:
            sync = pair["synchrony"]
            self.distance_tree.insert(
                "",
                "end",
                values=(
                    pair["first"],
                    pair["second"],
                    f"{pair['distance']:.3f}",
                    f"{sync:.3f}" if sync is not None else "Sin movimiento",
                ),
            )

    def _render_contacts(self, snapshot):
        self.contact_tree.delete(*self.contact_tree.get_children())
        for contact in snapshot["contacts"]:
            self.contact_tree.insert(
                "",
                "end",
                values=(
                    contact["kind"],
                    contact["first"],
                    contact["second"],
                    f"({contact['point1'][0]:.3f}, {contact['point1'][1]:.3f})",
                    f"({contact['point2'][0]:.3f}, {contact['point2'][1]:.3f})",
                ),
            )

    def _render_events(self, snapshot):
        self.events_tree.delete(*self.events_tree.get_children())
        for event in snapshot["events"]:
            self.events_tree.insert(
                "",
                "end",
                values=(
                    f"{event['beat']:.1f}",
                    event["instrument"],
                    event["note"],
                    f"{event['duration']:.2f}",
                    event["velocity"],
                ),
            )

    def _show_selected_landmarks(self, _event=None):
        selection = self.people_tree.selection()
        if selection:
            self._show_landmarks(selection[0])

    def _show_landmarks(self, track_id):
        self.landmark_tree.delete(*self.landmark_tree.get_children())
        if self.latest_snapshot is None:
            return
        landmarks = self.latest_snapshot["landmarks"].get(int(track_id), [])
        for index, point in enumerate(landmarks):
            point_name = mp.solutions.pose.PoseLandmark(index).name.replace(
                "_", " "
            ).title()
            self.landmark_tree.insert(
                "",
                "end",
                values=(
                    f"{index}: {point_name}",
                    self._format_optional(point["x"]),
                    self._format_optional(point["y"]),
                    self._format_optional(point["z"]),
                    self._format_optional(point["visibility"]),
                    self._format_optional(point["presence"]),
                ),
            )

    @staticmethod
    def _format_optional(value):
        return f"{value:.3f}" if value is not None else "—"


# ---------------------------------------------------------
# SISTEMA PRINCIPAL
# ---------------------------------------------------------

def main():
    root = tk.Tk()
    ResonantiaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
