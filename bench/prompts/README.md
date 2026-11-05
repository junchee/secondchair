# Prompts for the translation test (stage C, 2026-11-05)

Design: `notes/speech_test_design_2026-11-05.md` (sections 2a and 4). Each file holds the prompt below a `---` line; the text above it is for people. Placeholders are `{{name}}`; fill every one (empty string if there is nothing).

- `reference_translation.md`: writes the reference Korean for one AMI reference sentence, with the meeting description, a term list and the earlier sentences as context. Model: **Claude Opus**, temperature 0, run once per sentence and cached; the result is fixed for all later runs. Output: one JSON line `{"ko": "...", "kind": "content|fragment|backchannel"}`.
- `translation_judge.md`: judges one candidate Korean translation against the reference English and the reference Korean (GEMBA-MQM style, meaning only). Model: **Claude Sonnet**, temperature 0, for all repeated judging. **Haiku** only after it gives the same `meaning` as Sonnet on a checked sample (proposal: at least 90% of 100 sentences, and no critical error that Sonnet found missed). Output: one JSON line `{"meaning": "right|partly|wrong", "critical": [...], "errors": [{"type", "severity", "span", "note"}], "comment": "..."}`.
- The translators under test use Anne's own prompt (`translate.py`), not these files.

From the judge's output: `Meaning` = share of `right`; `Critical` = critical errors per 100 sentences; `T_err` = major + critical errors per 100 reference words, by type.

Parse both outputs with `json.loads` on the reply after stripping spaces; if that fails, cut from the first `{` to the last `}` and try once more; count a second failure as a failed call (retry once, then record it).

Jun's check of the judge: `bench/results/C/samples_for_jun.md` (local only: it holds AMI text).
