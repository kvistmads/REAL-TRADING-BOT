"""Skriver godkendte/auto-godkendte parameter-ændringer til config.yaml.

Guardrails (PRD Opgave 5):
- Tager ALTID backup først: config.yaml.bak.<timestamp> (aldrig destruktivt).
- Fuld audit-trail til reflection/audit.log (og DB via obs.auto_applied + Observation-rækken).
- Beskyttede parametre og for store ændringer stoppes af confidence_gate FØR vi når hertil;
  applier'en selv antager at gaten har godkendt ændringen.

Config-konvention for hvor en parameter bor:
- strategy_id sat  → strategies.params.<strategy_id>.<parameter>
- strategy_id None → strategies.<parameter>   (fx det globale min_confidence)
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_AUDIT_PATH = "reflection/audit.log"


class ParameterApplier:
    def __init__(self, audit_path: str = DEFAULT_AUDIT_PATH):
        self.audit_path = audit_path

    def apply(
        self,
        obs,
        cfg_path: str = "config.yaml",
        notify: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """Skriv obs.suggested_value til config.yaml. Returnér audit-record.

        Muterer obs.auto_applied=True — caller er ansvarlig for at committe DB'en.
        """
        backup_path = f"{cfg_path}.bak.{int(time.time())}"
        shutil.copy(cfg_path, backup_path)

        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}

        old_value = self._get_nested(cfg, obs.strategy_id, obs.parameter)
        self._set_nested(cfg, obs.strategy_id, obs.parameter, obs.suggested_value)

        with open(cfg_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        obs.auto_applied = True

        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "obs_id": getattr(obs, "id", None),
            "strategy_id": obs.strategy_id,
            "parameter": obs.parameter,
            "old_value": old_value,
            "new_value": obs.suggested_value,
            "evidence": obs.evidence,
            "confidence": obs.confidence,
            "backup": backup_path,
        }
        self._write_audit(record)

        msg = (
            f"⚙️ AUTO-APPLIED: {obs.strategy_id or 'global'} › {obs.parameter}: "
            f"{old_value} → {obs.suggested_value} (conf={obs.confidence:.2f})"
        )
        logger.info(msg)
        if notify is not None:
            try:
                notify(msg)
            except Exception as e:  # notifikation må aldrig vælte en apply
                logger.warning("Kunne ikke notificere om auto-apply: %s", e)

        return record

    def _write_audit(self, record: dict) -> None:
        path = Path(self.audit_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    @staticmethod
    def _target_container(cfg: dict, strategy_id: Optional[str], create: bool) -> dict:
        """Find (eller opret) dict'en som parameteren skal sættes i."""
        strategies = cfg.setdefault("strategies", {}) if create else cfg.get("strategies", {})
        if strategy_id is None:
            return strategies
        if create:
            params = strategies.setdefault("params", {})
            return params.setdefault(strategy_id, {})
        return (strategies.get("params", {}) or {}).get(strategy_id, {})

    def _set_nested(self, cfg: dict, strategy_id: Optional[str], parameter: str, value: Any) -> None:
        container = self._target_container(cfg, strategy_id, create=True)
        container[parameter] = value

    def _get_nested(self, cfg: dict, strategy_id: Optional[str], parameter: str) -> Any:
        container = self._target_container(cfg, strategy_id, create=False)
        return container.get(parameter) if isinstance(container, dict) else None
