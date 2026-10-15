"""secondchair in the browser.

Run with the venv active:
    python app.py                 (whisper-small)
    python app.py --model turbo   (whisper-large-v3-turbo, slower, more accurate)

Opens http://127.0.0.1:8765 . The page shows the transcript and its translation side by side
and gets every event live (Server-Sent Events). The terminal shows the same events.
Only this Mac can reach the page: the server listens on 127.0.0.1.
Stop with the page's Stop button or Ctrl+C here; closing the page does not stop it.

The page also drives the voice output (voice_out.py): Jun's Korean, translated and confirmed,
spoken into the meeting through the virtual mic "BlackHole 16ch".
"""

import argparse
import json
import os
import queue
import signal
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import transcribe_stream
from events import Settings, fan_out, print_event
from record import Recorder
from summary import summarize

MODELS = {
    "small": "mlx-community/whisper-small-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "index.html")
KEEPALIVE_SECONDS = 15


class Hub:
    """Keeps every event of this session and passes new ones to each open page.

    A page that connects (or reloads) first gets the history, so nothing is lost.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.history = []
        self.clients = set()

    def emit(self, event):
        with self.lock:
            self.history.append(event)
            for client in self.clients:
                client.put(event)

    def subscribe(self):
        client = queue.Queue()
        with self.lock:
            for event in self.history:
                client.put(event)
            client.put({"type": "live"})  # end of the replay: events after this are new
            self.clients.add(client)
        return client

    def unsubscribe(self, client):
        with self.lock:
            self.clients.discard(client)


def make_handler(hub, settings, emit, controls):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # keep the terminal for transcript lines

        def do_GET(self):
            if self.path == "/":
                with open(PAGE, "rb") as page:
                    body = page.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/events":
                self.stream_events()
            else:
                self.send_error(404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                ok = self.handle_action(json.loads(self.rfile.read(length) or b"{}"))
            except (json.JSONDecodeError, ValueError, TypeError):
                ok = False
            self.send_response(204 if ok else 400)
            self.end_headers()

        def handle_action(self, body):
            voice = controls.get("voice")
            if self.path == "/settings":
                settings.update(body)
                emit(settings.as_event())
            elif self.path == "/voice" and voice:
                if body.get("mode") == "interpret" and not settings.translate:
                    settings.update({"translate": True})  # interpreting needs translation
                    emit(settings.as_event())
                if "mode" in body:
                    voice.set_mode(body["mode"])
                if "monitor" in body or "monitor_volume" in body:
                    voice.set_monitor(body.get("monitor"), body.get("monitor_volume"))
            elif self.path == "/speak" and voice:
                voice.speak(str(body.get("text", "")))
            elif self.path == "/discard" and voice:
                voice.discard()
            elif self.path == "/stop":
                # Same clean shutdown as Ctrl+C: the main thread turns SIGTERM into KeyboardInterrupt.
                os.kill(os.getpid(), signal.SIGTERM)
            else:
                return False
            return True

        def stream_events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            client = hub.subscribe()
            try:
                while True:
                    try:
                        event = client.get(timeout=KEEPALIVE_SECONDS)
                        chunk = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        chunk = ": keepalive\n\n"  # lets the page notice a dead server
                    self.wfile.write(chunk.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # page closed
            finally:
                hub.unsubscribe(client)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=MODELS, default="small")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not open the page")
    parser.add_argument("--no-switch", action="store_true", help="leave the output device alone")
    args = parser.parse_args()

    hub = Hub()
    recorder = Recorder()
    emit = fan_out(hub.emit, print_event, recorder)  # page, terminal, and the saved transcript
    settings = Settings(translate=True)  # on when the OpenRouter key is set; the page can turn it off
    controls = {}  # filled by transcribe_stream.run (the voice output)
    handler = make_handler(hub, settings, emit, controls)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f"http://127.0.0.1:{args.port}"
    print(f"secondchair: {url}")
    if not args.no_browser:
        webbrowser.open(url)

    transcribe_stream.run(
        MODELS[args.model],
        switch_output=not args.no_switch,
        settings=settings,
        emit=emit,
        voice=True,
        controls=controls,
    )
    summary = None
    conversation = recorder.plain_text()
    if conversation and settings.translate_available:
        emit({"type": "info", "text": "summarizing the meeting…"})
        try:
            summary = summarize(conversation)
            hub.emit({"type": "summary", "text": summary})
            print("\n" + summary + "\n")
        except Exception as error:  # the transcript is still saved without it
            emit({"type": "info", "text": f"summary failed: {error}"})
    saved = recorder.close(summary)
    if saved:
        print(f"Transcript saved: {saved}")
    hub.emit({"type": "stopped", "saved": saved})  # the page says so instead of reconnecting
    time.sleep(0.5)
    server.shutdown()


if __name__ == "__main__":
    main()
