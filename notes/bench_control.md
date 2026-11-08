# Control for the automatic test (Jun edits this on the GitHub phone app; Claude reads it after each `git pull`)

Edit on branch `bench-auto`, keep the format `key: value` (one per line, nothing else on the line).
Claude changes only the `status:` lines. Everything else is Jun's.

## Jun's switches
stop: no
go_until: A
ok_B_download: no
ok_C_samples: no
ok_F_decision: no
ok_L_decision: no
ok_capture_check: no
ok_M_apply: no
budget_usd_per_batch: 5
note:

How to read it:
- `stop: yes` = finish the call in progress, write the report, then do nothing until it says `no`.
- `go_until: X` = run stages up to and including X (A..M), then wait. Stages with an `ok_` switch also wait for `yes`.
- `ok_...: yes` = the approval named in `notes/bench_runbook_2026-11-05.md`. Never set by Claude.
- `budget_usd_per_batch` = hard limit for one paid batch; a batch whose estimate is higher is not started.
- `note:` = a free sentence for Claude to read at the next stage.

## Claude's status (updated by Claude; one line each)
status_stage: F done (report bench/reports/F.md)
status_waiting_for: Jun: ok_F_decision and go_until; next work in notes/bench_handover_2026-11-08.md (bench fix, subagent judging, free ASR tests)
status_updated: 2026-11-08
