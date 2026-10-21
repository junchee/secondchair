"""yourAccent: a small local web app for English pronunciation practice.

A separate program from secondchair (own port, own data folder), meant to feel like its own app.
  - Listening training with minimal pairs (light / right ...), spoken by Kokoro voices.
  - Script practice: read a sentence aloud, Whisper marks the words, hear the right sound and your own.
  - Review: words and sentences that went wrong come back later.

Run:  python -m youraccent            (opens the page)
Data: ~/yourAccent  (override with YOURACCENT_HOME); port 8766 (override with YOURACCENT_PORT)
"""

import argparse
import collections
import fcntl
import io
import json
import os
import sys
import threading
import uuid
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import numpy as np

from youraccent import voices
from youraccent.judge import WhisperJudge
from youraccent.materials import Materials, clean_text, pdf_text
from youraccent.pairs import BY_ID, PAIRS
from youraccent.review import Review
from youraccent.store import Store
from youraccent.tts import SPEEDS, TTS, WORD
from youraccent.worker import Worker

HOME = os.path.expanduser(os.environ.get("YOURACCENT_HOME", "~/yourAccent"))
PORT = int(os.environ.get("YOURACCENT_PORT", "8766"))
JUDGE_MODEL = os.environ.get("YOURACCENT_JUDGE_MODEL", "small")
SECONDCHAIR_LOCK = "/tmp/secondchair.lock"
OWN_LOCK = os.environ.get("YOURACCENT_LOCK", "/tmp/youraccent.lock")  # tests use their own, so they never clash with a running copy
PAGE = os.path.join(os.path.dirname(__file__), "ui", "index.html")
RATE = 16000
MAX_BODY = 25_000_000  # a minute of audio is about 6 MB; a PDF of a lecture can be bigger
MAX_ATTEMPTS = 30  # recent readings kept in memory (never on disk) so the own-sound clips can be played


def refuse_if_secondchair_runs():
    """Practice sound played to the default output would go into a meeting, so never run together."""
    guard = open(SECONDCHAIR_LOCK, "a")
    try:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(guard, fcntl.LOCK_UN)
    except BlockingIOError:
        sys.exit("secondchair(회의 프로그램)가 켜져 있습니다. 먼저 끝낸 뒤에 yourAccent를 켜세요.")
    finally:
        guard.close()


def claim_single_instance():
    lock = open(OWN_LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f"yourAccent가 이미 켜져 있습니다. 브라우저에서 http://127.0.0.1:{PORT}/ 를 여세요.")
    return lock  # keep it open: the lock lasts until this process ends


