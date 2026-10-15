"""Transcription with whisper-large-v3-turbo (more accurate, about 5 s per chunk on M1).

Run: python transcribe_turbo.py   (options and output switching: see transcribe_stream.py)
"""

from transcribe_stream import main

MODEL = "mlx-community/whisper-large-v3-turbo"

if __name__ == "__main__":
    main(MODEL)
