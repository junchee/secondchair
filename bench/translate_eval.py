"""Translation test, stage D of notes/bench_runbook_2026-11-05.md.

Measures how much of an English meeting survives as Korean, with the app's own translator:
  T0 = the reference English sentences in, T1 = the speech recogniser's text for the same sentences in.
Each Korean candidate is judged by a model against the reference English and a reference Korean.

Steps (every model call is cached under bench/results/cache/, keyed by a hash of the whole request, so a
finished call is never repeated and an interrupted run resumes by running the same command again):
  a. reference Korean   Opus,   bench/prompts/reference_translation.md   (once per sentence)
  b. candidate Korean   each --translator x --prompt-variant x condition (the app's own prompt, translate.py)
  c. judge              Sonnet, bench/prompts/translation_judge.md (v2), temperature 0, one call per candidate

Defaults (see --help): reference model anthropic/claude-opus-5.5, judge model anthropic/claude-sonnet-5.5
(both ids exist in OpenRouter's public list, 2026-11-06; haiku-5.5 in config/models.json shows the naming),
translator = first id of roles.translate in config/models.json (deepseek/deepseek-v4.1-flash-1017),
prompt variant `app` (translate.build_request from translate.py, imported unchanged).
Prompt variants (add one in VARIANTS): app, speech (+ "text is from speech, may contain errors"), context4.

Usage (run from the repo root; nothing paid happens with --fake or --dry-run):

  # what would one real run cost? (needs no key; reads OpenRouter's public price list)
  python3 bench/translate_eval.py --run-name D1 --dry-run
  # the same with fake models, then the real thing (needs OPENROUTER_API_KEY in the environment)
  python3 bench/translate_eval.py --run-name D1 --fake --max-seconds 60 --piece ES2004a.cut01
  python3 bench/translate_eval.py --run-name D1 --asr-model turbo --conditions T0,T1 --budget-usd 5
  # two translators, two prompt variants
  python3 bench/translate_eval.py --run-name D2 --translator deepseek/deepseek-v4.1-flash-1017 \\
      --translator qwen/qwen3.5-9b --prompt-variant app --prompt-variant speech
  # does the judge agree with Jun's samples?
  python3 bench/translate_eval.py --judge-check [--fake]
  # make a stub recogniser text (some words dropped, one changed, one inserted) for a dry run
  python3 bench/translate_eval.py --make-stub-asr --piece ES2004a.cut01

Inputs: bench/audio/ami/prepared/ (manifest.json, *.cutNN.json from prepare_ami.py); recogniser text for T1 in
bench/results/asr/<asr-model>/<piece>.txt (plain text) or .json (words, "words", "text" or "segments").
Output: bench/results/<run-name>/rows.jsonl, summary.txt, summary.json (and judge_check.json).
With --fake the cache is bench/results/cache_fake, never the real one.
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import llm                                   # noqa: E402
from score_text import align, tokens         # noqa: E402

PREPARED = os.path.join(HERE, "audio", "ami", "prepared")
RESULTS = os.path.join(HERE, "results")
PROMPTS = os.path.join(HERE, "prompts")
REFERENCE_PROMPT = os.path.join(PROMPTS, "reference_translation.md")
JUDGE_PROMPT = os.path.join(PROMPTS, "translation_judge.md")
REGRESSION = os.path.join(PROMPTS, "judge_regression_cases.json")
REGRESSION_AMI = os.path.join(RESULTS, "C", "judge_regression_ami.json")
CONTROL_FILE = os.path.join(ROOT, "notes", "bench_control.md")

DEFAULT_REFERENCE_MODEL = "anthropic/claude-opus-5.5"
DEFAULT_JUDGE_MODEL = "anthropic/claude-sonnet-5.5"
FALLBACK_TRANSLATOR = "deepseek/deepseek-v4.1-flash-1017"   # only if config/models.json cannot be read
GAP_SECONDS = 5.0
JUDGE_CONTEXT = 2
MEETING = ("A design-team meeting from the AMI corpus: a small project team (project manager, industrial designer, "
           "user interface designer, marketing expert) designs a new TV remote control. Spontaneous speech with many "
           "short replies.")

# ------------------------------------------------------------------ prompt variants (easy to extend)
# context: how many earlier sentences go with the line; extra_system: text added to the app's system prompt.
VARIANTS = {
    "app": {"context": 2, "extra_system": ""},
    "speech": {"context": 2, "extra_system": (
        " The text was written by a speech recogniser from spoken words, so it may contain recognition errors "
        "(wrong, missing or extra words). Use the context to read a wrong word as the word the speaker most likely said.")},
    "context4": {"context": 4, "extra_system": ""},
}
SYSTEM_MARK = " Reply with the translation only."

# ------------------------------------------------------------------ data: sentences

SPOKEN_LETTERS = re.compile(r"^(?:[A-Za-z]_)+[A-Za-z]?$")      # T_V_  L_C_D_  D_V_D_  I_D_
SINGLE_LETTER = re.compile(r"^[A-Za-z]_$")                      # T_ (Rex)
BACKCHANNEL_WORDS = {"yeah", "yep", "yup", "yes", "no", "okay", "ok", "right", "mm", "mmhmm", "hmm", "uhhuh", "sure",
                     "alright", "cool", "aha", "oh", "great", "fine", "thanks", "kay"}
# capitalised words that mark a restart, not a name: dropped from the key-item list only
RESTART_WORDS = {"yeah", "yes", "okay", "ok", "right", "well", "so", "and", "but", "oh", "gonna", "mm-hmm", "cool", "sure",
                 "alright", "no", "now", "then", "just", "good", "fine", "great", "hello", "hi", "sorry", "thanks", "please",
                 "anyway", "because", "cos", "er", "wow", "hey", "'kay", "shock", "let's", "they've", "what", "i", "is"}


def normalise_words(words, flags=None):
    """Spoken letters to the usual written form: T_V_ -> TV, L_C_D_ -> LCD, D_V_D_ -> DVD, I_D_ -> ID,
    'T_ Rex' -> T-Rex. Returns (new words, new key flags); a merged word is a key item if any part was."""
    flags = list(flags) if flags is not None else [False] * len(words)
    out, out_flags, i = [], [], 0
    while i < len(words):
        w = words[i]
        if SPOKEN_LETTERS.match(w) and w.count("_") + (0 if w.endswith("_") else 1) >= 2:
            out.append("".join(c for c in w if c != "_").upper())
            out_flags.append(flags[i])
        elif SINGLE_LETTER.match(w):
            letter = w[0].upper()
            if i + 1 < len(words):
                out.append(f"{letter}-{words[i + 1]}")
                out_flags.append(flags[i] or flags[i + 1])
                i += 1
            else:
                out.append(letter)
                out_flags.append(flags[i])
        else:
            out.append(w)
            out_flags.append(flags[i])
        i += 1
    return out, out_flags


def split_at_gaps(times, indexes, gap=GAP_SECONDS):
    """Split a run of word indexes where the next word starts `gap` seconds or more after the previous one
    ended. `times[i]` = (start, end). Returns a list of index lists."""
    parts, cur = [], []
    for i in indexes:
        if cur and times[i][0] - times[cur[-1]][1] >= gap:
            parts.append(cur)
            cur = []
        cur.append(i)
    if cur:
        parts.append(cur)
    return parts


def build_sentences(piece_id, piece, gap=GAP_SECONDS):
    """The reference sentences of one prepared piece: split at gaps, spoken letters written out, key items
    cleaned. Each: {id, piece, n, spk, words, text, start, end, key}."""
    ws, keys = piece["words"], set(piece.get("key", []))
    times = [(w["start"], w["end"]) for w in ws]
    ends = list(piece["ends"])
    if not ends or ends[-1] != len(ws) - 1:
        ends.append(len(ws) - 1)
    out, start = [], 0
    for e in ends:
        run = list(range(start, e + 1))
        start = e + 1
        for part in split_at_gaps(times, run, gap):
            words, flags = normalise_words([ws[i]["w"] for i in part], [i in keys for i in part])
            key = [w for w, f in zip(words, flags) if f and not (w[:1].isupper() and w.lower() in RESTART_WORDS)]
            n = len(out) + 1
            out.append({"id": f"{piece_id}.S{n:03d}", "piece": piece_id, "n": n, "spk": ws[part[0]]["spk"],
                        "words": words, "text": " ".join(words), "start": ws[part[0]]["start"],
                        "end": ws[part[-1]]["end"], "key": key})
    return out


def is_bare_backchannel(text):
    toks = tokens(text)
    return 0 < len(toks) <= 3 and all(t in BACKCHANNEL_WORDS for t in toks)


def labelled(sent, text):
    return f"{sent['spk']}: {text}"


# ------------------------------------------------------------------ data: recogniser text (T1)

def load_asr_words(asr_dir, asr_model, piece_id):
    """The recogniser's words for a piece as a list of strings, or None if there is no file."""
    base = os.path.join(asr_dir, asr_model, piece_id)
    if os.path.exists(base + ".txt"):
        with open(base + ".txt", encoding="utf-8") as f:
            return f.read().split()
    if os.path.exists(base + ".json"):
        with open(base + ".json", encoding="utf-8") as f:
            data = json.load(f)
        return _words_from_json(data)
    return None


