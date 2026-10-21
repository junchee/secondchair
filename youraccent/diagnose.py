"""yourAccent, first test (A): does the speech recognizer notice a mispronounced word?

You read sentences aloud. Whisper writes down what it heard, word by word, with how sure it
was. Each word of the sentence is then marked:
    ok      heard as written, and Whisper was sure
    doubt   heard as written, but Whisper was not sure (maybe the sound was unclear)
    wrong   heard as a different word (the sound may have been wrong)
    missed  not heard

Run, from the secondchair folder:
    .venv/bin/python -m youraccent.diagnose                 built-in sentences (L/R, th, B/V ...)
    .venv/bin/python -m youraccent.diagnose --text my.txt   your own script, as a text file
Options: --max N, --model small|turbo, --mic NAME, --keep, --replay DIR, --doubt P, --list-mics

Nothing is played and nothing leaves this Mac. Recordings are deleted unless you pass --keep.
A word marked ok does not prove the sound was right: Whisper may correct a small error on its
own. That is exactly what this test is meant to show.
"""

import argparse
import datetime
import fcntl
import os
import re
import sys
import threading
import time
import wave
from difflib import SequenceMatcher

import numpy as np

from youraccent.sentences import TRAPS, split_sentences

DATA_DIR = os.path.expanduser("~/yourAccent")
MODELS = {
    "small": "mlx-community/whisper-small-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}
RATE = 16000
MAX_TOKENS = 160
SECONDCHAIR_LOCK = "/tmp/secondchair.lock"
DOUBT = 0.6
# Short function words and the first word of a recording often get a low score for reasons
# that have nothing to do with the sound, so they are never marked "doubt".
SKIP_DOUBT = {"the", "a", "an", "of", "to", "and", "is", "are", "on", "in", "i", "it", "at", "or"}


def norm(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def compare(expected, heard, doubt=DOUBT):
    """Line up the written sentence with the heard words.

    `heard` is a list of (word, probability). Returns (rows, extra): one row per written word,
    (word, status, heard_as, probability), and the heard words that were not in the sentence.
    """
    shown = [w.strip(".,?!;:\"()") for w in expected.split() if norm(w)]
    want = [norm(w) for w in shown]
    got = [(norm(w), p) for w, p in heard if norm(w)]
    rows = [None] * len(want)
    extra = []
    matcher = SequenceMatcher(None, want, [g[0] for g in got], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                i, p = i1 + k, got[j1 + k][1]
                unsure = p < doubt and i > 0 and want[i] not in SKIP_DOUBT
                rows[i] = (shown[i], "doubt" if unsure else "ok", want[i], p)
        elif tag == "replace":
            block = got[j1:j2]
            for k, i in enumerate(range(i1, i2)):
                if i2 - i1 == j2 - j1:
                    heard_as, p = block[k]
                else:
                    heard_as, p = " ".join(g[0] for g in block), min(g[1] for g in block)
                rows[i] = (shown[i], "wrong", heard_as, p)
        elif tag == "delete":
            for i in range(i1, i2):
                rows[i] = (shown[i], "missed", "", 0.0)
        else:  # insert: words that were heard but are not in the sentence
            extra.extend(got[j1:j2])
    return rows, extra


def listen(audio, model, doubt=DOUBT):
    """Whisper's text and the comparison for one recording (16 kHz mono float32)."""
    import mlx_whisper

    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=MODELS[model],
        language="en",
        condition_on_previous_text=False,  # and no prompt with the script: that would hide errors
        temperature=0.0,
        sample_len=MAX_TOKENS,
        word_timestamps=True,
    )
    words = [(w["word"], w["probability"]) for s in result["segments"] for w in s.get("words", [])]
    return result["text"].strip(), words


def read_wav(path):
    with wave.open(path) as f:
        data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        rate = f.getframerate()
    return to_rate(data, rate, RATE)


def write_wav(path, audio):
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def to_rate(audio, rate, target):
    if audio.size == 0 or rate == target:
        return audio.astype(np.float32)
    n_out = int(round(audio.size * target / rate))
    return np.interp(np.linspace(0, audio.size - 1, n_out), np.arange(audio.size), audio).astype(np.float32)


class Recorder:
    """Records the microphone from Enter to Enter."""

    def __init__(self, device):
        import sounddevice as sd

        self.sd = sd
        self.device = device
        self.rate = int(sd.query_devices(device)["default_samplerate"])

    def record(self):
        frames = []

        def callback(indata, count, info, status):
            frames.append(indata[:, 0].copy())

        with self.sd.InputStream(device=self.device, channels=1, samplerate=self.rate, callback=callback):
            input("   ... 녹음 중. 다 읽었으면 Enter ")
        audio = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
        return to_rate(audio, self.rate, RATE)


def mark(status):
    return {"ok": "  ok   ", "doubt": " ?doubt", "wrong": "XWRONG ", "missed": "XmissED"}[status]


def show(expected, text, rows, extra, targets, out):
    def say(line=""):
        print(line)
        out.append(line)

    say(f"   들은 것: {text or '(아무것도 못 들음)'}")
    problems = [r for r in rows if r[1] != "ok"]
    if not problems and not extra:
        say("   모든 단어가 문장대로 들렸고 확신도 높았습니다.")
    for word, status, heard_as, p in problems:
        detail = f"→ {heard_as}" if status == "wrong" else ""
        flag = "  <== 시험 단어" if word.lower() in targets else ""
        say(f"   {mark(status)} {word:<12} {detail:<14} (확신 {p:.2f}){flag}")
    if extra:
        say("   더 들린 말: " + " ".join(w for w, _ in extra))
    for word, status, heard_as, p in rows:
        if status == "ok" and word.lower() in targets:
            say(f"   {mark(status)} {word:<12} (확신 {p:.2f})  <== 시험 단어, 문제 없이 들림")


def main():
    parser = argparse.ArgumentParser(description="yourAccent first test: does Whisper notice a wrong sound?")
    parser.add_argument("--text", metavar="FILE", help="your own script (text file) instead of the built-in sentences")
    parser.add_argument("--max", type=int, default=8, help="most sentences to read (default 8)")
    parser.add_argument("--model", choices=MODELS, default="small", help="small is fast; turbo is bigger and slower")
    parser.add_argument("--mic", metavar="NAME", help="part of the microphone's name (default: as in secondchair)")
    parser.add_argument("--keep", action="store_true", help="keep the recordings in ~/yourAccent/test/ (default: delete)")
    parser.add_argument("--replay", metavar="DIR", help="check kept recordings again (no microphone), e.g. with another model")
    parser.add_argument("--doubt", type=float, default=DOUBT, help=f"below this score a right word counts as doubtful (default {DOUBT})")
    parser.add_argument("--list-mics", action="store_true")
    args = parser.parse_args()

    if args.list_mics:
        from audio_test import list_inputs

        list_inputs()
        return

    sentences = None
    if args.replay:
        with open(os.path.join(args.replay, "sentences.txt"), encoding="utf-8") as f:
            sentences = [(line.rstrip("\n"), (), "") for line in f if line.strip()]
    elif args.text:
        if args.text.lower().endswith(".pdf"):
            sys.exit("PDF는 다음 단계에서 지원합니다. 지금은 글을 텍스트 파일(.txt)로 저장해서 쓰세요.")
        with open(os.path.expanduser(args.text), encoding="utf-8") as f:
            sentences = [(s, (), "") for s in split_sentences(f.read())]
        if not sentences:
            sys.exit("파일에서 문장을 찾지 못했습니다.")
    else:
        sentences = list(TRAPS)
    sentences = sentences[: args.max]

    recorder = None
    if not args.replay:
        # Practice sound must never reach a meeting, and the meeting app owns the microphone's route.
        guard = open(SECONDCHAIR_LOCK, "w")
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(guard, fcntl.LOCK_UN)
        except BlockingIOError:
            sys.exit("secondchair(회의 프로그램)가 켜져 있습니다. 먼저 끝낸 뒤에 시험하세요.")
        from audio_test import find_input, find_mic

        device = find_input(args.mic) if args.mic else find_mic()
        if device is None:
            sys.exit("마이크를 찾지 못했습니다. --list-mics 로 목록을 보고 --mic 이름 으로 고르세요.")
        recorder = Recorder(device)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = args.replay or os.path.join(DATA_DIR, "test", stamp)
    if args.keep and not args.replay:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        with open(os.path.join(folder, "sentences.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(s for s, _, _ in sentences) + "\n")

    out = []
    tally = {"ok": 0, "doubt": 0, "wrong": 0, "missed": 0}
    trap_hits = []  # (word, status) for the built-in test words
    print(f"\nyourAccent 첫 시험: 문장 {len(sentences)}개, 모델 {args.model}")
    if recorder:
        print("각 문장은 Enter로 시작하고 Enter로 끝냅니다. 건너뛰기: s + Enter, 그만하기: q + Enter\n")
    try:
        for n, (sentence, targets, sounds) in enumerate(sentences, 1):
            print(f"[{n}/{len(sentences)}] 읽어 주세요" + (f"   (소리: {sounds})" if sounds else ""))
            print(f"   {sentence}")
            out.append(f"[{n}] {sentence}")
            path = os.path.join(folder, f"{n:02d}.wav")
            if args.replay:
                audio = read_wav(path)
            else:
                answer = input("   준비되면 Enter ").strip().lower()
                if answer == "q":
                    break
                if answer == "s":
                    continue
                audio = recorder.record()
                if audio.size < RATE * 0.5:
                    print("   너무 짧아서 건너뜁니다.\n")
                    continue
                if float(np.abs(audio).max()) < 0.02:
                    print("   (소리가 아주 작습니다. 마이크를 확인하세요.)")
                if args.keep:
                    write_wav(path, audio)
            started = time.time()
            text, words = listen(audio, args.model, args.doubt)
            rows, extra = compare(sentence, words, args.doubt)
            print(f"   ({time.time() - started:.1f}초)")
            show(sentence, text, rows, extra, set(targets), out)
            for word, status, _, _ in rows:
                tally[status] += 1
                if word.lower() in targets:
                    trap_hits.append((word.lower(), status))
            print()
    except (KeyboardInterrupt, EOFError):
        print("\n중단했습니다. 여기까지의 결과를 정리합니다.")

    total = sum(tally.values())
    if total:
        print("=" * 60)
        print(f"단어 {total}개: ok {tally['ok']}, 의심 {tally['doubt']}, 틀림 {tally['wrong']}, 못 들음 {tally['missed']}")
        if trap_hits:
            caught = [w for w, s in trap_hits if s != "ok"]
            print(f"시험 단어 {len(trap_hits)}개 중 문제로 잡힌 것 {len(caught)}개: {', '.join(caught) or '없음'}")
        print("ok라고 나온 시험 단어는 '정말 맞게 발음했다'가 아니라 'Whisper가 알아들었다'는 뜻입니다.")
        os.makedirs(os.path.join(DATA_DIR, "test_reports"), mode=0o700, exist_ok=True)
        report = os.path.join(DATA_DIR, "test_reports", f"{stamp}.txt")
        with open(report, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        print(f"결과 파일: {report}")
        if args.keep and not args.replay:
            print(f"녹음 보관: {folder}  (다른 모델로 다시 보려면 --replay {folder} --model turbo)")


if __name__ == "__main__":
    main()
