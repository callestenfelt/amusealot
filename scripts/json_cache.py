"""Shared JSON cache helpers (ETag cache, GitHub seen-events cache).

save_json_cache writes atomically (temp file + os.replace) so a crash or
full disk mid-write can't leave a truncated file that a later run would
silently swallow into {} — wiping the accumulated state.
"""

import json
import os
import tempfile


def load_json_cache(path, label="cache"):
    """Load a JSON dict from path; missing or unreadable files yield {}."""
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load {label} ({path}): {e}")
    return {}


def save_json_cache(path, data, label="cache"):
    """Atomically write a JSON dict to path (temp file in the same dir + rename)."""
    try:
        fd, tmp = tempfile.mkstemp(
            dir=os.path.dirname(path) or ".",
            prefix=os.path.basename(path) + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        print(f"Warning: Could not save {label} ({path}): {e}")
