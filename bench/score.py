"""Score one or more streaming results (bench/results/*.jsonl) side by side.

    python bench/score.py RESULT.jsonl [RESULT2.jsonl ...] [--ref REF.txt]

Per engine:
  shown delay     = when the word first appeared (grey) - when it was spoken (its audio end)
  confirmed delay = when it became final (white)       - when it was spoken
  WER             = word error rate against --ref (lower case, punctuation ignored)
  load            = compute time / audio length (1.0 would mean the Mac is busy all the time)
"""

import argparse
import json
import re


def words_of(text):
    return [w for w in re.sub(r"[^\w' ]", " ", text.lower().replace("’", "'")).split() if w]


def wer(ref, hyp):
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)] / max(1, len(ref))


def pct(values, q):
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("results", nargs="+")
    p.add_argument("--ref")
    args = p.parse_args()
    ref = words_of(open(args.ref).read()) if args.ref else None

    print(f"\n{'engine':38} {'shown p50/p90':>14} {'confirmed p50/p90':>18} {'WER':>6} {'load':>5} {'mem MB':>7}")
    for path in args.results:
        lines = [json.loads(l) for l in open(path)]
        meta = next((l for l in lines if l.get("meta")), {})
        ws = [l for l in lines if not l.get("meta")]
        shown = [w["shown"] - w["audio_end"] for w in ws]
        conf = [w["confirmed"] - w["audio_end"] for w in ws]
        hyp = words_of(" ".join(w["word"] for w in ws))
        e = f"{wer(ref, hyp) * 100:5.1f}%" if ref else "   -  "
        load = meta.get("compute_s", float("nan")) / max(1e-9, meta.get("duration", 0))
        print(f"{meta.get('engine', path)[:38]:38} {pct(shown, .5):6.2f}/{pct(shown, .9):5.2f}s "
              f"{pct(conf, .5):8.2f}/{pct(conf, .9):5.2f}s {e:>6} {load:5.2f} {meta.get('peak_mem_mb', 0):7.0f}")
    print()


if __name__ == "__main__":
    main()