def _words_from_json(data):
    if isinstance(data, dict):
        if "words" in data:
            return _words_from_json(data["words"])
        if "segments" in data:
            return " ".join(str(s.get("text", "")) for s in data["segments"]).split()
        return str(data.get("text", "")).split()
    out = []
    for item in data:
        if isinstance(item, dict):
            item = item.get("word") or item.get("w") or item.get("text") or ""
        out.extend(str(item).split())
    return out


def assign_asr(sentence_words, asr_words):
    """Give every reference sentence the recogniser words aligned to its span.

    sentence_words: list (per sentence) of word lists. asr_words: list of strings. Both are cut into the tokens
    of score_text, aligned with `align`; a recogniser word goes to the sentence of the reference word it matched
    or replaced. An inserted word goes to the sentence of the reference word just before it (the first sentence
    at the start). Returns a list of texts, one per sentence ('' if nothing was heard)."""
    ref_tok, ref_owner = [], []
    for si, words in enumerate(sentence_words):
        for w in words:
            for t in tokens(w):
                ref_tok.append(t)
                ref_owner.append(si)
    hyp_tok, hyp_raw = [], []
    for ri, raw in enumerate(asr_words):
        for t in tokens(raw):
            hyp_tok.append(t)
            hyp_raw.append(ri)
    owner_of_raw, last = {}, 0
    for op, i, j in align(ref_tok, hyp_tok):
        if i is not None:
            last = ref_owner[i]
        if j is not None:
            owner_of_raw.setdefault(hyp_raw[j], ref_owner[i] if i is not None else last)
    texts = [[] for _ in sentence_words]
    prev = 0
    for ri, raw in enumerate(asr_words):
        owner = owner_of_raw.get(ri, prev)       # a word with no letters (punctuation) stays with the word before
        prev = owner
        if texts:
            texts[owner].append(raw)
    return [" ".join(t) for t in texts]


