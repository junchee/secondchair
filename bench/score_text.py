"""Text scoring for the speech test (stage A of notes/bench_runbook_2026-11-05.md).

Compares a hypothesis text (what Anne or Whisper wrote) with a reference text.
Korean is counted by character, English by word (as MER in the HiKE paper);
mixed text works too: Latin/digit runs are words, each Hangul syllable is one token.

    from score_text import tokens, tokens_with_ends, score
    ref, ref_ends = tokens_with_ends(ref_text)
    hyp, hyp_ends = tokens_with_ends(hyp_text)
    r = score(ref, hyp, key=[3, 17], ref_ends=ref_ends, hyp_ends=hyp_ends)

Numbers returned (all as fractions of the reference length N, 0..1+):
    Missing  = deletions / N          Invented = insertions / N
    Wrong    = substitutions / N      MER      = the three together
    Key      = share of the marked key items (indexes into ref) that are heard right
    SentF1   = F1 of sentence ends against the reference (tolerance `tol` tokens)

The alignment is a full table (len(ref) * len(hyp) cells): use it on pieces of a few
minutes (about 1000 words), not on a whole 40-minute meeting.

    python bench/score_text.py REF.txt HYP.txt     # quick look at two text files
    python -m unittest bench/test_score_text.py    # tests
"""

import re
import sys

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[가-힣]")
_SENT_END = re.compile(r"[.?!]+(?=\s|$)")


def tokens(text):
    """Lower-case tokens: Latin/digit words (with an inner apostrophe) and single Hangul syllables."""
    return _TOKEN.findall(text.lower().replace("’", "'"))


def tokens_with_ends(text):
    """Tokens plus the index of the last token of each sentence (split at . ? !)."""
    words, ends = [], []
    start = 0
    for m in _SENT_END.finditer(text):
        chunk = tokens(text[start:m.start()])
        start = m.end()
        if chunk:
            words.extend(chunk)
            ends.append(len(words) - 1)
    tail = tokens(text[start:])
    if tail:
        words.extend(tail)
        ends.append(len(words) - 1)
    return words, ends


def align(ref, hyp):
    """Minimum-edit alignment. Returns a list of (op, ref_index, hyp_index):
    op is 'M' match, 'S' substitution, 'D' deletion (ref word missing), 'I' insertion
    (extra hyp word); the index of the side that has no word is None."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i
    for j in range(1, m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        ri = ref[i - 1]
        di, dp = d[i], d[i - 1]
        for j in range(1, m + 1):
            di[j] = min(dp[j - 1] + (ri != hyp[j - 1]), dp[j] + 1, di[j - 1] + 1)
    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("M" if ref[i - 1] == hyp[j - 1] else "S", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append(("D", i - 1, None))
            i -= 1
        else:
            ops.append(("I", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def _sentence_f1(ops, n_ref, n_hyp, ref_ends, hyp_ends, tol):
    """Sentence ends are compared in reference positions (number of reference words before the end)."""
    ref_pos = {e + 1 for e in ref_ends if 0 < e + 1 < n_ref}
    consumed = {}                 # hyp index -> reference words consumed once that hyp word is done
    r = 0
    for op, ri, hj in ops:
        if ri is not None:
            r += 1
        if hj is not None:
            consumed[hj] = r
    hyp_pos = {consumed[e] for e in hyp_ends if e in consumed and 0 < e + 1 < n_hyp and 0 < consumed[e] < n_ref}
    if not ref_pos and not hyp_pos:
        return 1.0
    if not ref_pos or not hyp_pos:
        return 0.0
    free = sorted(ref_pos)
    hit = 0
    for h in sorted(hyp_pos):
        best = min(free, key=lambda x: abs(x - h), default=None)
        if best is not None and abs(best - h) <= tol:
            free.remove(best)
            hit += 1
    p, rc = hit / len(hyp_pos), hit / len(ref_pos)
    return 0.0 if hit == 0 else 2 * p * rc / (p + rc)


def score(ref, hyp, key=None, ref_ends=None, hyp_ends=None, tol=1):
    """ref, hyp: token lists. key: indexes into ref of the marked key items.
    ref_ends, hyp_ends: indexes of the last token of each sentence (see tokens_with_ends)."""
    ops = align(ref, hyp)
    n = len(ref)
    s = sum(op == "S" for op, _, _ in ops)
    dele = sum(op == "D" for op, _, _ in ops)
    ins = sum(op == "I" for op, _, _ in ops)
    div = max(1, n)
    out = {
        "N": n, "S": s, "D": dele, "I": ins,
        "MER": (s + dele + ins) / div,
        "Missing": dele / div,
        "Invented": ins / div,
        "Wrong": s / div,
        "Key": None,
        "SentF1": None,
    }
    if key:
        matched = {ri for op, ri, _ in ops if op == "M"}
        out["Key"] = sum(k in matched for k in key) / len(key)
    if ref_ends is not None and hyp_ends is not None:
        out["SentF1"] = _sentence_f1(ops, n, len(hyp), ref_ends, hyp_ends, tol)
    return out


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    ref, ref_ends = tokens_with_ends(open(sys.argv[1], encoding="utf-8").read())
    hyp, hyp_ends = tokens_with_ends(open(sys.argv[2], encoding="utf-8").read())
    for k, v in score(ref, hyp, ref_ends=ref_ends, hyp_ends=hyp_ends).items():
        print(f"{k:9} {v if v is None or isinstance(v, int) else round(v, 4)}")


if __name__ == "__main__":
    main()
