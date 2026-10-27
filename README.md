# Resonantia 🎶
Instalación artística e interactiva que traduce el movimiento y la conexión humana en música generativa.

## Integrantes
* Salomon David Ramirez
* Juan Pablo Rueda Sanchez
* Juan Esteban Galindo Mina

## Descripción de la Idea
La obra busca demostrar que la tecnología puede utilizarse para fortalecer la interacción humana. A medida que las personas se acercan, se mueven o interactúan en el espacio, la composición musical evoluciona desde un simple pulso rítmico inicial hasta una obra completa.

# pasos a seguir 

crea un entorno virtual 

python -m venv ambiente

despues entra al entorno 

ambiente\Scripts\activate

Luego, instala las librerías listadas en tu archivo requirements.txt

pip install -r requirements.txt


# para abrir el archivo desde la terminal se hace asi 
python src/vision.py

## Deteccion de varias personas

El modulo de vision usa MediaPipe Pose Landmarker para detectar hasta 4 personas
por fotograma. La camara sigue configurada con el indice `0`.

Descarga una vez el modelo oficial Lite desde PowerShell, en la raiz del proyecto:

```powershell
New-Item -ItemType Directory -Force assets
Invoke-WebRequest `
  -Uri "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task" `
  -OutFile "assets/pose_landmarker_lite.task"
```

El archivo de modelo no se incluye en Git. Luego ejecuta `python src/vision.py`.
La ventana muestra el esqueleto, el centro del cuerpo, un ID temporal y el
desplazamiento normalizado entre fotogramas. El seguimiento asocia detecciones
por cercania de sus centros y conserva IDs durante ausencias breves; puede
confundir IDs si las personas se cruzan, se ocultan o se mueven mucho entre
fotogramas. No es un identificador de personas.

La vision tambien marca posibles contactos entre personas: muñeca con muñeca
como posible contacto de manos, o muñeca con antebrazo como posible contacto
de brazos. Es una estimacion basada en la distancia entre puntos 2D; no confirma
que haya agarre fisico y puede variar con la perspectiva, la oclusion y la
posicion de la camara.

## Metricas de interaccion

La interfaz muestra la distancia entre los centros de cada pareja y, por
participante, el desplazamiento entre fotogramas, la velocidad y la direccion
de movimiento. Estas medidas se calculan en coordenadas normalizadas de la
imagen: la velocidad se expresa en unidades normalizadas por segundo, no en
unidades fisicas, porque no se ha calibrado la escala de la escena. La direccion
usa los ejes de la imagen (0 grados a la derecha y 90 grados hacia abajo).

La sincronia instantanea (de 0 a 1) promedia la similitud de direccion y rapidez
entre las parejas que se estan moviendo en ese fotograma. No mide una tendencia
de sincronizacion sostenida a lo largo del tiempo; las personas inmoviles no
participan en ese calculo. El valor combina la alineacion de las direcciones con
la relacion entre las rapideces de cada pareja.