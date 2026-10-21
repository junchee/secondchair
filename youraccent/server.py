"""yourAccent: a small local web app for English pronunciation practice.

A separate program from secondchair (own port, own data folder), meant to feel like its own app.
For now: listening training with minimal pairs (light / right ...), spoken by Kokoro voices.

Run:  python -m youraccent            (opens the page)
Data: ~/yourAccent  (override with YOURACCENT_HOME); port 8766 (override with YOURACCENT_PORT)
"""

import argparse
import fcntl
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from youraccent import voices
from youraccent.pairs import BY_ID, PAIRS, WORDS
from youraccent.store import Store
from youraccent.tts import SPEEDS, TTS

HOME = os.path.expanduser(os.environ.get("YOURACCENT_HOME", "~/yourAccent"))
PORT = int(os.environ.get("YOURACCENT_PORT", "8766"))
SECONDCHAIR_LOCK = "/tmp/secondchair.lock"
OWN_LOCK = "/tmp/youraccent.lock"
PAGE = os.path.join(os.path.dirname(__file__), "ui", "index.html")


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


def make_handler(store, tts):
    pool = set(voices.ALL)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _host_ok(self):
            # Only this Mac's own page may talk to the server (guards against other sites
            # reaching 127.0.0.1 from the browser).
            return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

        def _send(self, code, body, content_type="application/json; charset=utf-8", headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "host"})
            url = urlparse(self.path)
            if url.path == "/":
                with open(PAGE, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if url.path == "/api/pairs":
                return self._send(200, {
                    "pairs": PAIRS,
                    "voices": {"target": voices.TARGET, "british": voices.BRITISH, "american_male": voices.AMERICAN_MALE},
                    "progress": store.get()["pairs"],
                })
            if url.path == "/api/audio":
                query = parse_qs(url.query)
                word = (query.get("word") or [""])[0]
                voice = (query.get("voice") or [""])[0]
                speed = (query.get("speed") or ["normal"])[0]
                if word not in WORDS or voice not in pool or speed not in SPEEDS:
                    return self._send(400, {"error": "bad request"})
                try:
                    path = tts.get(word, voice, speed)
                except RuntimeError as error:
                    return self._send(500, {"error": str(error)})
                with open(path, "rb") as f:
                    return self._send(200, f.read(), "audio/wav")
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, {"error": "host"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._send(415, {"error": "json only"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            if urlparse(self.path).path == "/api/answer":
                pair = BY_ID.get(body.get("pair"))
                played, chosen, voice = body.get("played"), body.get("chosen"), body.get("voice")
                if not pair or played not in pair["words"] or chosen not in pair["words"] or voice not in pool:
                    return self._send(400, {"error": "bad answer"})
                return self._send(200, store.record(pair["id"], played, chosen, voice))
            self._send(404, {"error": "not found"})

    return Handler


def main():
    parser = argparse.ArgumentParser(description="yourAccent: pronunciation practice")
    parser.add_argument("--no-browser", action="store_true", help="do not open the page")
    args = parser.parse_args()

    refuse_if_secondchair_runs()
    lock = claim_single_instance()
    store = Store(os.path.join(HOME, "progress.json"))
    tts = TTS(os.path.join(HOME, "cache", "voices"))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(store, tts))
    url = f"http://127.0.0.1:{PORT}/"
    print(f"yourAccent: {url}   (끝내려면 Ctrl+C)")
    # Make the target voice's first words ahead of time, so the first click is not slow.
    threading.Thread(target=lambda: [tts.get(w, voices.TARGET) for w in PAIRS[0]["words"]], daemon=True).start()
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
