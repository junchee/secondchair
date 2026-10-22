# Translation model comparison (2026-10-22)

Which model translates the bubbles (English -> Korean, one request per bubble, newest text only).
All three were accepted under zero data retention (`provider: {zdr: true, data_collection: deny}`).

## Speed
Test: 6 sentences, streamed, from `scratchpad` benchmark (real OpenRouter calls).

| Model | First piece | Complete sentence |
|---|---|---|
| qwen/qwen3.5-9b | 0.65 s | 0.89 s |
| anthropic/claude-haiku-5.5 | 0.55 s | 0.73 s |
| deepseek/deepseek-v4.1-flash-1017 | 0.23 s | 0.38 s |
| deepseek/deepseek-v4-flash | 0.55 s | 0.89 s |

Live runs (Jun's logs, a BBC podcast, Mac busy with Whisper drafts), time per bubble translation:
- DeepSeek: mostly 0.2-0.5 s, one 1.9 s; nothing waiting.
- Haiku: 0.3-1.9 s, usually 0.6-1.2 s; nothing waiting.
- Qwen 9b: 0.9-2.1 s; the second and later versions of a long bubble took 2.1 s; nothing waiting.

## Quality (read from the logs)
- DeepSeek: clean; no commentary in the output.
- Haiku: one version printed a preface ("이 줄을 번역합니다. 저자 이름과 책 제목은 그대로 둡니다.") before the translation; adds English in brackets ("교수, 대학교 조직행동학과 (University College 소속)"); fragments joined into odd sentences ("오신 것을 유튜브에서 환영합니다").
- Qwen 9b: fine, but leaves some English words untranslated ("backlog").
- All three rewrite the Korean of a growing bubble from scratch each time, so earlier sentences change wording between versions.

## Decision and open points
- DeepSeek only (Jun, 2026-10-22); the selector in Settings was removed.
- To do: give the previous Korean to the model as a reference ("keep the earlier part, translate only the new part") to make growing bubbles stable.
- Jun said he could not tell the translation quality apart in plain reading; speed and the points above decided it.
- Whisper mishears names ("matter" for Meta): a terms dictionary would help (not built).