def wav_to_16k(data):
    """16-bit PCM wav bytes -> float32 mono at 16 kHz (the first channel if there are several)."""
    with wave.open(io.BytesIO(data)) as f:
        channels, width, rate = f.getnchannels(), f.getsampwidth(), f.getframerate()
        raw = f.readframes(f.getnframes())
    if width != 2:
        raise ValueError("16-bit wav only")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    if channels > 1:
        audio = audio[: len(audio) // channels * channels].reshape(-1, channels)[:, 0]
    if rate != RATE and audio.size:
        n_out = int(round(audio.size * RATE / rate))
        audio = np.interp(np.linspace(0, audio.size - 1, n_out), np.arange(audio.size), audio).astype(np.float32)
    return audio


def wav_bytes(audio):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return buffer.getvalue()


def make_handler(ctx):
    pool = set(voices.ALL)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _host_ok(self):
            # Only this Mac's own page may talk to the server (guards against other sites
            # reaching 127.0.0.1 from the browser).
            return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

        def _send(self, code, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > MAX_BODY:
                return None
            return self.rfile.read(length)

        # ------------------------------------------------------------ GET
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "host"})
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path
            if path == "/":
                with open(PAGE, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/pairs":
                return self._send(200, {
                    "pairs": PAIRS,
                    "voices": {"target": voices.TARGET, "british": voices.BRITISH, "american_male": voices.AMERICAN_MALE},
                    "progress": ctx.store.get()["pairs"],
                })
            if path == "/api/audio":
                text = (query.get("word") or query.get("text") or "").strip()
                voice, speed = query.get("voice", ""), query.get("speed", "normal")
                is_word = "word" in query
                if voice not in pool or speed not in SPEEDS or not ctx.tts.valid(text) or (is_word and not WORD.fullmatch(text)):
                    return self._send(400, {"error": "bad request"})
                try:
                    wav = ctx.tts.get(text, voice, speed)
                except Exception as error:
                    return self._send(500, {"error": str(error)})
                with open(wav, "rb") as f:
                    return self._send(200, f.read(), "audio/wav")
            if path == "/api/clip":  # Jun's own sound of one word, cut from the recording
                attempt = ctx.attempts.get(query.get("attempt", ""))
                try:
                    row = attempt["rows"][int(query.get("i", "-1"))]
                except (TypeError, ValueError, IndexError, KeyError):
                    return self._send(404, {"error": "no such clip"})
                if row["start"] is None or row["end"] is None:
                    return self._send(404, {"error": "no sound for this word"})
                audio = attempt["audio"]
                a = max(0, int((row["start"] - 0.08) * RATE))
                b = min(len(audio), int((min(row["end"], row["start"] + 3) + 0.08) * RATE))
                return self._send(200, wav_bytes(audio[a:b]), "audio/wav")
            if path == "/api/materials":
                return self._send(200, ctx.materials.listing())
            if path == "/api/material":
                item = ctx.materials.get(query.get("id", ""))
                return self._send(200, item) if item else self._send(404, {"error": "not found"})
            if path == "/api/review":
                return self._send(200, ctx.review.listing())
            self._send(404, {"error": "not found"})

        # ------------------------------------------------------------ POST
        def do_POST(self):
            if not self._host_ok():
                return self._send(403, {"error": "host"})
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            kind = self.headers.get("Content-Type", "").split(";")[0]
            body = self._read()
            if body is None:
                return self._send(413, {"error": "too big"})
            if url.path == "/api/judge" and kind == "audio/wav":
                return self._judge(query.get("text", ""), body)
            if url.path == "/api/pdf" and kind == "application/pdf":
                try:
                    return self._send(200, {"text": clean_text(pdf_text(body))})
                except Exception:
                    return self._send(400, {"error": "pdf"})
            if kind != "application/json":
                return self._send(415, {"error": "wrong content type"})
            try:
                data = json.loads(body or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            path = url.path
            if path == "/api/answer":
                pair = BY_ID.get(data.get("pair"))
                played, chosen, voice = data.get("played"), data.get("chosen"), data.get("voice")
                if not pair or played not in pair["words"] or chosen not in pair["words"] or voice not in pool:
                    return self._send(400, {"error": "bad answer"})
                return self._send(200, ctx.store.record(pair["id"], played, chosen, voice))
            if path == "/api/materials":
                try:
                    return self._send(200, ctx.materials.create(data.get("title", ""), data.get("text", "")))
                except ValueError:
                    return self._send(400, {"error": "no sentences"})
            if path == "/api/material/delete":
                return self._send(200, {"deleted": ctx.materials.delete(data.get("id", ""))})
            if path == "/api/review/save":
                try:
                    return self._send(200, ctx.review.save_by_hand(data.get("kind", ""), str(data.get("text", ""))))
                except ValueError:
                    return self._send(400, {"error": "bad item"})
            if path == "/api/review/delete":
                return self._send(200, {"deleted": ctx.review.delete(str(data.get("id", "")))})
            self._send(404, {"error": "not found"})

        def _judge(self, text, data):
            text = " ".join(text.split())
            if not ctx.tts.valid(text):
                return self._send(400, {"error": "bad text"})
            try:
                audio = wav_to_16k(data)
            except (ValueError, wave.Error, EOFError):
                return self._send(400, {"error": "bad audio"})
            if audio.size < RATE * 0.4:
                return self._send(400, {"error": "too_short"})
            try:
                result = ctx.worker.run(lambda: ctx.judge.judge(audio, text))
            except Exception as error:
                return self._send(500, {"error": f"{type(error).__name__}: {error}"})
            attempt_id = uuid.uuid4().hex[:12]
            ctx.attempts[attempt_id] = {"audio": audio, "rows": result["rows"]}
            while len(ctx.attempts) > MAX_ATTEMPTS:
                ctx.attempts.popitem(last=False)
            # A reading that does not cover the sentence (stopped early, silence, a different sentence)
            # says nothing about pronunciation: it must not fill the review list.
            matched = sum(1 for r in result["rows"] if r["status"] in ("ok", "doubt"))
            incomplete = matched < max(1, -(-len(result["rows"]) // 2))  # fewer than half the words came out as written
            if not incomplete:
                ctx.review.update_from_attempt(text, result["rows"])
            rows = [dict(i=i, word=r["word"], status=r["status"], heard_as=r["heard_as"], prob=round(r["prob"], 2),
                         has_clip=r["start"] is not None and r["end"] is not None)
                    for i, r in enumerate(result["rows"])]
            self._send(200, {"attempt": attempt_id, "engine": result["engine"], "heard": result["heard"], "rows": rows,
                             "extra": result["extra"], "seconds": round(audio.size / RATE, 1), "incomplete": incomplete,
                             "quiet": float(np.abs(audio).max()) < 0.02})

    return Handler


def main():
    parser = argparse.ArgumentParser(description="yourAccent: pronunciation practice")
    parser.add_argument("--no-browser", action="store_true", help="do not open the page")
    args = parser.parse_args()

    refuse_if_secondchair_runs()
    lock = claim_single_instance()
    worker = Worker()
    ctx = SimpleNamespace(
        store=Store(os.path.join(HOME, "progress.json")),
        review=Review(os.path.join(HOME, "review.json")),
        materials=Materials(os.path.join(HOME, "materials")),
        worker=worker,
        tts=TTS(os.path.join(HOME, "cache", "voices"), worker),
        judge=WhisperJudge(JUDGE_MODEL),
        attempts=collections.OrderedDict(),
    )
    server = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(ctx))
    url = f"http://127.0.0.1:{PORT}/"
    print(f"yourAccent: {url}   (끝내려면 Ctrl+C)")
    # Make the first pair's words in the explaining voice ahead of time, so the first click is not slow.
    threading.Thread(target=lambda: [ctx.tts.get(w, voices.TARGET) for w in PAIRS[0]["words"]], daemon=True).start()
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        lock.close()


if __name__ == "__main__":
    main()
