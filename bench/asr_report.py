"""Free analysis of ASR text against the reference (no model calls): MER, Missing, Invented, Wrong, Key per piece,
and which reference sentences were really missed.

    python3 bench/asr_report.py --run E_small --asr-model small

Reads bench/results/<run>/rows.jsonl (the T0 rows give the normalised reference sentences in order) and
bench/results/asr/<asr-model>/<piece>.txt. Writes bench/results/<run>/asr_report.txt and prints it.
A reference sentence is 'missed' when 80% or more of its words are deletions in the alignment of the whole piece.
"""
import argparse, collections, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_text as st


def per_sentence_deleted(ops, lengths):
    """lengths: tokens per reference sentence. Returns (deleted, kept words) per sentence."""
    edge, total = [], 0
    for n in lengths:
        edge.append((total, total + n))
        total += n
    dele = [0] * len(lengths)
    for op, ri, _ in ops:
        if op == "D":
            for i, (a, b) in enumerate(edge):
                if a <= ri < b:
                    dele[i] += 1
                    break
    return dele


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", default="E_small")
    ap.add_argument("--asr-model", default="small")
    args = ap.parse_args()
    rows = [json.loads(l) for l in open(os.path.join(HERE, "results", args.run, "rows.jsonl"))]
    t0 = [r for r in rows if r["condition"] == "T0"]
    pieces = list(dict.fromkeys(r["piece"] for r in t0))
    out, tot = [], collections.Counter()
    miss_rows = []
    for p in pieces:
        sents = sorted([r for r in t0 if r["piece"] == p], key=lambda r: r["sentence"])
        ref_toks = [st.tokens(r["english_ref"]) for r in sents]
        ref = [t for ts in ref_toks for t in ts]
        hyp = st.tokens(open(os.path.join(HERE, "results", "asr", args.asr_model, p + ".txt")).read())
        ops = st.align(ref, hyp)
        key, pos = [], 0
        for r, ts in zip(sents, ref_toks):
            ks = {k.lower() for k in (r.get("key_items") or [])}
            key += [pos + i for i, t in enumerate(ts) if t in ks]
            pos += len(ts)
        s = st.score(ref, hyp, key or None)
        out.append(f"{p:15} words {s['N']:4d}  MER {100*s['MER']:5.1f}%  Missing {100*s['Missing']:4.1f}%  "
                   f"Invented {100*s['Invented']:4.1f}%  Wrong {100*s['Wrong']:4.1f}%  Key "
                   f"{'-' if s['Key'] is None else format(100*s['Key'], '.0f') + '%'} ({len(key)} items)")
        for k in ("N", "S", "D", "I"):
            tot[k] += s[k]
        dele = per_sentence_deleted(ops, [len(t) for t in ref_toks])
        for r, ts, d in zip(sents, ref_toks, dele):
            if ts and d / len(ts) >= 0.8:
                miss_rows.append((p, r["sentence"], len(ts), r["backchannel"], r["english_ref"]))
    n = tot["N"]
    out.append(f"{'ALL':15} words {n:4d}  MER {100*(tot['S']+tot['D']+tot['I'])/n:5.1f}%  Missing {100*tot['D']/n:4.1f}%  "
               f"Invented {100*tot['I']/n:4.1f}%  Wrong {100*tot['S']/n:4.1f}%")
    bc = [m for m in miss_rows if m[3]]
    content = [m for m in miss_rows if not m[3]]
    missed_words = sum(m[2] for m in content)
    out.append(f"\nSentences missed (80% or more of the words deleted): {len(miss_rows)}; bare backchannels {len(bc)}; "
               f"content {len(content)} ({missed_words} words, {100*missed_words/n:.1f}% of all reference words)")
    out.append("Content sentences missed (piece, number, words, text):")
    for m in content:
        out.append(f"  {m[0]} #{str(m[1]):>6} ({m[2]:2d}w) {m[4][:90]}")
    text = "\n".join(out)
    open(os.path.join(HERE, "results", args.run, "asr_report.txt"), "w").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
