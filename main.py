
"""
RESONANTIA - Integración principal
Cámara + visión artificial + director musical
+ secuenciador + motor FluidSynth.

Ejecutar desde la raíz:
    python main.py
"""

import base64
import queue
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
from music_sequencer import MusicSequencer
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

def play_bar(events, audio, bpm):

    seconds_per_beat = 60.0 / bpm

    start = time.monotonic()

    pending = sorted(
        events,
        key=lambda event: event.beat
    )

    for event in pending:

        target = start + event.beat * seconds_per_beat

        remaining = target - time.monotonic()

        if remaining > 0:
            time.sleep(remaining)

        audio.play_event(event)

    # Esperar el final del compás.
    bar_duration = 4 * seconds_per_beat

    remaining = (
        start + bar_duration - time.monotonic()
    )

    if remaining > 0:
        time.sleep(remaining)


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

        self.previous_mode = "silence"

        # Variables expresivas obtenidas del movimiento corporal.
        self.movement = 0.0
        self.arm_opening = 0.0
        self.phrase_detector = MotionPhraseDetector()
        self.motion_phrase = self.phrase_detector.update(0.0, 0.0)

        self.running = True

        self.thread = threading.Thread(
            target=self.run,
            daemon=True,
        )

        self.thread.start()

    def update_state(self, state, movement=0.0, arm_opening=0.0, delta_time=1.0 / 30.0):

        with self.lock:
            self.current_state = state
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

        while self.running:

            with self.lock:
                state = self.current_state
                movement = self.movement
                arm_opening = self.arm_opening
                state.movement = movement
                state.arm_opening = arm_opening
                state.motion_phase = self.motion_phrase.phase.value
                state.motion_onset = self.motion_phrase.onset

            events, decision = self.sequencer.create_bar(
                bar_number,
                state,
            )

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

                time.sleep(0.1)
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
                )
            else:
                time.sleep(4 * 60.0 / self.sequencer.bpm)

            # La progresión cambia cada dos compases: cada acorde de piano
            # conserva su armonía durante aproximadamente cuatro segundos.
            if bar_number % 2 == 0:
                self.director.advance_bar()

            bar_number += 1

    def close(self):

        self.running = False

        self.thread.join(timeout=3)


# ---------------------------------------------------------
# INTERPRETACIÓN DEL MOVIMIENTO CORPORAL
# ---------------------------------------------------------

def analyze_movement(valid_poses, tracked_poses, delta_time):
    """
    Calcula controles musicales usando las velocidades del tracker y
    la apertura de brazos obtenida de los landmarks de MediaPipe.

    Cada velocidad proviene de TrackedPose.velocity y está asociada a su
    track_id, evitando comparar personas distintas entre fotogramas.
    """
    speeds = []
    openings = []

    # PoseTracker conserva el orden de las detecciones del fotograma actual.
    for (landmarks, _detection), person in zip(valid_poses, tracked_poses):
        vx, vy = person.velocity
        speeds.append((vx * vx + vy * vy) ** 0.5)

        # MediaPipe Pose: hombros 11/12 y muñecas 15/16.
        required = (11, 12, 15, 16)
        if len(landmarks) <= max(required):
            continue

        left_shoulder = landmarks[11]
        right_shoulder = landmarks[12]
        left_wrist = landmarks[15]
        right_wrist = landmarks[16]

        shoulder_width = (
            (left_shoulder.x - right_shoulder.x) ** 2
            + (left_shoulder.y - right_shoulder.y) ** 2
        ) ** 0.5
        wrist_width = (
            (left_wrist.x - right_wrist.x) ** 2
            + (left_wrist.y - right_wrist.y) ** 2
        ) ** 0.5

        if shoulder_width > 0.001:
            openings.append(wrist_width / shoulder_width)

    if speeds and delta_time > 0:
        average_speed = sum(speeds) / len(speeds)
        movement = min(1.0, average_speed / 0.9)
    else:
        movement = 0.0

    average_opening = sum(openings) / len(openings) if openings else 0.8
    arm_opening = max(0.0, min(1.0, (average_opening - 0.8) / 1.7))
    return movement, arm_opening


