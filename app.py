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
import itertools
import json
import os
import queue
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import transcribe_stream
from events import Settings, fan_out, print_event
from transcribe_stream import Hooks
from record import Recorder
from summary import answer, summarize
from translate import Client, translate_typed

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

    def reset(self):
        """A new meeting starts: a page that connects from now on sees only this one."""
        with self.lock:
            self.history.clear()

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


class Summaries:
    """Summaries of the conversation so far: on request while the meeting goes on, and at the end."""

    def __init__(self, recorder, emit, available):
        self.recorder = recorder
        self.emit = emit
        self.available = available
        self.busy = threading.Lock()  # one summary at a time

    def make(self, final=False):
        """Summarize everything said so far, report it as a summary event, and return the text."""
        conversation = self.recorder.plain_text()
        if not conversation:
            self.emit({"type": "summary", "text": "", "final": final, "time": time.strftime("%H:%M")})
            return None
        self.emit({"type": "summarizing", "final": final})
        try:
            text = summarize(conversation)
        except Exception as error:  # the transcript is kept either way
            self.emit({"type": "info", "text": f"summary failed: {error}"})
            return None
        self.emit({"type": "summary", "text": text, "final": final, "time": time.strftime("%H:%M")})
        return text

    def request(self):
        """From the page's Summary button: summarize in the background, the meeting continues."""
        if not self.available:
            self.emit({"type": "info", "text": "summary needs OPENROUTER_API_KEY"})
        elif self.busy.acquire(blocking=False):

            def work():
                try:
                    self.make()
                finally:
                    self.busy.release()

            threading.Thread(target=work, daemon=True).start()


class Typing:
    """Text Jun types on the page, translated for him to say himself (or to send by voice).
    It is not part of the transcript: it was not said in the meeting."""

    CONTEXT_LINES = 8  # recent transcript lines sent along for names and references

    def __init__(self, recorder, emit, available):
        self.recorder = recorder
        self.emit = emit
        self.available = available
        self.ids = itertools.count(1)

    def request(self, text):
        text = text.strip()
        if not text:
            return
        if not self.available:
            self.emit({"type": "info", "text": "typed translation needs OPENROUTER_API_KEY"})
            return
        typed_id = next(self.ids)
        self.emit({"type": "typing", "id": typed_id, "source": text})

        def work():
            event = {"type": "typed", "id": typed_id, "source": text}
            try:
                event["target"], event["text"] = translate_typed(text, self.recorder.plain_text(last=self.CONTEXT_LINES))
            except Exception as error:
                event["target"], event["text"] = None, f"(translation failed: {error})"
            self.emit(event)

        threading.Thread(target=work, daemon=True).start()


class Asking:
    """Jun's questions about the meeting, answered from the whole conversation so far.
    Questions and answers are not recorded: they were not said in the meeting."""

    def __init__(self, recorder, emit, available):
        self.recorder = recorder
        self.emit = emit
        self.available = available
        self.ids = itertools.count(1)
        self.earlier = []  # last few (question, answer) pairs, for follow-ups
        self.client = Client(timeout=60)
        self.lock = threading.Lock()  # one connection: answers are made one at a time, in order

    def request(self, question):
        question = question.strip()
        if not question:
            return
        if not self.available:
            self.emit({"type": "info", "text": "asking needs OPENROUTER_API_KEY"})
            return
        ask_id = next(self.ids)
        self.emit({"type": "asking", "id": ask_id, "question": question})

        def work():
            event = {"type": "answer", "id": ask_id, "question": question}
            with self.lock:
                try:
                    event["text"] = answer(
                        question, self.recorder.plain_text(), self.earlier[-3:], self.client
                    )
                    self.earlier.append((question, event["text"]))
                except Exception as error:
                    event["text"] = f"(answer failed: {error})"
            self.emit(event)

        threading.Thread(target=work, daemon=True).start()


class Meeting(Hooks):
    """Joins the engine to the recorder, the page and the summary for each meeting."""

    def __init__(self, hub, recorder, summaries, asking, settings):
        self.hub = hub
        self.recorder = recorder
        self.summaries = summaries
        self.asking = asking
        self.settings = settings

    def begin(self):
        self.recorder.begin()  # new files for this meeting
        self.hub.reset()  # the page shows only this meeting
        self.asking.earlier.clear()  # follow-up questions do not reach back to the last meeting

    def finish(self):
        summary = None
        if self.settings.translate_available:
            with self.summaries.busy:  # wait for a summary the page asked for just before End
                summary = self.summaries.make(final=True)
        saved = self.recorder.close(summary)
        if saved:
            print(f"Transcript saved: {saved}")
        return saved


def make_handler(hub, settings, emit, controls, summaries, typing, asking):
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
                settings.update(body)  # translate, line lengths, mic_filter
                emit(settings.as_event())
            elif self.path == "/voice" and voice:
                if body.get("mode") == "interpret" and not settings.translate:
                    settings.update({"translate": True})  # interpreting needs translation
                    emit(settings.as_event())
                if "mode" in body:
                    voice.set_mode(body["mode"])
                if "monitor" in body or "monitor_volume" in body:
                    voice.set_monitor(body.get("monitor"), body.get("monitor_volume"))
                if "voice" in body:
                    voice.set_voice(str(body["voice"]))
                if body.get("preview"):
                    voice.preview(body.get("voice"))
            elif self.path == "/speak" and voice:
                voice.speak(str(body.get("text", "")))
            elif self.path == "/discard" and voice:
                voice.discard()
            elif self.path == "/summarize":
                summaries.request()
            elif self.path == "/type":
                typing.request(str(body.get("text", "")))
            elif self.path == "/ask":
                asking.request(str(body.get("question", "")))
            elif self.path == "/session" and controls.get("engine"):
                controls["engine"].command(str(body.get("action", "")))  # start, pause, resume, end
            elif self.path in ("/quit", "/stop") and controls.get("engine"):
                controls["engine"].request_quit()  # ends a running meeting properly, then exits
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
    summaries = Summaries(recorder, emit, settings.translate_available)
    typing = Typing(recorder, emit, settings.translate_available)
    asking = Asking(recorder, emit, settings.translate_available)
    handler = make_handler(hub, settings, emit, controls, summaries, typing, asking)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f"http://127.0.0.1:{args.port}"
    print(f"secondchair (hajung beta): {url}")
    if not args.no_browser:
        webbrowser.open(url)

    meeting = Meeting(hub, recorder, summaries, asking, settings)
    saved = transcribe_stream.run(
        MODELS[args.model],
        switch_output=not args.no_switch,
        settings=settings,
        emit=emit,
        voice=True,
        controls=controls,
        hooks=meeting,
    )
    hub.emit({"type": "stopped", "saved": saved})  # the page says so instead of reconnecting
    time.sleep(0.5)
    server.shutdown()


if __name__ == "__main__":
    main()
