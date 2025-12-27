from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable


def _sha256_bytes(chunks: Iterable[bytes]) -> str:
    h = hashlib.sha256()
    for chunk in chunks:
        h.update(chunk)
    return h.hexdigest()


def config_fingerprint(paths: Iterable[Path]) -> str:
    """Compute a deterministic fingerprint over config file contents."""

    parts: list[bytes] = []
    for p in sorted((Path(x) for x in paths), key=lambda x: x.as_posix()):
        parts.append(p.as_posix().encode("utf-8"))
        parts.append(b"\n")
        parts.append(p.read_bytes())
        parts.append(b"\n")
    return _sha256_bytes(parts)


def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "YAML config requires PyYAML. Install it: pip install pyyaml"
        ) from e

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must be a mapping/object: {path}")
    return data


def load_frozen_configs(*, config_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load the frozen Phase-3 config set."""

    config_dir = Path(config_dir)
    signals_path = config_dir / "signals.yaml"
    windowing_path = config_dir / "windowing.yaml"
    rules_path = config_dir / "rules.yaml"

    for p in (signals_path, windowing_path, rules_path):
        if not p.exists():
            raise FileNotFoundError(f"Missing required config file: {p}")

    return {
        "signals": load_yaml(signals_path),
        "windowing": load_yaml(windowing_path),
        "rules": load_yaml(rules_path),
        "fingerprint": {
            "sha256": config_fingerprint([signals_path, windowing_path, rules_path]),
            "paths": [
                str(signals_path.as_posix()),
                str(windowing_path.as_posix()),
                str(rules_path.as_posix()),
            ],
        },
    }