# ---------------------------------------------------------
# INTERFAZ GRAFICA
# ---------------------------------------------------------

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
        self.audio_var = tk.BooleanVar(value=False)
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

        self._build_interface()
        self.root.after(40, self._poll_updates)

    def _build_interface(self):
        self.root.columnconfigure(0, weight=1)

        header = ttk.Frame(self.root, padding=(18, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="RESONANTIA",
            font=("Segoe UI", 22, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Explora el movimiento y crea musica con otras personas.",
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        controls = ttk.LabelFrame(
            self.root, text="Controles", padding=(12, 8)
        )
        controls.grid(
            row=1, column=0, sticky="ew", padx=18, pady=(0, 8)
        )
        ttk.Label(controls, text="Camara:").grid(row=0, column=0, padx=4)
        self.camera_selector = ttk.Combobox(
            controls,
            textvariable=self.camera_var,
            values=tuple(str(index) for index in range(6)),
            width=5,
            state="readonly",
        )
        self.camera_selector.grid(row=0, column=1, padx=4)
        self.audio_check = ttk.Checkbutton(
            controls,
            text="Reproducir musica",
            variable=self.audio_var,
        )
        self.audio_check.grid(row=0, column=2, padx=8)
        self.start_button = ttk.Button(
            controls, text="Iniciar", command=self.start
        )
        self.start_button.grid(row=0, column=3, padx=4)
        self.stop_button = ttk.Button(
            controls, text="Detener", command=self.stop, state="disabled"
        )
        self.stop_button.grid(row=0, column=4, padx=4)
        ttk.Button(controls, text="Salir", command=self.close).grid(
            row=0, column=5, padx=(4, 0)
        )

        content = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        content.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 8))

        video_panel = ttk.Frame(content, padding=6)
        data_panel = ttk.Frame(content, padding=6)
        content.add(video_panel, weight=3)
        content.add(data_panel, weight=2)
        video_panel.columnconfigure(0, weight=1)
        video_panel.rowconfigure(0, weight=1)

        self.video_label = ttk.Label(
            video_panel,
            text="Pulsa Iniciar para activar la camara.\n"
            "Colocate en un lugar bien iluminado y de cuerpo visible.",
            anchor="center",
            justify="center",
            background="#17212b",
            foreground="#f2f5f7",
            font=("Segoe UI", 13),
        )
        self.video_label.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            video_panel,
            text="Consejo: deja espacio entre participantes y evita "
            "cubrir las manos para mejorar la deteccion.",
            wraplength=760,
        ).grid(row=1, column=0, sticky="ew", pady=(8, 0))

        data_panel.columnconfigure(0, weight=1)
        data_panel.rowconfigure(1, weight=1)
        summary = ttk.LabelFrame(
            data_panel, text="Estado en vivo", padding=(10, 8)
        )
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for column in range(3):
            summary.columnconfigure(column, weight=1)
        self._summary_item(summary, "Personas", self.count_var, 0, 0)
        self._summary_item(summary, "Posibles contactos", self.contacts_var, 0, 1)
        self._summary_item(summary, "Sincronia grupal", self.sync_var, 0, 2)
        self._summary_item(summary, "Movimiento (0-1)", self.movement_var, 1, 0)
        self._summary_item(summary, "Apertura de brazos (0-1)", self.opening_var, 1, 1)
        self._summary_item(summary, "Velocidad de video", self.fps_var, 1, 2)
        self._summary_item(summary, "Modo musical", self.mode_var, 2, 0)
        self._summary_item(summary, "Acorde actual", self.chord_var, 2, 1)

        self.notebook = ttk.Notebook(data_panel)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self.people_tree = self._add_table_tab(
            "Personas",
            (
                ("id", "ID", 48),
                ("center", "Centro (x, y)", 105),
                ("movement", "Desplazamiento", 100),
                ("vx", "Velocidad X", 85),
                ("vy", "Velocidad Y", 85),
                ("speed", "Rapidez", 75),
                ("direction", "Direccion", 80),
            ),
        )
        self.people_tree.bind("<<TreeviewSelect>>", self._show_selected_landmarks)
        self.distance_tree = self._add_table_tab(
            "Distancias",
            (
                ("first", "Persona A", 85),
                ("second", "Persona B", 85),
                ("distance", "Distancia normalizada", 145),
                ("synchrony", "Sincronia (0-1)", 120),
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

        landmark_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(landmark_tab, text="Puntos corporales")
        ttk.Label(
            landmark_tab,
            text="Selecciona una persona para ver sus 33 landmarks "
            "(coordenadas normalizadas y visibilidad).",
            wraplength=440,
        ).pack(anchor="w", pady=(0, 6))
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

        music_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(music_tab, text="Musica")
        ttk.Label(
            music_tab,
            text=f"Tempo: {BPM} BPM  |  Tonalidad: La menor  |  Compas: 4/4",
        ).pack(anchor="w", pady=(0, 6))
        music_summary = ttk.Frame(music_tab)
        music_summary.pack(fill="x", pady=(0, 8))
        ttk.Label(music_summary, text="Capas activas:").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Label(
            music_summary, textvariable=self.layers_var, wraplength=330
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(music_summary, text="Densidad melodica:").grid(
            row=1, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Label(music_summary, textvariable=self.density_var).grid(
            row=1, column=1, sticky="w"
        )
        ttk.Label(music_summary, text="Intensidad:").grid(
            row=2, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Label(music_summary, textvariable=self.intensity_var).grid(
            row=2, column=1, sticky="w"
        )
        self.events_tree = self._create_tree(
            music_tab,
            (
                ("beat", "Tiempo (pulso)", 105),
                ("instrument", "Instrumento", 105),
                ("note", "Nota MIDI", 85),
                ("duration", "Duracion", 85),
                ("velocity", "Velocidad", 85),
            ),
        )

        footer = ttk.Frame(self.root, padding=(14, 6))
        footer.grid(row=3, column=0, sticky="ew")
        ttk.Label(footer, textvariable=self.status_var).pack(side="left")
        ttk.Label(
            footer,
            text="Las distancias y coordenadas son relativas a la imagen; "
            "el contacto es una estimacion, no una confirmacion fisica.",
            wraplength=850,
        ).pack(side="right")

    @staticmethod
    def _summary_item(parent, title, variable, row, column):
        item = ttk.Frame(parent, padding=(4, 3))
        item.grid(row=row, column=column, sticky="ew")
        ttk.Label(item, text=title, font=("Segoe UI", 8)).pack(anchor="w")
        ttk.Label(
            item, textvariable=variable, font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")

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
        horizontal_scrollbar = ttk.Scrollbar(
            container, orient="horizontal", command=tree.xview
        )
        tree.configure(
            yscrollcommand=scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        for name, heading, width in columns:
            tree.heading(name, text=heading)
            tree.column(name, width=width, minwidth=55, stretch=True)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
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
        self.camera_selector.configure(state="disabled")
        self.audio_check.configure(state="disabled")
        self.status_var.set("Iniciando camara y modelo de pose...")
        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(camera_index, self.audio_var.get(), self.stop_event),
            daemon=True,
        )
        self.capture_thread.start()

    def stop(self):
        if self.stop_event is not None and self.is_running:
            self.stop_event.set()
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
                        delta_time=delta_time
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
                    self.camera_selector.configure(state="readonly")
                    self.audio_check.configure(state="normal")
                    if self.is_closing:
                        self.root.destroy()
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
