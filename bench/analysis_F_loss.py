"""Stage F: where is translation quality lost? Read-only analysis of stage E data, no model calls.

    python3 bench/analysis_F_loss.py            # writes bench/results/F/loss.txt and sentences.jsonl

Inputs: bench/results/E_small/rows.jsonl, bench/audio/ami/prepared/PIECE.json,
bench/results/asr/small/PIECE.report/PIECE.json (segment times).
Only the two fully judged pieces (ES2004a.cut02, IS1009a.cut02) are used for judged numbers.
"""
import collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_text as st                      # noqa: E402
import translate_eval as te                  # noqa: E402  (only pure helpers are used)

PIECES = ["ES2004a.cut02", "IS1009a.cut02"]
ALL4 = PIECES + ["TS3003a.cut01", "TS3003a.cut04"]
OUT = os.path.join(HERE, "results", "F")
OVERLAP_S = 0.1

# ---------------------------------------------------------------- normalisation (analysis only)
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
       "seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def num_words(n):
    if n < 20:
        return [ONES[n]]
    if n < 100:
        return [TENS[n // 10]] + ([ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        return [ONES[n // 100], "hundred"] + (num_words(n % 100) if n % 100 else [])
    if 1000 < n < 10000 and n % 100 and n // 100 % 10:   # 1250 -> twelve fifty (prices, years)
        return num_words(n // 100) + num_words(n % 100)
    if n < 1_000_000:
        return num_words(n // 1000) + ["thousand"] + (num_words(n % 1000) if n % 1000 else [])
    return num_words(n // 1_000_000) + ["million"] + (num_words(n % 1_000_000) if n % 1_000_000 else [])


SPELL = {"colours": "colors", "colour": "color", "etc": "etcetera", "'kay": "okay", "kay": "okay", "'em": "them",
         "em": "them", "'cause": "because", "cause": "because", "cos": "because", "ok": "okay", "mm-hmm": "mmhmm",
         "favourite": "favorite", "centre": "center", "realise": "realize", "organise": "organize"}


def norm_tokens(text):
    """Tokens of score_text after: hyphen compounds joined, digits to words, a few spellings unified,
    sound labels like (typing) [MUSIC] removed."""
    text = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", text)
    text = re.sub(r"(\w)-(\w)", r"\1\2", text)
    text = text.replace("T_V_", "TV")
    out = []
    for t in st.tokens(text):
        t = SPELL.get(t, t)
        if t.isdigit():
            out += num_words(int(t))
        else:
            out.append(t)
    return out


def wer(ref, hyp):
    if not ref:
        return 0.0 if not hyp else 1.0
    ops = st.align(ref, hyp)
    return sum(op != "M" for op, _, _ in ops) / len(ref), ops


# ---------------------------------------------------------------- sentences with word indexes
def sentences_with_index(piece_id, piece):
    """Same split as translate_eval.build_sentences, but keeps the word indexes of each sentence."""
    ws = piece["words"]
    times = [(w["start"], w["end"]) for w in ws]
    ends = list(piece["ends"])
    if not ends or ends[-1] != len(ws) - 1:
        ends.append(len(ws) - 1)
    out, start = [], 0
    for e in ends:
        run = list(range(start, e + 1))
        start = e + 1
        for part in te.split_at_gaps(times, run, te.GAP_SECONDS):
            out.append(part)
    built = te.build_sentences(piece_id, piece)
    assert len(built) == len(out)
    return [dict(b, idx=p) for b, p in zip(built, out)]


def overlapped_words(ws):
    flag = [False] * len(ws)
    order = sorted(range(len(ws)), key=lambda i: ws[i]["start"])
    for a_pos, i in enumerate(order):
        for j in order[a_pos + 1:]:
            if ws[j]["start"] >= ws[i]["end"]:
                break
            if ws[i]["spk"] != ws[j]["spk"]:
                ov = min(ws[i]["end"], ws[j]["end"]) - max(ws[i]["start"], ws[j]["start"])
                if ov > OVERLAP_S:
                    flag[i] = flag[j] = True
    # words that start inside a long earlier word of another speaker are covered by the loop above, since
    # `order` is sorted by start and we scan forward until starts pass the end of word i.
    return flag


def asr_segments(piece):
    path = os.path.join(HERE, "results", "asr", "small", piece + ".report", piece + ".json")
    d = json.load(open(path))
    segs = []
    for s in d["segments"]:
        txt = re.sub(r"<\|[^|]*\|>", "", s["text"]).strip()
        segs.append({"start": s["start"], "end": s["end"], "text": txt, "avg": s["avgLogprob"],
                     "comp": s.get("compressionRatio"), "nsp": s.get("noSpeechProb"), "temp": s.get("temperature")})
    return segs


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = [json.loads(l) for l in open(os.path.join(HERE, "results", "E_small", "rows.jsonl"))]
    by = {(r["sentence"], r["condition"]): r for r in rows}
    out_rows = []
    word_stats = collections.Counter()
    for p in ALL4:
        piece = json.load(open(os.path.join(HERE, "audio", "ami", "prepared", p + ".json")))
        ws = piece["words"]
        ov = overlapped_words(ws)
        for i, w in enumerate(ws):
            word_stats[(p, ov[i])] += 1
        for s in sentences_with_index(p, piece):
            t0, t1 = by.get((s["id"], "T0")), by.get((s["id"], "T1"))
            if t0 is None or t1 is None:
                continue
            assert t0["english_ref"] == s["text"], (s["id"], t0["english_ref"], s["text"])
            n_ov = sum(ov[i] for i in s["idx"])
            ref_n, hyp_n = norm_tokens(s["text"]), norm_tokens(t1["english_used"])
            ref_r, hyp_r = st.tokens(s["text"]), st.tokens(t1["english_used"])
            w_raw = wer(ref_r, hyp_r)[0] if ref_r else 0.0
            w_n, ops = wer(ref_n, hyp_n) if ref_n else (0.0, [])
            cnt = collections.Counter(op for op, _, _ in ops)
            j0, j1 = t0.get("judge") or {}, t1.get("judge") or {}
            out_rows.append({
                "id": s["id"], "piece": p, "spk": s["spk"], "start": s["start"] - piece["start"],
                "end": s["end"] - piece["start"], "n": len(ref_r), "n_overlap": n_ov,
                "ov_share": n_ov / len(s["idx"]), "backchannel": t1["backchannel"], "asr_empty": t1["asr_empty"],
                "wer_raw": w_raw, "wer": w_n, "D": cnt["D"], "S": cnt["S"], "I": cnt["I"],
                "ref": s["text"], "asr": t1["english_used"], "ko_ref": t0["reference_ko"],
                "ko_t0": t0["candidate_ko"], "ko_t1": t1["candidate_ko"],
                "m0": j0.get("meaning"), "m1": j1.get("meaning"),
                "crit0": len(j0.get("critical") or []), "crit1": len(j1.get("critical") or []),
                "err1": j1.get("errors") or [], "err0": j0.get("errors") or [], "comment1": j1.get("comment"),
                "key": s["key"]})
    with open(os.path.join(OUT, "sentences.jsonl"), "w") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    L = []
    pr = L.append
    # words overlapped
    for p in ALL4:
        a, b = word_stats[(p, True)], word_stats[(p, False)]
        pr(f"{p}: words {a+b}, overlapped (> {OVERLAP_S}s with another speaker) {a} ({100*a/(a+b):.1f}%)")
    # ---- MER raw vs normalised, all 4 pieces (whole piece alignment)
    pr("\nMER per piece, whole-piece alignment, raw tokens vs normalised (digits->words, hyphens, spellings, sound labels):")
    tot = collections.Counter()
    for p in ALL4:
        sents = [r for r in out_rows if r["piece"] == p]
        hyp_txt = open(os.path.join(HERE, "results", "asr", "small", p + ".txt")).read()
        for tag, fn in (("raw", st.tokens), ("norm", norm_tokens)):
            ref = [t for r in sents for t in fn(r["ref"])]
            sc = st.score(ref, fn(hyp_txt))
            for k in ("N", "S", "D", "I"):
                tot[(tag, k)] += sc[k]
            pr(f"  {p:14} {tag:4} N {sc['N']:4d} MER {100*sc['MER']:5.1f}  D {100*sc['Missing']:4.1f}  "
               f"I {100*sc['Invented']:4.1f}  S {100*sc['Wrong']:4.1f}")
    for tag in ("raw", "norm"):
        n = tot[(tag, "N")]
        pr(f"  ALL            {tag:4} N {n:4d} MER {100*(tot[(tag,'S')]+tot[(tag,'D')]+tot[(tag,'I')])/n:5.1f}  "
           f"D {100*tot[(tag,'D')]/n:4.1f}  I {100*tot[(tag,'I')]/n:4.1f}  S {100*tot[(tag,'S')]/n:4.1f}")

    # ---- per-word Missing, overlapped vs clean (normalised, whole piece)
    pr("\nWords missing (deleted), overlapped vs clean, whole-piece alignment, normalised tokens (approx.: a reference"
       " word is overlapped if its sentence-word is; multi-token words share the flag):")
    agg = collections.Counter()
    for p in ALL4:
        piece = json.load(open(os.path.join(HERE, "audio", "ami", "prepared", p + ".json")))
        ws = piece["words"]
        ov = overlapped_words(ws)
        sents = sentences_with_index(p, piece)
        ref, flag = [], []
        for s in sents:
            for wi, w in zip(s["idx"], s["words"]):
                for t in norm_tokens(w):
                    ref.append(t)
                    flag.append(ov[wi])
        hyp = norm_tokens(open(os.path.join(HERE, "results", "asr", "small", p + ".txt")).read())
        for op, i, _ in st.align(ref, hyp):
            if i is not None:
                agg[(p, flag[i], "N")] += 1
                agg[(p, flag[i], op)] += 1
    for f_ in (True, False):
        n = sum(agg[(p, f_, "N")] for p in ALL4)
        d = sum(agg[(p, f_, "D")] for p in ALL4)
        s_ = sum(agg[(p, f_, "S")] for p in ALL4)
        pr(f"  {'overlapped' if f_ else 'clean':10}: tokens {n:4d}  deleted {100*d/n:4.1f}%  substituted {100*s_/n:4.1f}%")
    for p in ALL4:
        n, d = agg[(p, False, "N")], agg[(p, False, "D")]
        s_ = agg[(p, False, "S")]
        pr(f"    clean only {p:14}: tokens {n:4d} deleted {100*d/n:4.1f}% substituted {100*s_/n:4.1f}%")

    # ---- judged sentences
    J = [r for r in out_rows if r["piece"] in PIECES]
    pr(f"\nJudged sentences (2 pieces): {len(J)}; T0 right {sum(r['m0']=='right' for r in J)}, "
       f"T1 right {sum(r['m1']=='right' for r in J)}; missing judge T0 {sum(r['m0'] is None for r in J)}, "
       f"T1 {sum(r['m1'] is None for r in J)}")

    def cls(r):
        if r["asr_empty"]:
            return "1 ASR empty"
        if r["wer"] > 0.5:
            return "2 ASR WER > 50%"
        if r["wer"] > 0.2:
            return "3 ASR WER 20-50%"
        if r["wer"] > 0:
            return "4 ASR WER 1-20%"
        return "5 ASR exact (normalised)"

    def ovc(r):
        if r["n_overlap"] == 0:
            return "clean"
        return "mostly overlapped" if r["ov_share"] >= 0.5 else "partly overlapped"

    def table(sel, title):
        pr(f"\n{title}: {len(sel)} sentences")
        pr(f"  {'ASR class':26} {'n':>4} {'T1 right':>9} {'T1 not right':>12} {'(of which T0 also not right)':>28}")
        for c in sorted({cls(r) for r in sel}):
            g = [r for r in sel if cls(r) == c]
            bad = [r for r in g if r["m1"] != "right"]
            pr(f"  {c:26} {len(g):4d} {sum(r['m1']=='right' for r in g):9d} {len(bad):12d} "
               f"{sum(r['m0']!='right' for r in bad):28d}")
        bad = [r for r in sel if r["m1"] != "right"]
        pr(f"  {'total':26} {len(sel):4d} {len(sel)-len(bad):9d} {len(bad):12d} {sum(r['m0']!='right' for r in bad):28d}")
        if sel:
            pr(f"  T0 right {100*sum(r['m0']=='right' for r in sel)/len(sel):.1f}%  T1 right "
               f"{100*sum(r['m1']=='right' for r in sel)/len(sel):.1f}%  T1 right+partly "
               f"{100*sum(r['m1'] in ('right','partly') for r in sel)/len(sel):.1f}%  "
               f"critical/100 sent T0 {100*sum(r['crit0'] for r in sel)/len(sel):.1f} T1 {100*sum(r['crit1'] for r in sel)/len(sel):.1f}")

    table(J, "ALL judged")
    for o in ("clean", "partly overlapped", "mostly overlapped"):
        table([r for r in J if ovc(r) == o], f"overlap = {o}")
    table([r for r in J if r["backchannel"]], "bare backchannel")
    table([r for r in J if not r["backchannel"]], "content")
    table([r for r in J if not r["backchannel"] and ovc(r) == "clean"], "content AND clean")
    table([r for r in J if not r["backchannel"] and ovc(r) != "clean"], "content AND some overlap")
    # words-weighted view of T1 loss
    pr("\nWeighted by reference words (a lost 'Yeah' weighs 1, a 41-word sentence 41):")
    for name, sel in (("all", J), ("clean", [r for r in J if ovc(r) == "clean"]),
                      ("content clean", [r for r in J if ovc(r) == "clean" and not r["backchannel"]])):
        n = sum(r["n"] for r in sel)
        pr(f"  {name:14} words {n:4d}  T0 right {100*sum(r['n'] for r in sel if r['m0']=='right')/n:5.1f}%  "
           f"T1 right {100*sum(r['n'] for r in sel if r['m1']=='right')/n:5.1f}%  "
           f"T1 right+partly {100*sum(r['n'] for r in sel if r['m1'] in ('right','partly'))/n:5.1f}%")

    # judge error types on T1, by ASR class
    pr("\nT1 judge errors (major+critical), by type and ASR class:")
    c = collections.Counter()
    for r in J:
        for e in r["err1"]:
            if e.get("severity") in ("major", "critical"):
                c[(cls(r), e.get("type"))] += 1
    for k in sorted(c):
        pr(f"  {k[0]:26} {k[1]:16} {c[k]}")
    # translation's own loss: ASR exact but T1 not right
    pr("\nASR exact (normalised) but T1 not right (translation's own loss on correct input):")
    for r in J:
        if cls(r) == "5 ASR exact (normalised)" and r["m1"] != "right":
            pr(f"  {r['id']} T0 {r['m0']} T1 {r['m1']} | asr '{r['asr']}' | ref '{r['ref']}'")
    # long sentences
    pr("\nLongest reference sentences (>= 25 words) in judged pieces:")
    for r in sorted(J, key=lambda r: -r["n"]):
        if r["n"] < 25:
            break
        pr(f"  {r['id']} spk {r['spk']} {r['n']}w ov {r['n_overlap']} t {r['start']:.1f}-{r['end']:.1f} "
           f"wer {r['wer']:.2f} empty {r['asr_empty']} m0 {r['m0']} m1 {r['m1']}")
    open(os.path.join(OUT, "loss.txt"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
