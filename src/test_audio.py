import time
from audio_engine import AudioEngine


def main():
    audio = None

    try:
        audio = AudioEngine(
            soundfont_name="The_Absolute_Sega_FM_Soundfont_V2.sf2",
            sample_rate=44100,
            gain=0.7,
            bank=0,
            preset=48
        )

        audio.start()

        print("\nPRUEBA DE NOTA SOSTENIDA")
        print("Instrumento: Strings")
        print("La nota sonará durante 3 segundos.")

        audio.note_on(69, velocity=110)

        time.sleep(3)

        print("\nEnviando NOTE OFF...")
        resultado = audio.note_off(69)

        print("Resultado NOTE OFF:", resultado)

        time.sleep(2)

        print("\nPrueba finalizada.")

    except Exception as error:
        print("\nERROR:")
        print(error)

    finally:
        if audio is not None:
            audio.close()


if __name__ == "__main__":
    main()