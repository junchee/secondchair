"""Where Anne keeps the access key (an OpenRouter key Jun sends after payment).

The key is stored in the macOS Keychain (service "Anne OpenRouter key"), not in a text file. At start it is put in the
environment variable the rest of the program reads (OPENROUTER_API_KEY), unless that variable is already set (Jun's own
Mac keeps it in ~/.zshrc). `check` asks OpenRouter whether a key works (a free call: GET /api/v1/key).
"""
import json
import os
import re
import ssl
import subprocess
import urllib.request

try:
    import certifi
    _TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _TLS = ssl.create_default_context()

SERVICE = "Anne OpenRouter key"
ACCOUNT = "anne"
KEY_PATTERN = re.compile(r"^sk-or-[A-Za-z0-9_\-]{16,200}$")


def _read():
    try:
        done = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
                              capture_output=True, text=True, timeout=10)
        return done.stdout.strip() if done.returncode == 0 else ""
    except Exception:
        return ""


def load_into_env():
    """Use the Keychain key when no key is set in the environment. Returns True when a key is available."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        key = _read()
        if key:
            os.environ["OPENROUTER_API_KEY"] = key
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def looks_valid(key):
    return bool(KEY_PATTERN.match(key or ""))


def check(key, timeout=10):
    """Ask OpenRouter about this key. Returns {"ok": True, "remaining": ..., "limit": ...} or {"ok": False, "reason": ...}."""
    request = urllib.request.Request("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}", "User-Agent": "Anne"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_TLS) as response:
            data = json.loads(response.read()).get("data", {})
        return {"ok": True, "remaining": data.get("limit_remaining"), "limit": data.get("limit")}
    except urllib.error.HTTPError as error:
        return {"ok": False, "reason": "rejected" if error.code in (401, 403) else f"http {error.code}"}
    except Exception as error:
        return {"ok": False, "reason": "network"}


def save(key):
    """Keep the key in the Keychain (replacing an older one) and use it from now on."""
    subprocess.run(["security", "add-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w", key, "-U"],
                   check=True, capture_output=True, timeout=10)
    os.environ["OPENROUTER_API_KEY"] = key
