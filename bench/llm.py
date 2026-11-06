"""Small helpers for paid model calls in the bench (stage D): prices, cache, budget, clients.

Nothing here knows about translation. `translate_eval.py` builds request bodies (OpenRouter chat format) and
asks a `Runner`, which:
  - looks the request up in the cache first (one JSON file per call, keyed by a hash of the whole body:
    model, prompt text and input), so a finished call is never repeated and an interrupted run resumes;
  - in dry mode only counts and estimates what would be called;
  - otherwise checks the budget, calls the client, stores the reply with its cost and time.

Clients: `RealClient` (OpenRouter, key from the environment variable OPENROUTER_API_KEY, never printed or
stored) and `FakeClient` (no network; used by tests, `--fake` and the dry run).
"""

import hashlib
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PRICES_FILE = os.path.join(HERE, "model_prices.json")
PRICES_URL = "https://openrouter.ai/api/v1/models"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
ASSUMED_PRICE = (1e-6, 2e-6)       # dollars per token (input, output) for a model nobody listed

try:
    import certifi
    _TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _TLS = ssl.create_default_context()


# ---------------------------------------------------------------- prices

class Prices:
    """Dollars per token for each model id, and where the numbers came from (`source`)."""

    def __init__(self, table, source):
        self.table, self.source = table, source
        self.unknown = set()

    def get(self, model):
        if model in self.table:
            return tuple(self.table[model])
        self.unknown.add(model)
        return ASSUMED_PRICE

    def cost(self, model, tokens_in, tokens_out):
        pin, pout = self.get(model)
        return tokens_in * pin + tokens_out * pout


def load_prices(offline=False, path=PRICES_FILE, timeout=8):
    """OpenRouter's public model list (no key needed), else the small table in model_prices.json."""
    table, source = {}, ""
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        table = {k: tuple(v) for k, v in saved.get("per_token", {}).items()}
        source = f"{os.path.basename(path)} (saved {saved.get('fetched', '?')})"
    except (OSError, ValueError):
        pass
    if not offline:
        try:
            request = urllib.request.Request(PRICES_URL, headers={"User-Agent": "anne-bench"})
            with urllib.request.urlopen(request, timeout=timeout, context=_TLS) as response:
                data = json.loads(response.read()).get("data", [])
            live = {}
            for m in data:
                p = m.get("pricing") or {}
                try:
                    live[m["id"]] = (float(p["prompt"]), float(p["completion"]))
                except (KeyError, TypeError, ValueError):
                    continue
            if live:
                table.update(live)
                source = f"OpenRouter public model list ({PRICES_URL}, fetched {time.strftime('%Y-%m-%d')})"
        except Exception:
            source += " [OpenRouter list not reachable]"
    return Prices(table, source or "no price table found: assumed prices")


