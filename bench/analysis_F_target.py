"""Stage F: numbers for the target use (one main speaker): clean words, TS3003a.cut01, key items, error types.

    python3 bench/analysis_F_target.py      # writes bench/results/F/target.txt (read-only on data)

Whole-piece alignment with normalised tokens (analysis_F_loss.norm_tokens). Key items as in asr_report
(key_items of the reference sentences, lower-cased; normalised the same way).
"""
import collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_text as st                                            # noqa: E402
from analysis_F_loss import norm_tokens, overlapped_words, sentences_with_index, ALL4, asr_segments  # noqa: E402

OUT = os.path.join(HERE, "results", "F")
MODELS = ["small", "small_novad", "turbo", "turbo_novad"]


def piece_tokens(p):
    piece = json.load(open(os.path.join(HERE, "audio", "ami", "prepared", p + ".json")))
    ov = overlapped_words(piece["words"])
    ref, flag, key, spk = [], [], [], []
    for s in sentences_with_index(p, piece):
        ks = {k.lower() for k in s["key"]}
        for wi, w in zip(s["idx"], s["words"]):
            for t in norm_tokens(w):
                ref.append(t)
                flag.append(ov[wi])
                key.append(w.lower() in ks)
                spk.append(piece["words"][wi]["spk"])
    return ref, flag, key, spk


def main():
    global MODELS
    if len(sys.argv) > 1:          # e.g. python3 bench/analysis_F_target.py small small_prompt
        MODELS = sys.argv[1:]
    L = []
    pr = L.append
    subs, dels_clean, runs = collections.Counter(), collections.Counter(), []
    for model in MODELS:
        agg = collections.Counter()
        for p in ALL4:
            ref, flag, key, spk = piece_tokens(p)
            hyp = norm_tokens(open(os.path.join(HERE, "results", "asr", model, p + ".txt")).read())
            ops = st.align(ref, hyp)
            run = 0
            for op, i, j in ops:
                if op == "I":
                    agg[("I", p)] += 1
                    continue
                c = "clean" if not flag[i] else "ov"
                agg[(c, "N", p)] += 1
                agg[(c, op, p)] += 1
                if key[i]:
                    agg[(c, "keyN", p)] += 1
                    agg[(c, "key" + op, p)] += 1
                if model == "small" and c == "clean":
                    if op == "S":
                        subs[(ref[i], hyp[j])] += 1
                    if op == "D":
                        dels_clean[ref[i]] += 1
                if model == "small":
                    run = run + 1 if op == "D" else 0
                    if op != "D" and run:
                        pass
                if model == "small" and op == "D":
                    if runs and runs[-1][0] == p and runs[-1][2] == i - 1:
                        runs[-1][2] = i
                    else:
                        runs.append([p, i, i])

        def line(name, ps):
            n = sum(agg[("clean", "N", p)] for p in ps)
            d = sum(agg[("clean", "D", p)] for p in ps)
            s = sum(agg[("clean", "S", p)] for p in ps)
            kn = sum(agg[("clean", "keyN", p)] for p in ps)
            km = sum(agg[("clean", "keyM", p)] for p in ps)
            no = sum(agg[("ov", "N", p)] for p in ps)
            do = sum(agg[("ov", "D", p)] for p in ps)
            ins = sum(agg[("I", p)] for p in ps)
            pr(f"  {model:12} {name:16} clean tokens {n:4d}: Missing {100*d/n:4.1f}% Wrong {100*s/n:4.1f}% "
               f"(clean MER without insertions {100*(d+s)/n:4.1f}%), Key {100*km/kn if kn else 0:3.0f}% of {kn}; "
               f"overlapped tokens {no:3d} Missing {100*do/no if no else 0:4.1f}%; insertions {100*ins/(n+no):.1f}% of all")
        pr(f"\n{model}:")
        for p in ALL4:
            line(p, [p])
        line("ALL 4", ALL4)

    pr("\nsmall: most frequent substitutions on clean words (ref -> asr):")
    pr("  " + ", ".join(f"{a}->{b} {c}" for (a, b), c in subs.most_common(40)))
    pr("\nsmall: most frequent deleted clean words:")
    pr("  " + ", ".join(f"{a} {c}" for a, c in dels_clean.most_common(30)))
    pr("\nsmall: runs of 5 or more deleted tokens (piece, length, text):")
    long_runs = []
    for p, a, b in runs:
        if b - a + 1 >= 5:
            ref, flag, key, spk = piece_tokens(p)
            n_ov = sum(flag[a:b + 1])
            long_runs.append((p, b - a + 1, n_ov, " ".join(ref[a:b + 1])))
    for r in long_runs:
        pr(f"  {r[0]} {r[1]:3d} tokens, overlapped {r[2]:3d}: {r[3][:110]}")
    pr(f"  total {len(long_runs)} runs, {sum(r[1] for r in long_runs)} tokens, of which overlapped "
       f"{sum(r[2] for r in long_runs)}")

    pr("\nLoops and sound labels in the ASR texts:")
    for model in MODELS:
        for p in ALL4:
            txt = open(os.path.join(HERE, "results", "asr", model, p + ".txt")).read()
            labels = re.findall(r"[\(\[][^\)\]]*[\)\]]", txt)
            toks = st.tokens(txt)
            reps, k = [], 0
            while k < len(toks):
                m = k
                while m + 1 < len(toks) and toks[m + 1] == toks[k]:
                    m += 1
                if m - k + 1 >= 4:
                    reps.append(f"{toks[k]} x{m-k+1}")
                k = m + 1
            pr(f"  {model:12} {p:14} labels {len(labels):2d} {labels[:6]}  word repeated 4+ times: {reps}")
    pr("\nsmall: ASR segments with avgLogprob < -0.8 or compressionRatio > 2.4 (Whisper's usual thresholds):")
    for p in ALL4:
        segs = asr_segments(p)
        bad = [g for g in segs if g["avg"] < -0.8 or (g["comp"] or 0) > 2.4]
        temps = collections.Counter(g["temp"] for g in segs)
        pr(f"  {p}: {len(segs)} segments, flagged {len(bad)}, temperatures {dict(temps)}"
           + "".join(f"\n    {g['start']:.1f}-{g['end']:.1f} avg {g['avg']:.2f} comp {g['comp']:.2f}: {g['text'][:60]}" for g in bad))
    name = "target.txt" if len(sys.argv) <= 1 else "target_" + "_".join(MODELS) + ".txt"
    open(os.path.join(OUT, name), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
