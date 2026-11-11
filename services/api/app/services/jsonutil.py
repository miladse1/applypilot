import json
from typing import Any


def dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
