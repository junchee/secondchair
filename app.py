"""secondchair in the browser.

Run with the venv active:
    python app.py                 (whisper-small)
    python app.py --model turbo   (whisper-large-v3-turbo, slower, more accurate)

Opens http://127.0.0.1:8765 . The page shows the transcript and its translation side by side
and gets every event live (Server-Sent Events). The terminal shows the same events.
Only this Mac can reach the page: the server listens on 127.0.0.1. Ctrl+C to stop.
"""

import argparse
import json
import os
import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import transcribe_stream
from events import Settings, fan_out, print_event

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


def make_handler(hub, settings, emit):
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
            if self.path != "/settings":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                change = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self.send_error(400)
                return
            if "translate" in change:
                settings.translate = bool(change["translate"]) and settings.translate_available
                emit(settings.as_event())
            self.send_response(204)
            self.end_headers()

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
    emit = fan_out(hub.emit, print_event)  # every event goes to the page and the terminal
    settings = Settings(translate=True)  # on when the OpenRouter key is set; the page can turn it off
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(hub, settings, emit))
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
    )
    server.shutdown()


if __name__ == "__main__":
    main()
