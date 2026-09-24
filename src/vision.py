import cv2
import mediapipe as mp

# Inicializar las herramientas de dibujo y el modelo de Pose de MediaPipe
mp_drawing = mp.solutions.drawing_utils
mp_pose = mp.solutions.pose

# Iniciar la captura de video desde la cámara web predeterminada (0)
cap = cv2.VideoCapture(3)

print("Iniciando Resonantia... Presiona la tecla 'ESC' para salir.")

# Configurar el modelo de estimación de pose
with mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            print("No se pudo acceder a la cámara.")
            break

        # Convertir la imagen de BGR (OpenCV) a RGB (MediaPipe)
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image.flags.writeable = False
        
        # Procesar la imagen para detectar el esqueleto
        results = pose.process(image)

        # Regresar la imagen a BGR para poder mostrarla con OpenCV
        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        # Si se detecta un cuerpo, dibujar las conexiones del esqueleto en la pantalla
        if results.pose_landmarks:
            mp_drawing.draw_landmarks(
                image, 
                results.pose_landmarks, 
                mp_pose.POSE_CONNECTIONS
            )

        # Mostrar la ventana con el resultado del prototipo
        cv2.imshow('Resonantia - Prototipo de Vision', image)

        # Cerrar la ventana si se presiona la tecla 'ESC' (código 27)
        if cv2.waitKey(5) & 0xFF == 27:
            break

# Liberar la cámara y cerrar todas las ventanas abiertas
cap.release()
cv2.destroyAllWindows()