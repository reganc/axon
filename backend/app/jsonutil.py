"""jsonutil.py — lenient JSON extraction from LLM replies.

Models wrap JSON in code fences or surrounding prose; this pulls out the first
object/array and returns {} on failure. Shared by the companion agents and the
transcript miner (kept neutral so neither seam imports the other).
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("axon.jsonutil")

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARR = re.compile(r"\[.*\]", re.DOTALL)


def parse_json(text: str) -> dict | list:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in (_JSON_OBJ, _JSON_ARR):
        m = pattern.search(text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    log.warning("could not parse JSON from reply: %.120s", text)
    return {}