def estimate_tokens(text):
    """Rough token count: ASCII at 4 characters a token, other characters (Korean) at one each."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return int(ascii_chars / 4 + (len(text) - ascii_chars)) + 1


def body_text(body):
    return "".join(m.get("content", "") for m in body.get("messages", []))


# ---------------------------------------------------------------- cache

def request_key(body):
    """Hash of the whole request body (model, prompt text, input, settings)."""
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class Cache:
    """One JSON file per call under `root/ab/abcdef....json`; written by rename, so never half-written."""

    def __init__(self, root):
        self.root = root

    def _path(self, key):
        return os.path.join(self.root, key[:2], key + ".json")

    def get(self, key):
        try:
            with open(self._path(key), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def put(self, key, record):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        os.replace(temporary, path)


# ---------------------------------------------------------------- budget

class BudgetStop(Exception):
    """The next call would take the run over its dollar limit."""


class Budget:
    def __init__(self, limit_usd):
        self.limit, self.spent, self.reserved = float(limit_usd), 0.0, 0.0
        self.lock = threading.Lock()

    def reserve(self, estimate):
        with self.lock:
            if self.spent + self.reserved + estimate > self.limit:
                raise BudgetStop(f"budget ${self.limit:.2f} reached (spent ${self.spent:.4f})")
            self.reserved += estimate

    def settle(self, estimate, actual):
        with self.lock:
            self.reserved = max(0.0, self.reserved - estimate)
            self.spent += actual


# ---------------------------------------------------------------- clients

class CallError(Exception):
    """A call failed (network, HTTP error, empty reply). Nothing is cached for it."""


class RealClient:
    """OpenRouter chat completions. The key is read from OPENROUTER_API_KEY when the first call is made."""

    def __init__(self, timeout=90, attempts=3):
        self.timeout, self.attempts = timeout, attempts

    def chat(self, body):
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise CallError("OPENROUTER_API_KEY is not set in the environment")
        payload = json.dumps(body).encode("utf-8")
        last = None
        for attempt in range(self.attempts):
            started = time.time()
            request = urllib.request.Request(CHAT_URL, data=payload, method="POST", headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "anne-bench"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=_TLS) as response:
                    data = json.loads(response.read())
                seconds = time.time() - started
                text = (data["choices"][0]["message"].get("content") or "").strip()
                usage = data.get("usage") or {}
                return {"text": text, "usage": usage, "seconds": seconds}
            except urllib.error.HTTPError as error:
                detail = error.read()[:200].decode("utf-8", "replace")
                last = f"HTTP {error.code}: {detail}"
                if error.code not in (408, 429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as error:
                last = f"{type(error).__name__}: {error}"
            time.sleep(2 * (attempt + 1))
        raise CallError(last or "call failed")


class FakeClient:
    """No network. Answers like the prompts ask, deterministically, so that the whole pipeline can run.

    `responder(body)` may replace the default answers; it returns the reply text. `calls` counts requests."""

    def __init__(self, prices=None, responder=None, fail_after=None):
        self.prices = prices
        self.responder = responder
        self.fail_after = fail_after      # raise KeyboardInterrupt after this many calls (tests)
        self.calls = 0
        self.lock = threading.Lock()

    def chat(self, body):
        with self.lock:
            if self.fail_after is not None and self.calls >= self.fail_after:
                raise KeyboardInterrupt("fake interruption")
            self.calls += 1
        text = self.responder(body) if self.responder else fake_reply(body)
        tin = estimate_tokens(body_text(body))
        tout = estimate_tokens(text)
        cost = self.prices.cost(body.get("model", ""), tin, tout) if self.prices else 0.0
        return {"text": text, "usage": {"prompt_tokens": tin, "completion_tokens": tout, "cost": cost}, "seconds": 0.01}


def _section(text, start_marker, end_marker):
    a = text.find(start_marker)
    if a < 0:
        return ""
    a += len(start_marker)
    b = text.find(end_marker, a)
    return text[a:b if b >= 0 else None].strip()


def fake_reply(body):
    """Default fake answers. Reference prompt: Korean = 'KO[' + English + ']'. Translator: the same, but a model
    whose id ends in 'b' drops the last word of long sentences. Judge: compares the English words inside the
    candidate with the English sentence (right >= 90%, partly >= 60%, else wrong)."""
    text = body_text(body)
    if "reference Korean translation" in text and "Sentence to translate (speaker" in text:
        sentence = text[text.index("Sentence to translate (speaker "):].split("):\n", 1)[1].split("\n\nAbout the text", 1)[0].strip()
        kind = "backchannel" if len(sentence.split()) <= 2 else "content"
        return json.dumps({"ko": f"KO[{sentence}]", "kind": kind}, ensure_ascii=False)
    if "You check the Korean translation" in text:
        english = _section(text, "(what the speaker really said):\n", "\n\nReference Korean")
        reference = _section(text, "(a correct translation, one of many possible):\n", "\n\nCandidate Korean")
        candidate = _section(text, "Candidate Korean (to judge):\n", "\n\nKey items")
        if not candidate:
            return json.dumps({"meaning": "wrong", "critical": ["empty candidate"], "errors": [
                {"type": "omission", "severity": "critical", "span": english[:30], "note": "empty"}], "comment": "empty"})
        if candidate == reference:
            return json.dumps({"meaning": "right", "critical": [], "errors": [], "comment": "same"})
        inner = candidate[3:-1] if candidate.startswith("KO[") and candidate.endswith("]") else candidate
        want, got = english.lower().split(), inner.lower().split()
        share = sum(1 for w in want if w in got) / max(1, len(want))
        if share >= 0.9:
            return json.dumps({"meaning": "right", "critical": [], "errors": [
                {"type": "omission", "severity": "minor", "span": "", "note": "small"}] if share < 1 else [], "comment": "close"})
        if share >= 0.6:
            return json.dumps({"meaning": "partly", "critical": [], "errors": [
                {"type": "omission", "severity": "major", "span": "", "note": "part missing"}], "comment": "part missing"})
        return json.dumps({"meaning": "wrong", "critical": ["meaning lost"], "errors": [
            {"type": "wrong_meaning", "severity": "critical", "span": "", "note": "lost"},
            {"type": "wrong_name_or_number", "severity": "major", "span": "", "note": "x"}], "comment": "lost"})
    # a translator
    line = _section(body["messages"][-1]["content"], "Line to translate:\n", "\n\n")
    words = line.split()
    if body.get("model", "").endswith("b") and len(words) >= 8:
        words = words[:-1]
    return f"KO[{' '.join(words)}]"


# ---------------------------------------------------------------- runner

class Runner:
    """Cache, budget and client together. `ask(step, body, tokens_out)` returns the stored record
    {"text", "usage", "cost", "seconds", "model"} or, in dry mode for a call not yet in the cache, None."""

    def __init__(self, client, cache, budget, prices, dry=False):
        self.client, self.cache, self.budget, self.prices, self.dry = client, cache, budget, prices, dry
        self.stats = {}
        self.lock = threading.Lock()
        self.seen = set()          # dry mode: exact requests already planned (a repeat is one call, not two)

    def _stat(self, step):
        return self.stats.setdefault(step, {"cached": 0, "new": 0, "planned": 0, "failed": 0, "repeat": 0,
                                            "tokens_in": 0, "tokens_out": 0, "usd": 0.0})

    def ask(self, step, body, tokens_out):
        key = request_key(body)
        record = self.cache.get(key)
        with self.lock:
            stat = self._stat(step)
            if record:
                stat["cached"] += 1
                return record
        tin = estimate_tokens(body_text(body))
        estimate = self.prices.cost(body["model"], tin, tokens_out)
        if self.dry:
            with self.lock:
                if step != "judge":        # a judge request is only a guess before its candidate exists
                    if key in self.seen:
                        stat["repeat"] += 1
                        return None
                    self.seen.add(key)
                stat["planned"] += 1
                stat["tokens_in"] += tin
                stat["tokens_out"] += tokens_out
                stat["usd"] += estimate
            return None
        self.budget.reserve(estimate)      # raises BudgetStop
        try:
            reply = self.client.chat(body)
        except CallError:
            self.budget.settle(estimate, 0.0)
            with self.lock:
                stat["failed"] += 1
            raise
        except BaseException:
            self.budget.settle(estimate, 0.0)
            raise
        usage = reply.get("usage") or {}
        tokens_in = usage.get("prompt_tokens", tin)
        tokens_made = usage.get("completion_tokens", tokens_out)
        cost = usage.get("cost")
        if cost is None:
            cost = self.prices.cost(body["model"], tokens_in, tokens_made)
        record = {"model": body["model"], "text": reply["text"], "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_made},
                  "cost": float(cost), "seconds": float(reply["seconds"]), "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.cache.put(key, record)
        self.budget.settle(estimate, float(cost))
        with self.lock:
            stat["new"] += 1
            stat["tokens_in"] += tokens_in
            stat["tokens_out"] += tokens_made
            stat["usd"] += float(cost)
        return record

    def new_calls(self):
        return sum(s["new"] for s in self.stats.values())

    def planned_calls(self):
        return sum(s["planned"] for s in self.stats.values())
