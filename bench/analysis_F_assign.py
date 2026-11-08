"""Stage F: is the T1 'loss' partly the bench's own assignment of ASR words to reference sentences?

    python3 bench/analysis_F_assign.py      # needs bench/results/F/sentences.jsonl (run analysis_F_loss.py first)

Read-only. For every sentence of the 4 pieces it computes
  wer_E     : WER of the text stage E gave the translator (raw tokens, sentence order of translate_eval)
  wer_sort  : WER after re-assigning with sentences in time order and digits written as words
  heard     : share of the sentence's (normalised) words found in ASR segments that overlap its time
              (+-1 s); a bag-of-words upper bound for 'the recogniser heard it'
Writes bench/results/F/assign.txt and adds the fields to bench/results/F/sentences2.jsonl.
"""
import collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_text as st                       # noqa: E402
import translate_eval as te                   # noqa: E402
from analysis_F_loss import norm_tokens, asr_segments, PIECES, ALL4   # noqa: E402

OUT = os.path.join(HERE, "results", "F")


def wer(ref, hyp):
    if not ref:
        return 0.0
    return sum(op != "M" for op, _, _ in st.align(ref, hyp)) / len(ref)


def main():
    rows = [json.loads(l) for l in open(os.path.join(OUT, "sentences.jsonl"))]
    L = []
    for p in ALL4:
        s = [r for r in rows if r["piece"] == p]
        hyp_raw = open(os.path.join(HERE, "results", "asr", "small", p + ".txt")).read()
        # re-assign: time order, normalised words on both sides
        order = sorted(range(len(s)), key=lambda i: (s[i]["start"], s[i]["spk"]))
        hyp_words = " ".join(norm_tokens(hyp_raw)).split()
        texts = te.assign_asr([norm_tokens(s[i]["ref"]) for i in order], hyp_words)
        for k, i in enumerate(order):
            s[i]["asr_sort"] = texts[k]
            s[i]["wer_sort"] = wer(norm_tokens(s[i]["ref"]), texts[k].split())
            s[i]["wer_E"] = wer(st.tokens(s[i]["ref"]), st.tokens(s[i]["asr"]))
        segs = asr_segments(p)
        for r in s:
            ref = norm_tokens(r["ref"])
            pool = collections.Counter()
            for g in segs:
                if g["end"] >= r["start"] - 1 and g["start"] <= r["end"] + 1:
                    pool.update(norm_tokens(g["text"]))
            hit = 0
            for t in ref:
                if pool[t] > 0:
                    pool[t] -= 1
                    hit += 1
            r["heard"] = hit / len(ref) if ref else 0.0
    with open(os.path.join(OUT, "sentences2.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    pr = L.append
    for p in ALL4:
        s = [r for r in rows if r["piece"] == p]
        n = sum(r["n"] for r in s)
        e = sum(r["wer_E"] * r["n"] for r in s) / n
        o = sum(r["wer_sort"] * r["n"] for r in s) / n
        pr(f"{p}: word-weighted sentence WER, stage E assignment {100*e:.1f}%, time-order + digits {100*o:.1f}%")
    J = [r for r in rows if r["piece"] in PIECES and r["m1"] is not None and r["m0"] is not None]
    pr(f"\nJudged in both conditions (2 pieces): {len(J)} sentences")
    bad = [r for r in J if r["m1"] != "right"]
    pr(f"T1 not right: {len(bad)}")

    def why(r):
        if r["m0"] != "right":
            return "0 T0 also not right (translator/reference/judge)"
        if r["asr_empty"] and r["heard"] >= 0.6:
            return "1 E text empty, words heard nearby (assignment)"
        if r["asr_empty"]:
            return "2 E text empty, not heard"
        if r["wer_E"] > 0.5 and r["wer_sort"] <= 0.3:
            return "3 E text bad, re-assignment fixes it"
        if r["wer_E"] > 0.5 and r["heard"] >= 0.6:
            return "4 E text bad, words heard nearby (overlap order)"
        if r["wer_E"] > 0.2:
            return "5 E text has many ASR errors"
        if r["wer_E"] > 0:
            return "6 E text has few ASR errors"
        return "7 E text exact"
    c = collections.Counter(why(r) for r in bad)
    for k in sorted(c):
        sub = [r for r in bad if why(r) == k]
        pr(f"  {k:52} {c[k]:3d}  (backchannel {sum(r['backchannel'] for r in sub)}, clean {sum(r['n_overlap']==0 for r in sub)})")
    pr("\nSame for content sentences only:")
    badc = [r for r in bad if not r["backchannel"]]
    c = collections.Counter(why(r) for r in badc)
    for k in sorted(c):
        pr(f"  {k:52} {c[k]:3d}")
    pr("\nCases where the assignment is doubtful (classes 1, 3, 4):")
    for r in bad:
        if why(r)[0] in "134":
            pr(f"  {r['id']} {r['n']}w ov {r['n_overlap']} heard {r['heard']:.2f} wer_E {r['wer_E']:.2f} "
               f"wer_sort {r['wer_sort']:.2f} m1 {r['m1']}")
    open(os.path.join(OUT, "assign.txt"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