def make_stub_text(words):
    """Test recogniser text: every 17th word dropped, every 41st changed, one word inserted after every 53rd."""
    out = []
    for i, w in enumerate(words, 1):
        if i % 17 == 0:
            continue
        out.append("banana" if i % 41 == 0 else w)
        if i % 53 == 0:
            out.append("um-actually")
    return " ".join(out)


# ------------------------------------------------------------------ prompts and request bodies

def load_prompt(path):
    """The prompt: everything below the first line that is only '---'."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^---[ \t]*$", text, re.M)
    if not m:
        raise SystemExit(f"{path}: no '---' line")
    return text[m.end():].strip("\n") + "\n"


def fill(template, **values):
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{(\w+)\}\}", out)
    if left:
        raise ValueError(f"unfilled placeholders: {left}")
    return out


def provider(zdr=True):
    return {"zdr": True, "data_collection": "deny"} if zdr else {"data_collection": "deny"}


def claude_body(model, prompt, max_tokens, zdr=True):
    return {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0,
            "max_tokens": max_tokens, "usage": {"include": True}, "provider": provider(zdr)}


def _import_app_translate():
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import translate      # the app's own module: importing it starts nothing and reads no settings
        return translate
    except Exception:
        return None


def _copied_build_request(text, target, context, model):
    """Copy of translate.build_request (2026-11-06), used only if translate.py cannot be imported.
    A test compares it with the real one whenever the import works."""
    parts = []
    if context:
        parts.append("Earlier lines (context only, do not translate):\n" + "\n".join(context))
    parts.append("Line to translate:\n" + text)
    script = " Write Korean in Hangul only; never use Chinese, Japanese or Cyrillic characters." if target == "Korean" else ""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": f"You translate one line of a live meeting transcript into natural {target}. "
             "Lines are cut at pauses, so a line may start or end mid-sentence: use the context "
             "lines only to understand it, and translate the line as a fragment if it is one. "
             "If the line stops mid-sentence, stop your translation at the same point and end it "
             "with '…'. Never add anything that is said only in a context line, even to finish "
             "a sentence: those words get their own translation. "
             "Translate every word of the line, including any words in other languages; keep "
             "names of people and places." + script + " Reply with the translation only."},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        "temperature": 0, "max_tokens": 300, "reasoning": {"enabled": False},
        "provider": {"zdr": True, "data_collection": "deny", "sort": "latency"},
    }


def app_request(text, context, model, module=None):
    module = module if module is not None else _import_app_translate()
    if module is not None:
        return module.build_request(text, "Korean", tuple(context), None, model, None)
    return _copied_build_request(text, "Korean", context, model)


def translate_body(model, variant, text, prev_lines):
    """The request for one candidate: the app's request with the variant's context length and added sentence."""
    v = VARIANTS[variant]
    context = prev_lines[-v["context"]:] if v["context"] else []
    body = app_request(text, context, model)
    if v["extra_system"]:
        system = body["messages"][0]["content"]
        assert SYSTEM_MARK in system
        body["messages"][0]["content"] = system.replace(SYSTEM_MARK, v["extra_system"] + SYSTEM_MARK)
    body["usage"] = {"include": True}
    return body


def default_translator():
    try:
        with open(os.path.join(ROOT, "config", "models.json"), encoding="utf-8") as f:
            return json.load(f)["roles"]["translate"][0]
    except (OSError, ValueError, KeyError, IndexError):
        return FALLBACK_TRANSLATOR


def read_budget_default(path=CONTROL_FILE, fallback=5.0):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*budget_usd_per_batch\s*:\s*([0-9.]+)\s*$", line)
                if m:
                    return float(m.group(1))
    except OSError:
        pass
    return fallback


# ------------------------------------------------------------------ parsing replies

def parse_json_reply(text):
    """json.loads of the stripped reply; else from the first { to the last }; else None."""
    text = (text or "").strip()
    for candidate in (text, text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def valid_judge(d):
    if not isinstance(d, dict) or d.get("meaning") not in ("right", "partly", "wrong"):
        return None
    errors = d.get("errors") if isinstance(d.get("errors"), list) else []
    d["errors"] = [e for e in errors if isinstance(e, dict)]
    d["critical"] = d.get("critical") if isinstance(d.get("critical"), list) else []
    return d


def valid_reference(d):
    if not isinstance(d, dict) or not isinstance(d.get("ko"), str) or not d["ko"].strip():
        return None
    kind = d.get("kind") if d.get("kind") in ("content", "fragment", "backchannel") else "content"
    return {"ko": d["ko"].strip(), "kind": kind}


RETRY_NOTE = "\n\nReturn only the JSON object on one line, nothing else."


def ask_json(runner, step, body, tokens_out, validator):
    """Ask, parse; on a parse failure ask once more (the retry is a different request, so it is cached too).
    Returns (parsed or None, parse_failed, [records])."""
    records = []
    rec = runner.ask(step, body, tokens_out)
    if rec is None:
        return None, False, records
    records.append(rec)
    parsed = validator(parse_json_reply(rec["text"]))
    if parsed:
        return parsed, False, records
    retry = json.loads(json.dumps(body))
    retry["messages"][-1]["content"] += RETRY_NOTE
    rec = runner.ask(step, retry, tokens_out)
    if rec is None:
        return None, False, records
    records.append(rec)
    parsed = validator(parse_json_reply(rec["text"]))
    return parsed, parsed is None, records


# ------------------------------------------------------------------ the pipeline

class Evaluation:
    def __init__(self, runner, reference_model, judge_model, zdr=True, workers=4):
        self.runner, self.reference_model, self.judge_model = runner, reference_model, judge_model
        self.zdr, self.workers = zdr, workers
        self.reference_template = load_prompt(REFERENCE_PROMPT)
        self.judge_template = load_prompt(JUDGE_PROMPT)
        self.refs, self.cands, self.judges = {}, {}, {}
        self.stop = None

    # --- step a
    def do_reference(self, sent, previous):
        if self.stop:
            return
        prompt = fill(self.reference_template, meeting=MEETING, terms="(none)", previous="\n".join(previous) or "(none)",
                      speaker=sent["spk"], sentence=sent["text"])
        body = claude_body(self.reference_model, prompt, 400, self.zdr)
        out = {"ko": None, "kind": None, "cost": 0.0, "seconds": 0.0, "error": None}
        try:
            parsed, failed, records = ask_json(self.runner, "reference", body, int(len(sent["text"]) * 0.9) + 30, valid_reference)
            out["cost"] = sum(r["cost"] for r in records)
            out["seconds"] = sum(r["seconds"] for r in records)
            if parsed:
                out["ko"], out["kind"] = parsed["ko"], parsed["kind"]
            elif failed:
                out["error"] = "parse_error"
        except llm.CallError as error:
            out["error"] = f"call failed: {error}"
        except llm.BudgetStop as stop:
            self.stop = stop
        self.refs[sent["id"]] = out

    # --- step b
    def do_candidate(self, sent, cond, model, variant, prev_lines, text):
        if self.stop:
            return
        key = (sent["id"], cond, model, variant)
        out = {"ko": None, "cost": 0.0, "seconds": None, "error": None, "asr_empty": False, "english_used": text}
        if cond == "T1" and not text.strip():
            out.update(ko="", asr_empty=True)
            self.cands[key] = out
            return
        body = translate_body(model, variant, text, prev_lines)
        try:
            rec = self.runner.ask("translate", body, int(len(text) * 0.9) + 20)
            if rec is not None:
                out.update(ko=rec["text"].strip(), cost=rec["cost"], seconds=rec["seconds"])
        except llm.CallError as error:
            out["error"] = f"call failed: {error}"
        except llm.BudgetStop as stop:
            self.stop = stop
        self.cands[key] = out

    # --- step c
    def judge_body(self, previous, source_en, reference_ko, candidate_ko, key_items):
        prompt = fill(self.judge_template, previous="\n".join(previous) or "(none)", source_en=source_en,
                      reference_ko=reference_ko, candidate_ko=candidate_ko, key_items=key_items)
        return claude_body(self.judge_model, prompt, 500, self.zdr)

    def do_judge(self, sent, cond, model, variant, previous):
        if self.stop:
            return
        key = (sent["id"], cond, model, variant)
        ref, cand = self.refs.get(sent["id"]), self.cands.get(key)
        out = {"judge": None, "cost": 0.0, "seconds": 0.0, "error": None}
        self.judges[key] = out
        if ref is None or (ref["ko"] is None and not self.runner.dry):
            out["error"] = "no reference translation"
            return
        if cand is None or (cand["ko"] is None and not self.runner.dry):
            out["error"] = "no candidate"
            return
        ref_ko = ref["ko"] or "가" * int(len(sent["text"]) * 0.5)
        cand_ko = cand["ko"] if cand["ko"] is not None else "가" * int(len(sent["text"]) * 0.5)
        body = self.judge_body(previous, sent["text"], ref_ko, cand_ko, ", ".join(sent["key"]))
        try:
            parsed, failed, records = ask_json(self.runner, "judge", body, 130, valid_judge)
            out["cost"] = sum(r["cost"] for r in records)
            out["seconds"] = sum(r["seconds"] for r in records)
            if parsed:
                out["judge"] = parsed
            elif failed:
                out["judge"] = {"parse_error": True, "raw": records[-1]["text"][:300] if records else ""}
        except llm.CallError as error:
            out["error"] = f"call failed: {error}"
        except llm.BudgetStop as stop:
            self.stop = stop

    def execute(self, tasks):
        if self.workers <= 1 or self.runner.dry:
            for task in tasks:
                task()
            return
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for future in [pool.submit(t) for t in tasks]:
                future.result()

    def run(self, pieces, conditions, translators, variants):
        """pieces: list of {"id", "sentences": [...], "asr": [texts] or None}. Returns the rows."""
        tasks, plan = [], []
        for piece in pieces:
            sents = piece["sentences"]
            for i, s in enumerate(sents):
                previous = [labelled(p, p["text"]) for p in sents[max(0, i - JUDGE_CONTEXT):i]]
                tasks.append(lambda s=s, previous=previous: self.do_reference(s, previous))
            for cond in conditions:
                if cond == "T1" and piece["asr"] is None:
                    continue
                texts = [s["text"] for s in sents] if cond == "T0" else piece["asr"]
                for model in translators:
                    for variant in variants:
                        for i, s in enumerate(sents):
                            prev_lines = [labelled(sents[j], texts[j]) for j in range(i) if texts[j].strip()]
                            tasks.append(lambda s=s, c=cond, m=model, v=variant, p=prev_lines, t=texts[i]:
                                         self.do_candidate(s, c, m, v, p, t))
                            plan.append((s, i, cond, model, variant, sents))
        self.execute(tasks)
        judge_tasks = []
        for s, i, cond, model, variant, sents in plan:
            previous = [labelled(p, p["text"]) for p in sents[max(0, i - JUDGE_CONTEXT):i]]
            judge_tasks.append(lambda s=s, c=cond, m=model, v=variant, p=previous: self.do_judge(s, c, m, v, p))
        if not self.stop:
            self.execute(judge_tasks)
        rows = []
        for s, i, cond, model, variant, sents in plan:
            key = (s["id"], cond, model, variant)
            ref, cand, judge = self.refs.get(s["id"]), self.cands.get(key), self.judges.get(key)
            if cand is None:
                continue
            ref_kind = ref["kind"] if ref else None
            rows.append({
                "sentence": s["id"], "piece": s["piece"], "speaker": s["spk"], "condition": cond, "translator": model,
                "variant": variant, "english_ref": s["text"], "english_used": cand["english_used"],
                "asr_empty": cand["asr_empty"], "ref_words": len(s["words"]), "key_items": s["key"],
                "reference_ko": ref["ko"] if ref else None, "reference_kind": ref_kind,
                "backchannel": ref_kind == "backchannel" or is_bare_backchannel(s["text"]),
                "candidate_ko": cand["ko"], "candidate_error": cand["error"],
                "judge": judge["judge"] if judge else None, "judge_error": judge["error"] if judge else "not judged",
                "cost_translate": cand["cost"], "cost_judge": judge["cost"] if judge else 0.0,
                "cost_reference": ref["cost"] if ref else 0.0,
                "seconds_translate": cand["seconds"], "seconds_judge": judge["seconds"] if judge else None,
            })
        return rows


# ------------------------------------------------------------------ summary

SEVERITIES = ("minor", "major", "critical")
TYPES = ("omission", "addition", "wrong_meaning", "wrong_name_or_number")


def critical_count(judge):
    n = sum(1 for e in judge.get("errors", []) if e.get("severity") == "critical")
    return n if n else len(judge.get("critical", []))


def _share(rows, wanted):
    n = len(rows)
    if not n:
        return None
    return sum(1 for r in rows if r["judge"]["meaning"] in wanted) / n


def group_metrics(rows):
    judged = [r for r in rows if isinstance(r.get("judge"), dict) and not r["judge"].get("parse_error")]
    parse_error = [r for r in rows if isinstance(r.get("judge"), dict) and r["judge"].get("parse_error")]
    nobc = [r for r in judged if not r["backchannel"]]
    content = [r for r in judged if r.get("reference_kind") == "content"]
    words = sum(r["ref_words"] for r in judged)
    counts = Counter()
    by_type = Counter()
    for r in judged:
        for e in r["judge"].get("errors", []):
            sev, typ = e.get("severity"), e.get("type")
            counts[sev] += 1
            if sev in ("major", "critical"):
                by_type[typ] += 1
    crit = sum(critical_count(r["judge"]) for r in judged)

    def per100w(n):
        return 100.0 * n / words if words else None

    secs = [r["seconds_translate"] for r in rows if r.get("seconds_translate") is not None]
    return {
        "sentences": len(rows), "judged": len(judged), "parse_error": len(parse_error),
        "unjudged": len(rows) - len(judged) - len(parse_error),
        "Meaning_right": _share(judged, ("right",)), "Meaning_right_partly": _share(judged, ("right", "partly")),
        "Meaning_noBC_right": _share(nobc, ("right",)), "Meaning_noBC_right_partly": _share(nobc, ("right", "partly")),
        "n_noBC": len(nobc),
        "Meaning_content_right": _share(content, ("right",)), "Meaning_content_right_partly": _share(content, ("right", "partly")),
        "n_content": len(content),
        "Critical_per_100_sentences": 100.0 * crit / len(judged) if judged else None,
        "T_err_per_100_words": per100w(counts["major"] + counts["critical"]),
        "T_err_minor": per100w(counts["minor"]), "T_err_major": per100w(counts["major"]),
        "T_err_critical": per100w(counts["critical"]),
        "T_err_by_type": {t: per100w(by_type[t]) for t in TYPES},
        "empty_candidates": sum(1 for r in rows if not (r.get("candidate_ko") or "").strip()),
        "asr_empty": sum(1 for r in rows if r.get("asr_empty")),
        "cost_translate_usd": sum(r["cost_translate"] for r in rows),
        "cost_judge_usd": sum(r["cost_judge"] for r in rows),
        "mean_translate_seconds": sum(secs) / len(secs) if secs else None,
    }


def summarise(rows):
    groups = {}
    for r in rows:
        groups.setdefault((r["translator"], r["variant"], r["condition"]), []).append(r)
    return [{"translator": k[0], "variant": k[1], "condition": k[2], **group_metrics(v)} for k, v in sorted(groups.items())]


def _pc(x):
    return "  -  " if x is None else f"{100 * x:5.1f}"


def _num(x, digits=2):
    return "  -  " if x is None else f"{x:.{digits}f}"


def format_table(summary):
    head = (f"{'translator':26} {'variant':9} {'cond':4} {'n':>4} {'perr':>4} | {'Meaning%':>8} {'+partly':>7} | "
            f"{'noBC%':>6} {'+partly':>7} | {'content%':>8} {'+partly':>7} | {'Crit/100s':>9} {'Terr/100w':>9} | "
            f"{'empty':>5} {'$transl':>8} {'s/transl':>8}")
    lines = [head, "-" * len(head)]
    for g in summary:
        lines.append(
            f"{g['translator'].split('/')[-1][:26]:26} {g['variant']:9} {g['condition']:4} {g['sentences']:4d} {g['parse_error']:4d} | "
            f"{_pc(g['Meaning_right']):>8} {_pc(g['Meaning_right_partly']):>7} | "
            f"{_pc(g['Meaning_noBC_right']):>6} {_pc(g['Meaning_noBC_right_partly']):>7} | "
            f"{_pc(g['Meaning_content_right']):>8} {_pc(g['Meaning_content_right_partly']):>7} | "
            f"{_num(g['Critical_per_100_sentences'], 1):>9} {_num(g['T_err_per_100_words']):>9} | "
            f"{g['empty_candidates']:5d} {g['cost_translate_usd']:8.4f} {_num(g['mean_translate_seconds']):>8}")
    lines.append("")
    lines.append("n = sentences; perr = judge reply could not be parsed (not counted as wrong, not in the % columns); "
                 "Meaning% = share judged right, +partly = right or partly; noBC = without bare backchannels; "
                 "content = reference kind content only; Crit/100s = critical errors per 100 judged sentences; "
                 "Terr = major+critical errors per 100 reference words; empty = empty candidates.")
    for g in summary:
        types = ", ".join(f"{t} {_num(v)}" for t, v in g["T_err_by_type"].items())
        lines.append(f"  {g['translator'].split('/')[-1]} {g['variant']} {g['condition']}: T_err minor {_num(g['T_err_minor'])}, "
                     f"major {_num(g['T_err_major'])}, critical {_num(g['T_err_critical'])} per 100 words; "
                     f"major+critical by type: {types}; unjudged {g['unjudged']}; ASR-empty sentences {g['asr_empty']}; "
                     f"judge ${g['cost_judge_usd']:.4f}")
    return "\n".join(lines)


# ------------------------------------------------------------------ plan printing

STEP_NAMES = {"reference": "a. reference Korean", "translate": "b. candidate Korean", "judge": "c. judge"}


def format_plan(runner, prices, budget_usd, title="Plan"):
    lines = [f"{title} (prices: {prices.source})",
             f"{'step':22} {'cached':>7} {'to call':>8} {'tokens in':>10} {'tokens out':>10} {'est. $':>9}"]
    total_calls = total_usd = 0
    for step in ("reference", "translate", "judge"):
        s = runner.stats.get(step)
        if not s:
            continue
        calls = s["planned"] if runner.dry else s["new"]
        lines.append(f"{STEP_NAMES[step]:22} {s['cached']:7d} {calls:8d} {s['tokens_in']:10d} {s['tokens_out']:10d} {s['usd']:9.4f}")
        total_calls += calls
        total_usd += s["usd"]
    lines.append(f"{'total':22} {'':7} {total_calls:8d} {'':10} {'':10} {total_usd:9.4f}   (budget ${budget_usd:.2f})")
    if prices.unknown:
        lines.append(f"  price not listed, assumed ${llm.ASSUMED_PRICE[0] * 1e6:.2f}/{llm.ASSUMED_PRICE[1] * 1e6:.2f} per M tokens: "
                     + ", ".join(sorted(prices.unknown)))
    repeats = sum(s["repeat"] for s in runner.stats.values())
    if repeats:
        lines.append(f"  {repeats} planned request(s) are identical to another one (for example T1 text equal to the reference) and are called once.")
    lines.append("  Estimate: ASCII 4 characters a token, Korean 1 per character; judge reply 130 tokens; +-30%.")
    return "\n".join(lines), total_calls, total_usd


# ------------------------------------------------------------------ judge check

SEVERITY_ORDER = {"minor": 1, "major": 2, "critical": 3}


def top_severity(judge):
    best = None
    for e in judge.get("errors", []):
        sev = e.get("severity")
        if SEVERITY_ORDER.get(sev, 0) > SEVERITY_ORDER.get(best, 0):
            best = sev
    return best


def load_cases(paths=(REGRESSION, REGRESSION_AMI)):
    cases = []
    for p in paths:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                cases.extend(json.load(f))
    return cases


def judge_check(ev, cases):
    """Run the judge on cases with expected verdicts. Returns the result rows and the counts."""
    results = []
    for c in cases:
        previous = c.get("previous", "")
        body = ev.judge_body(previous.split("\n") if previous else [], c["source_en"], c["reference_ko"], c["candidate_ko"],
                             c.get("key_items", ""))
        try:
            parsed, failed, records = ask_json(ev.runner, "judge", body, 130, valid_judge)
        except llm.CallError as error:
            parsed, failed = None, True
        if parsed is None and ev.runner.dry:
            results.append({"id": c["id"], "expected": c["expected_meaning"], "got": None, "planned": True})
            continue
        got = parsed["meaning"] if parsed else None
        sev = top_severity(parsed) if parsed else None
        exp_sev = c.get("expected_top_severity")
        results.append({"id": c["id"], "expected": c["expected_meaning"], "got": got, "expected_severity": exp_sev,
                        "got_severity": sev, "meaning_ok": got == c["expected_meaning"],
                        "severity_ok": parsed is not None and sev == exp_sev, "parse_error": parsed is None,
                        "comment": (parsed or {}).get("comment", "")})
    done = [r for r in results if not r.get("planned")]
    counts = {"cases": len(results), "judged": len(done),
              "meaning_agree": sum(1 for r in done if r["meaning_ok"]),
              "severity_agree": sum(1 for r in done if r["severity_ok"]),
              "parse_errors": sum(1 for r in done if r["parse_error"])}
    return results, counts


def format_judge_check(results, counts):
    lines = [f"{'case':6} {'expected':9} {'got':9} {'exp sev':9} {'got sev':9}"]
    for r in results:
        if r.get("planned"):
            continue
        mark = "" if r["meaning_ok"] and r["severity_ok"] else "   <-- differs"
        lines.append(f"{r['id']:6} {r['expected']:9} {str(r['got']):9} {str(r['expected_severity']):9} {str(r['got_severity']):9}{mark}")
    lines.append(f"meaning agrees in {counts['meaning_agree']} of {counts['judged']} cases; top severity agrees in "
                 f"{counts['severity_agree']} of {counts['judged']}; parse errors {counts['parse_errors']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ main

def select_pieces(manifest, wanted):
    if not wanted:
        return [m["id"] for m in manifest]
    ids = []
    for w in wanted:
        hit = [m["id"] for m in manifest if m["id"] == w or m["meeting"] == w]
        if not hit:
            raise SystemExit(f"no piece or meeting called {w!r} in the manifest")
        ids.extend(i for i in hit if i not in ids)
    return ids


def load_pieces(args, dry):
    with open(os.path.join(args.prepared_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    pieces, notes = [], []
    for pid in select_pieces(manifest, args.piece):
        with open(os.path.join(args.prepared_dir, pid + ".json"), encoding="utf-8") as f:
            piece = json.load(f)
        sents = build_sentences(pid, piece)
        asr_words = load_asr_words(args.asr_dir, args.asr_model, pid) if "T1" in args.conditions else None
        asr = None
        if asr_words is not None:
            asr = assign_asr([s["words"] for s in sents], asr_words)
        elif "T1" in args.conditions:
            if dry:
                asr = [s["text"] for s in sents]
                notes.append(f"{pid}: no recogniser text in {args.asr_dir}/{args.asr_model}; T1 estimated from the reference text")
            else:
                notes.append(f"{pid}: no recogniser text in {args.asr_dir}/{args.asr_model}; T1 skipped")
        if args.max_seconds:
            keep = [i for i, s in enumerate(sents) if s["end"] <= piece["start"] + args.max_seconds]
            sents = [sents[i] for i in keep]
            if asr is not None:
                asr = [asr[i] for i in keep]
        pieces.append({"id": pid, "sentences": sents, "asr": asr})
    return pieces, notes


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="Copy-paste examples and the file layout are in the docstring at the top of bench/translate_eval.py.")
    p.add_argument("--run-name", default="D_run", help="output folder bench/results/<run-name> (default D_run)")
    p.add_argument("--piece", action="append", help="piece id (ES2004a.cut01) or meeting (ES2004a); repeatable; default all 12")
    p.add_argument("--conditions", default="T0,T1", help="T0 = reference English in, T1 = recogniser text in (default T0,T1)")
    p.add_argument("--asr-model", default="turbo", help="folder name under --asr-dir for the T1 texts (default turbo)")
    p.add_argument("--asr-dir", default=os.path.join(RESULTS, "asr"))
    p.add_argument("--prepared-dir", default=PREPARED)
    p.add_argument("--results-dir", default=RESULTS)
    p.add_argument("--translator", action="append",
                   help="OpenRouter model id under test; repeatable; default = roles.translate[0] of config/models.json")
    p.add_argument("--prompt-variant", action="append", choices=sorted(VARIANTS), help="repeatable; default app")
    p.add_argument("--reference-model", default=DEFAULT_REFERENCE_MODEL, help=f"default {DEFAULT_REFERENCE_MODEL}")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL, help=f"default {DEFAULT_JUDGE_MODEL}")
    p.add_argument("--max-seconds", type=float, help="use only sentences that end within this many seconds of the piece start")
    p.add_argument("--budget-usd", type=float, help="refuse above this estimate and stop at it (default: budget_usd_per_batch in notes/bench_control.md, else 5)")
    p.add_argument("--dry-run", action="store_true", help="print the plan and the estimate only")
    p.add_argument("--fake", action="store_true", help="no network: fake models, separate cache (cache_fake)")
    p.add_argument("--offline-prices", action="store_true", help="use bench/model_prices.json, do not fetch OpenRouter's list")
    p.add_argument("--judge-check", action="store_true", help="run the judge on the regression cases and print the agreement")
    p.add_argument("--make-stub-asr", action="store_true", help="write bench/results/asr/stub/<piece>.txt from the reference text")
    p.add_argument("--no-zdr", action="store_true", help="do not require zero data retention (AMI is public)")
    p.add_argument("--workers", type=int, default=4, help="parallel calls (default 4)")
    p.add_argument("--timeout", type=float, default=90.0, help="seconds per call")
    args = p.parse_args(argv)
    args.conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    bad = [c for c in args.conditions if c not in ("T0", "T1")]
    if bad:
        p.error(f"unknown condition {bad}")
    args.translator = args.translator or [default_translator()]
    args.prompt_variant = args.prompt_variant or ["app"]
    if args.budget_usd is None:
        args.budget_usd = read_budget_default()
    return args


def make_runner(args, dry, budget_usd):
    prices = llm.load_prices(offline=args.offline_prices or args.fake)
    cache = llm.Cache(os.path.join(args.results_dir, "cache_fake" if args.fake else "cache"))
    client = llm.FakeClient(prices) if args.fake else llm.RealClient(timeout=args.timeout)
    return llm.Runner(client, cache, llm.Budget(budget_usd), prices, dry=dry), prices


def main(argv=None):
    args = parse_args(argv)
    zdr = not args.no_zdr

    if args.make_stub_asr:
        out_dir = os.path.join(args.asr_dir, "stub")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(args.prepared_dir, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        for pid in select_pieces(manifest, args.piece):
            with open(os.path.join(args.prepared_dir, pid + ".json"), encoding="utf-8") as f:
                words = [w for s in build_sentences(pid, json.load(f)) for w in s["words"]]
            with open(os.path.join(out_dir, pid + ".txt"), "w", encoding="utf-8") as f:
                f.write(make_stub_text(words) + "\n")
            print(f"wrote {os.path.join(out_dir, pid + '.txt')}")
        return 0

    if args.judge_check:
        cases = load_cases()
        planner, prices = make_runner(args, True, args.budget_usd)
        ev = Evaluation(planner, args.reference_model, args.judge_model, zdr, 1)
        judge_check(ev, cases)
        text, calls, usd = format_plan(planner, prices, args.budget_usd, f"Plan: judge check, {len(cases)} cases, judge {args.judge_model}")
        print(text)
        if args.dry_run:
            return 0
        if usd > args.budget_usd:
            print(f"REFUSED: estimate ${usd:.4f} is above the budget ${args.budget_usd:.2f}")
            return 2
        runner, prices = make_runner(args, False, args.budget_usd)
        ev = Evaluation(runner, args.reference_model, args.judge_model, zdr, 1)
        try:
            results, counts = judge_check(ev, cases)
        except llm.BudgetStop as stop:
            print(f"STOPPED: {stop}")
            return 3
        out_dir = os.path.join(args.results_dir, args.run_name)
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "judge_check.json"), "w", encoding="utf-8") as f:
            json.dump({"judge_model": args.judge_model, "counts": counts, "results": results}, f, indent=1, ensure_ascii=False)
        print(format_judge_check(results, counts))
        print(f"new calls {runner.new_calls()}, spent ${runner.budget.spent:.4f}")
        return 0

    pieces, notes = load_pieces(args, args.dry_run)
    n_sent = sum(len(p["sentences"]) for p in pieces)
    print(f"{len(pieces)} piece(s), {n_sent} sentences, conditions {','.join(args.conditions)}, translators {args.translator}, "
          f"variants {args.prompt_variant}")
    for n in notes:
        print("  note:", n)

    planner, prices = make_runner(args, True, args.budget_usd)
    Evaluation(planner, args.reference_model, args.judge_model, zdr, 1).run(pieces, args.conditions, args.translator, args.prompt_variant)
    text, calls, usd = format_plan(planner, prices, args.budget_usd, "Plan")
    print(text)
    if args.dry_run:
        return 0
    if usd > args.budget_usd:
        print(f"REFUSED: estimate ${usd:.4f} is above the budget ${args.budget_usd:.2f}. Nothing was called.")
        return 2
    if calls == 0:
        print("Nothing to call: every answer is in the cache.")

    runner, prices = make_runner(args, False, args.budget_usd)
    ev = Evaluation(runner, args.reference_model, args.judge_model, zdr, args.workers)
    out_dir = os.path.join(args.results_dir, args.run_name)
    os.makedirs(out_dir, exist_ok=True)
    stopped = None
    rows = []
    try:
        rows = ev.run(pieces, args.conditions, args.translator, args.prompt_variant)
        stopped = ev.stop
    except KeyboardInterrupt:
        print("Interrupted: run the same command again to continue (finished calls are cached).")
        return 130
    with open(os.path.join(out_dir, "rows.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = summarise(rows)
    table = format_table(summary)
    header = [f"Run {args.run_name}: {len(rows)} rows, new calls this run {runner.new_calls()}, spent ${runner.budget.spent:.4f} "
              f"(budget ${args.budget_usd:.2f}); reference {args.reference_model}, judge {args.judge_model}; "
              f"variants {args.prompt_variant}; max-seconds {args.max_seconds}; fake={args.fake}"]
    if stopped:
        header.append(f"STOPPED EARLY: {stopped}. Rows are partial; run again with a larger --budget-usd to continue.")
    header.extend("note: " + n for n in notes)
    with open(os.path.join(out_dir, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n\n" + table + "\n")
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"run": args.run_name, "models": {"reference": args.reference_model, "judge": args.judge_model,
                                                    "translators": args.translator},
                   "variants": args.prompt_variant, "fake": args.fake, "spent_usd": runner.budget.spent,
                   "new_calls": runner.new_calls(), "stopped": str(stopped) if stopped else None, "groups": summary},
                  f, indent=1, ensure_ascii=False)
    print()
    print("\n".join(header))
    print(table)
    print(f"written: {out_dir}/rows.jsonl, summary.txt, summary.json")
    return 3 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
