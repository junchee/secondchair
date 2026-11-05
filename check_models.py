"""Checks that the models Anne uses still exist and answer. Run it by hand or on a schedule on your own Mac:

    .venv/bin/python check_models.py          # which models are gone
    .venv/bin/python check_models.py --ping   # also asks each first-choice model one tiny question (costs almost nothing)

Exit code 1 and a macOS notification when something needs attention; the fix is to change config/models.json and push it.
"""
import subprocess
import sys

import models
import translate


def notify(text):
    subprocess.run(["osascript", "-e", f'display notification "{text}" with title "Anne: model check"'], check=False)


def main():
    models.refresh()
    state = models.status()
    problems = []
    if not state["checked"]:
        problems.append("OpenRouter's model list could not be read (offline?)")
    for role, ids in state["missing"].items():
        problems.append(f"{role}: no longer listed: {', '.join(ids)}")
    if "--ping" in sys.argv:
        for role in models.DEFAULTS:
            model = models.first(role)
            try:
                reply = translate.Client(timeout=20).post({
                    "model": model, "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 5, "reasoning": {"enabled": False},
                    "provider": {"zdr": True, "data_collection": "deny"}})
                print(f"ok    {role:9s} {model}: {reply.strip()[:20]!r}")
            except Exception as error:
                problems.append(f"{role}: {model} did not answer ({str(error)[:80]})")
    for role in models.DEFAULTS:
        print(f"{role:9s} {' -> '.join(models.ordered(role))}")
    if problems:
        print("\nNEEDS ATTENTION:\n  " + "\n  ".join(problems))
        notify(problems[0][:100])
        sys.exit(1)
    print("\nAll models are listed.")


if __name__ == "__main__":
    main()
