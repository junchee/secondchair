# Stage B report (2026-11-05)

Ran by a Haiku subagent. Jun approved the download in chat; the switch `ok_B_download` in the control file is still `no` (Claude does not set it).

## What ran
- Downloaded into `bench/audio/ami/` (git ignores it): ES2004a, IS1009a, TS3003a `Mix-Headset.wav` and `ami_public_manual_1.6.2.zip`. Total about 131 MB.
- Unzipped the annotations to `bench/audio/ami/annotations/`.
- `python3 bench/prepare_ami.py --ami-dir bench/audio/ami --meeting ES2004a --meeting IS1009a --meeting TS3003a`: exit 0, 12 pieces.
- `cd bench && python3 -m unittest test_score_text test_prepare_ami`: 27 tests, OK (only ResourceWarnings about unclosed files in `test_prepare_ami.py`).

## Checks
- Licence: `LICENCE.txt` in the zip says CC BY 4.0. The readme says the annotations are release 1.7 (16 June 2014), although the file is named 1.6.2. Credit AMI in any write-up.
- XML layout matches what stage A assumed: `<w nite:id starttime endtime>`, punctuation as `punc="true"`, namespace `nite:`. The parser needed no change.
- Audio: 16 kHz, mono, 16-bit. ES2004a 1049.4 s, IS1009a 838.8 s, TS3003a 1505.6 s.
- Sizes: ES2004a 32.0 MB, IS1009a 25.6 MB, TS3003a 46.0 MB, zip 21.8 MB.

## Pieces (manifest)
| piece | start | end | words | sent | key |
|---|---|---|---|---|---|
| ES2004a.cut01 | 11.0 | 319.1 | 391 | 49 | 16 |
| ES2004a.cut02 | 315.9 | 624.3 | 720 | 90 | 22 |
| ES2004a.cut03 | 617.5 | 934.9 | 993 | 80 | 40 |
| ES2004a.cut04 | 923.6 | 1048.5 | 385 | 48 | 14 |
| IS1009a.cut01 | 55.0 | 358.9 | 543 | 87 | 33 |
| IS1009a.cut02 | 357.4 | 671.6 | 925 | 99 | 31 |
| IS1009a.cut03 | 652.9 | 805.7 | 410 | 60 | 20 |
| TS3003a.cut01 | 13.5 | 321.9 | 570 | 80 | 48 |
| TS3003a.cut02 | 321.9 | 630.7 | 574 | 73 | 7 |
| TS3003a.cut03 | 630.7 | 967.5 | 251 | 48 | 12 |
| TS3003a.cut04 | 968.5 | 1280.3 | 513 | 84 | 25 |
| TS3003a.cut05 | 1267.8 | 1475.5 | 452 | 73 | 16 |

## Things to look at later
- Cuts overlap by a few seconds (for example ES2004a.cut01 ends at 319.1 and cut02 starts at 315.9) because speakers overlap and words are ordered by start time. Cut the audio by each piece's own start and end; do not assume the pieces tile.
- Word counts per piece vary from 251 to 993 words. The key-item count is very uneven (TS3003a.cut02: 7 words in 574). The key items are a heuristic; check them before `Key` is trusted.
- The text of ES2004a.cut01 starts with chatter ("Are we we're not allowed to dim the lights..."): the first minutes are setup talk, not meeting content.

## Next
Stage C (Opus): prompts for the reference translation and the translation judge, plus 20 samples for Jun. It waits for `go_until: C` and `ok_C_samples: yes` before the samples are used.
