"""Stage E, step 1: ASR text for the pieces of the speech test, with whisperkit-cli.

    python3 bench/run_asr.py --asr-model small --piece ES2004a.cut02 --piece IS1009a.cut02 \
        --piece TS3003a.cut01 --piece TS3003a.cut04
    python3 bench/run_asr.py --asr-model small --piece ES2004a.cut02 --max-seconds 10   # quick check

For each piece it cuts the meeting's wav (bench/audio/ami/MEETING.Mix-Headset.wav, 16 kHz mono) at the
piece's start and end into bench/results/asr/_wav/PIECE.wav, runs `whisperkit-cli transcribe` on it and
writes the text to bench/results/asr/<asr-model>/PIECE.txt (the file translate_eval.py reads for T1).
The raw report and the seconds taken go to bench/results/asr/<asr-model>/PIECE.report/ and PIECE.time.json.
A piece whose .txt exists is skipped (resume); --force redoes it. One piece at a time, one worker.
It loads a speech model: do not run it while Anne is running (8 GB Mac). Nothing is played.
Models: --asr-model small = ~/AnneProto/model, turbo = ~/AnneProto/turbo (override with --model-path).
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
AMI = os.path.join(HERE, "audio", "ami")
OUT = os.path.join(HERE, "results", "asr")
MODELS = {"small": "~/AnneProto/model", "turbo": "~/AnneProto/turbo"}
TOKENIZER = "~/AnneProto/tokenizer"


def cut_wav(src, dst, start, end):
    """Write seconds [start, end] of a PCM wav to dst. Returns the length written in seconds."""
    with wave.open(src, "rb") as w:
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
        w.setpos(max(0, int(start * rate)))
        frames = w.readframes(max(0, int((end - start) * rate)))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with wave.open(dst, "wb") as o:
        o.setnchannels(ch)
        o.setsampwidth(width)
        o.setframerate(rate)
        o.writeframes(frames)
    return len(frames) / (rate * width * ch)


def load_pieces(wanted):
    manifest = json.load(open(os.path.join(AMI, "prepared", "manifest.json")))
    by_id = {m["id"]: m for m in manifest}
    missing = [p for p in wanted if p not in by_id]
    if missing:
        raise SystemExit(f"unknown piece(s): {missing}; known: {sorted(by_id)}")
    return [by_id[p] for p in wanted]


def text_from_report(report_dir, wav_stem):
    """The CLI writes a JSON report (and others) into report_dir; take the 'text' of the JSON."""
    for path in sorted(glob.glob(os.path.join(report_dir, "*.json"))):
        try:
            data = json.load(open(path))
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            return data["text"].strip()
    return None


def transcribe(wav, model_path, report_dir, language):
    os.makedirs(report_dir, exist_ok=True)
    cmd = ["whisperkit-cli", "transcribe", "--audio-path", wav,
           "--model-path", os.path.expanduser(model_path),
           "--download-tokenizer-path", os.path.expanduser(TOKENIZER),
           "--language", language, "--concurrent-worker-count", "1",
           "--report", "--report-path", report_dir]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    secs = time.time() - t0
    if r.returncode != 0:
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-20:])
        raise SystemExit(f"whisperkit-cli failed (exit {r.returncode}); command: {' '.join(cmd)}\n{tail}")
    return secs, r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--asr-model", default="small")
    ap.add_argument("--model-path")
    ap.add_argument("--piece", action="append", required=True)
    ap.add_argument("--language", default="en")
    ap.add_argument("--max-seconds", type=float, help="only the first N seconds of each piece (quick check)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    model_path = args.model_path or MODELS.get(args.asr_model)
    if not model_path:
        raise SystemExit("give --model-path for an unknown --asr-model name")
    out_dir = os.path.join(OUT, args.asr_model + ("_check" if args.max_seconds else ""))
    os.makedirs(out_dir, exist_ok=True)
    for m in load_pieces(args.piece):
        txt = os.path.join(out_dir, m["id"] + ".txt")
        if os.path.exists(txt) and not args.force:
            print(f"{m['id']}: exists, skipped")
            continue
        src = os.path.join(AMI, f"{m['meeting']}.Mix-Headset.wav")
        end = m["end"] if not args.max_seconds else min(m["end"], m["start"] + args.max_seconds)
        wav = os.path.join(OUT, "_wav", m["id"] + (f".{int(args.max_seconds)}s" if args.max_seconds else "") + ".wav")
        length = cut_wav(src, wav, m["start"], end)
        report_dir = os.path.join(out_dir, m["id"] + ".report")
        secs, _ = transcribe(wav, model_path, report_dir, args.language)
        text = text_from_report(report_dir, m["id"])
        if not text:
            raise SystemExit(f"{m['id']}: no 'text' in the report under {report_dir}; look at the files there")
        open(txt, "w").write(text + "\n")
        json.dump({"audio_seconds": length, "seconds": secs, "model": args.asr_model, "model_path": model_path},
                  open(os.path.join(out_dir, m["id"] + ".time.json"), "w"))
        print(f"{m['id']}: {length:.0f} s of audio in {secs:.0f} s ({secs / length:.2f}x), {len(text.split())} words")


if __name__ == "__main__":
    sys.exit(main())
