
"""
RESONANTIA - Integración principal
Cámara + visión artificial + director musical
+ secuenciador + motor FluidSynth.

Ejecutar desde la raíz:
    python main.py
"""

import sys
import time
import threading
from copy import copy
from pathlib import Path

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


# ---------------------------------------------------------
# CONFIGURACIÓN MUSICAL
# ---------------------------------------------------------

CAMERA_INDEX = 0
BPM = 110

SOUNDFONT = "The_Absolute_Sega_FM_Soundfont_V2.sf2"

# Instrumentos iniciales del SoundFont.
# Los programas se numeran desde cero.
INSTRUMENTS = {
    "melody": (0, 48),  # Strings
    "bass": (0, 32),    # Acoustic Bass
    "chords": (0, 0),   # Acoustic Piano
    "kick": (0, 0),
    "hihat": (0, 0),
}

CHANNELS = {
    "melody": 0,
    "bass": 1,
    "chords": 2,
    "kick": 3,
    "hihat": 4,
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

        # La percusión se reserva para una configuración posterior.
        if instrument in ("kick", "hihat"):
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

        self.previous_mode = "silence"

        # Variables expresivas obtenidas del movimiento corporal.
        self.movement = 0.0
        self.arm_opening = 0.0

        self.running = True

        self.thread = threading.Thread(
            target=self.run,
            daemon=True,
        )

        self.thread.start()

    def update_state(self, state, movement=0.0, arm_opening=0.0):

        with self.lock:
            self.current_state = state

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

            events, decision = self.sequencer.create_bar(
                bar_number,
                state,
            )

            # El cuerpo modifica la interpretación de cada compás:
            # brazos abiertos = melodía más aguda; movimiento = más energía.
            expressive_events = []
            melody_events = []

            for event in events:
                expressive = copy(event)

                if expressive.instrument == "melody":
                    transposition = round(arm_opening * 7)
                    expressive.midi_note = min(
                        96, max(48, expressive.midi_note + transposition)
                    )

                    expressive.velocity = min(
                        127,
                        max(1, round(
                            expressive.velocity * (0.65 + movement * 0.65)
                        )),
                    )
                    melody_events.append(expressive)

                elif expressive.instrument in ("bass", "chords"):
                    expressive.velocity = min(
                        127,
                        max(1, round(
                            expressive.velocity * (0.80 + movement * 0.35)
                        )),
                    )

                expressive_events.append(expressive)

            # Cuando el movimiento es intenso, la melodía responde
            # con dos acentos adicionales dentro del compás.
            if movement >= 0.55 and melody_events:
                for source_event, beat in zip(melody_events[:2], (1.0, 3.0)):
                    accent = copy(source_event)
                    accent.beat = beat
                    accent.velocity = min(127, round(accent.velocity * 0.85))
                    expressive_events.append(accent)

            events = expressive_events

            if decision.mode == "silence":

                if self.previous_mode != "silence":
                    self.audio.silence()

                self.previous_mode = "silence"

                time.sleep(0.1)
                continue

            if self.previous_mode == "silence":
                print(
                    f"\nRESONANTIA: modo {decision.mode}"
                )

            elif self.previous_mode != decision.mode:
                self.audio.silence()

                print(
                    f"\nRESONANTIA: cambio a {decision.mode}"
                )

            self.previous_mode = decision.mode

            play_bar(
                events,
                self.audio,
                self.sequencer.bpm,
            )

            self.director.advance_bar()

            bar_number += 1

    def close(self):

        self.running = False

        self.thread.join(timeout=3)


# ---------------------------------------------------------
# INTERPRETACIÓN DEL MOVIMIENTO CORPORAL
# ---------------------------------------------------------

def analyze_movement(valid_poses, previous_centers, delta_time):
    """
    Calcula dos controles musicales a partir de los landmarks de MediaPipe.

    movement: desplazamiento del torso entre fotogramas (0 a 1).
    arm_opening: apertura de brazos respecto al ancho de hombros (0 a 1).

    No depende de atributos internos de los objetos del tracker:
    utiliza directamente los landmarks normalizados de MediaPipe.
    """
    centers = []
    openings = []

    for landmarks, _detection in valid_poses:
        # MediaPipe Pose: hombros 11/12, muñecas 15/16 y caderas 23/24.
        required = (11, 12, 15, 16, 23, 24)
        if len(landmarks) <= max(required):
            continue

        left_shoulder = landmarks[11]
        right_shoulder = landmarks[12]
        left_wrist = landmarks[15]
        right_wrist = landmarks[16]
        left_hip = landmarks[23]
        right_hip = landmarks[24]

        torso_x = (
            left_shoulder.x + right_shoulder.x
            + left_hip.x + right_hip.x
        ) / 4.0
        torso_y = (
            left_shoulder.y + right_shoulder.y
            + left_hip.y + right_hip.y
        ) / 4.0
        centers.append((torso_x, torso_y))

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

    displacements = []
    for index, center in enumerate(centers):
        if index < len(previous_centers):
            old_x, old_y = previous_centers[index]
            dx = center[0] - old_x
            dy = center[1] - old_y
            displacements.append((dx * dx + dy * dy) ** 0.5)

    if displacements and delta_time > 0:
        speed = sum(displacements) / len(displacements) / delta_time
        movement = min(1.0, speed / 0.9)
    else:
        movement = 0.0

    average_opening = (
        sum(openings) / len(openings) if openings else 0.8
    )
    arm_opening = max(
        0.0, min(1.0, (average_opening - 0.8) / 1.7)
    )

    return movement, arm_opening, centers


# ---------------------------------------------------------
# SISTEMA PRINCIPAL
# ---------------------------------------------------------

def main():

    camera = None
    audio = None
    worker = None

    try:

        print("=" * 50)
        print("       RESONANTIA - SISTEMA INTERACTIVO")
        print("=" * 50)

        # Inicializar audio.
        audio = ResonantiaAudio()

        # Inicializar director y secuenciador.
        worker = MusicWorker(audio)

        # Inicializar cámara.
        if not vision.MODEL_PATH.is_file():

            raise FileNotFoundError(
                "No se encuentra el modelo MediaPipe:\n"
                f"{vision.MODEL_PATH}"
            )

        camera = cv2.VideoCapture(CAMERA_INDEX)

        if not camera.isOpened():

            raise RuntimeError(
                "No se pudo abrir la cámara."
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

        tracker = vision.PoseTracker()

        print("\nRESONANTIA INICIADO.")
        print("Muévete frente a la cámara.")
        print("Presiona ESC para salir.\n")

        with mp.tasks.vision.PoseLandmarker.create_from_options(
            options
        ) as landmarker:

            # Valores iniciales para comparar el primer fotograma.
            # Evita usar previous_frame_time antes de haberlo definido.
            previous_frame_time = time.monotonic()
            previous_centers = []

            while True:

                success, frame = camera.read()

                if not success:
                    break

                timestamp_ns = time.monotonic_ns()

                rgb = cv2.cvtColor(
                    frame,
                    cv2.COLOR_BGR2RGB,
                )

                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb,
                )

                result = landmarker.detect_for_video(
                    image,
                    timestamp_ns // 1_000_000,
                )

                valid_poses = []

                for landmarks in result.pose_landmarks:

                    detection = vision._make_detection(
                        landmarks
                    )

                    if detection is not None:
                        valid_poses.append(
                            (landmarks, detection)
                        )

                tracked = tracker.update(
                    [detection for _, detection in valid_poses],
                    timestamp_ns / 1_000_000_000,
                )

                interactions = vision._detect_interactions(
                    tracked
                )

                synchrony = logic.calculate_group_synchrony(
                    [person.velocity for person in tracked]
                )

                # Convertir detecciones en estado musical.
                state = MusicState(
                    people_count=len(tracked),
                    contact_detected=bool(interactions),
                    synchrony=(
                        synchrony
                        if synchrony is not None
                        else 0.0
                    ),
                )

                current_frame_time = time.monotonic()
                delta_time = max(
                    0.001, current_frame_time - previous_frame_time
                )
                previous_frame_time = current_frame_time

                movement, arm_opening, previous_centers = analyze_movement(
                    valid_poses,
                    previous_centers,
                    delta_time,
                )

                worker.update_state(
                    state,
                    movement=movement,
                    arm_opening=arm_opening,
                )

                # Dibujar las poses.
                for (landmarks, _), person in zip(
                    valid_poses,
                    tracked,
                ):

                    vision._draw_pose(
                        frame,
                        landmarks,
                    )

                # Información de la instalación.
                mode = worker.previous_mode

                cv2.putText(
                    frame,
                    f"Personas: {len(tracked)}",
                    (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2,
                )

                cv2.putText(
                    frame,
                    f"Contactos: {len(interactions)}",
                    (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255),
                    2,
                )

                cv2.putText(
                    frame,
                    f"Sincronia: {synchrony or 0:.2f}",
                    (20, 105),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 0),
                    2,
                )

                cv2.putText(
                    frame,
                    f"Movimiento: {movement:.2f}",
                    (20, 175),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 200, 255),
                    2,
                )

                cv2.putText(
                    frame,
                    f"Apertura brazos: {arm_opening:.2f}",
                    (20, 210),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 180, 0),
                    2,
                )

                cv2.putText(
                    frame,
                    f"Modo musical: {mode}",
                    (20, 140),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                )

                cv2.imshow(
                    "RESONANTIA - Camara y musica",
                    frame,
                )

                if cv2.waitKey(1) & 0xFF == 27:
                    break

    except KeyboardInterrupt:

        print("\nCierre solicitado.")

    finally:

        if worker is not None:
            worker.close()

        if audio is not None:
            audio.close()

        if camera is not None:
            camera.release()

        cv2.destroyAllWindows()

        print("\nRESONANTIA: sistema cerrado.")


if __name__ == "__main__":
    main()
