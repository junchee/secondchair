"""Which model does which job (translate, typed, ask, summary, digest, recheck), best first.

The lists are in config/models.json. Anne reads that file from GitHub when it starts (and every 6 hours), keeps
the last good copy next to user_settings.json, and falls back to the lists below when there is nothing else.
So a model that is renamed or taken down can be replaced for everyone by changing one file and pushing it.
Every refresh also asks OpenRouter's public list (no key needed) which models still exist: a model that is gone
is skipped automatically, and the program logs it ("[models] ..."). Nothing is shown to the user.
"""
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.request

import prefs

try:
    import certifi
    _TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _TLS = ssl.create_default_context()

REMOTE_URL = "https://raw.githubusercontent.com/junchee/secondchair/main/config/models.json"
MODELS_URL = "https://openrouter.ai/api/v1/models"
REFRESH_SECONDS = 6 * 3600
ID_PATTERN = re.compile(r"^[~A-Za-z0-9._\-/:]{3,80}$")

DEFAULTS = {
    "translate": ["deepseek/deepseek-v4.1-flash-1017", "qwen/qwen3.5-9b"],
    "typed": ["deepseek/deepseek-v4.1-flash-1017", "qwen/qwen3.5-9b"],
    "ask": ["deepseek/deepseek-v4.1-flash-1017", "qwen/qwen3.5-35b-a3b"],
    "summary": ["deepseek/deepseek-v4.1-flash-1017", "qwen/qwen3.5-35b-a3b"],
    "digest": ["anthropic/claude-haiku-5.5", "deepseek/deepseek-v4.1-flash-1017"],
    "recheck": ["qwen/qwen3.5-35b-a3b", "deepseek/deepseek-v4.1-flash-1017"],
}

_lock = threading.Lock()
_roles = {role: list(ids) for role, ids in DEFAULTS.items()}
_exist = None          # set of model ids OpenRouter lists now (None = not checked yet)
_missing = {}          # role -> ids from the lists that OpenRouter no longer lists
_started = False


def _cache_path():
    return os.path.join(os.path.dirname(prefs.PATH), "models_cache.json")


def clean(config):
    """The roles of a config dict if it is well formed (known roles, 1-4 plausible ids each), else {}."""
    roles = config.get("roles") if isinstance(config, dict) else None
    if not isinstance(roles, dict):
        return {}
    out = {}
    for role, ids in roles.items():
        if role in DEFAULTS and isinstance(ids, list) and 1 <= len(ids) <= 4 and all(isinstance(i, str) and ID_PATTERN.match(i) for i in ids):
            out[role] = list(ids)
    return out


def ordered(role):
    """The model ids for this job, best first, without the ones OpenRouter no longer lists (all of them if that would leave none)."""
    with _lock:
        ids = list(_roles.get(role) or DEFAULTS[role])
        alive = [i for i in ids if _exist is None or i in _exist or i.startswith("~")]
    return alive or ids


def first(role):
    return ordered(role)[0]


def second(role):
    ids = ordered(role)
    return ids[1] if len(ids) > 1 else ids[0]


def status():
    with _lock:
        return {"missing": {role: ids for role, ids in _missing.items() if ids}, "checked": _exist is not None}


def _fetch(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "Anne"})
    with urllib.request.urlopen(request, timeout=timeout, context=_TLS) as response:
        return json.loads(response.read())


def refresh():
    """One round: the config from GitHub (else the cached copy), then which models still exist. Never raises."""
    global _roles, _exist, _missing
    config = {}
    try:
        config = clean(_fetch(REMOTE_URL, 4))
        if config:
            with open(_cache_path(), "w", encoding="utf-8") as f:
                json.dump({"roles": config}, f)
    except Exception:
        pass
    if not config:
        try:
            with open(_cache_path(), encoding="utf-8") as f:
                config = clean(json.load(f))
        except Exception:
            config = {}
    exist = None
    try:
        exist = {m["id"] for m in _fetch(MODELS_URL, 8).get("data", []) if m.get("id")}
    except Exception:
        pass
    with _lock:
        _roles = {role: list(DEFAULTS[role]) for role in DEFAULTS}
        _roles.update(config)
        _exist = exist if exist else _exist
        _missing = {role: [i for i in ids if _exist is not None and i not in _exist and not i.startswith("~")] for role, ids in _roles.items()}
        gone = {i for ids in _missing.values() for i in ids}
    for model in sorted(gone):
        print(f"[models] {model} is no longer listed by OpenRouter: the next model in its list is used", file=sys.stderr, flush=True)


def start():
    """Refresh now (in the background) and every 6 hours."""
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            refresh()
            time.sleep(REFRESH_SECONDS)

    threading.Thread(target=loop, daemon=True).start()
