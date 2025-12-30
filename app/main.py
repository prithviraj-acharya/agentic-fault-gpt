from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, load_settings
from app.kafka_consumers import KafkaIngest
from app.stores import (
    TelemetryStore,
    WindowStore,
    compute_active_incidents,
    min_window_item,
)
from app.utils import isoformat_z

_SIGNAL_ALIASES: Dict[str, List[str]] = {
    # Canonical name -> possible raw telemetry keys
    "sat": ["sat", "sat_c", "sa_temp", "sa_temp_c"],
    "rat": ["rat", "rat_c", "ra_temp", "ra_temp_c", "avg_zone_temp", "avg_zone_temp_c"],
    "valve_pos": ["valve_pos", "cc_valve", "cc_valve_pos", "cc_valve_pct"],
    "fan_speed": ["fan_speed", "sa_fan_speed", "sa_fan_speed_pct", "fan_speed_pct"],
    "damper_pos": ["damper_pos", "oa_damper", "oa_damper_pos", "oa_damper_pct"],
    "oat": [
        "oat",
        "oat_c",
        "oa_temp",
        "oa_temp_c",
        "outdoor_air_temp",
        "outdoor_air_temp_c",
    ],
}


def _pick_signal_value(values: Dict[str, Any], canonical: str) -> Any:
    for key in _SIGNAL_ALIASES.get(canonical, [canonical]):
        if key in values:
            return values.get(key)
    return None


def _resolve_signal_key(known_keys: List[str], requested: str) -> Optional[str]:
    known = set(known_keys)
    for key in _SIGNAL_ALIASES.get(requested, [requested]):
        if key in known:
            return key
    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _pick_default_ahu_id(
    telemetry_store: TelemetryStore, window_store: WindowStore
) -> Optional[str]:
    tel = telemetry_store.ahus()
    if tel:
        return sorted(tel)[0]
    win = window_store.ahus()
    return sorted(win)[0] if win else None


def _max_window_severity(w: Dict[str, Any]) -> int:
    anomalies_obj = w.get("anomalies")
    anomalies: List[Any] = anomalies_obj if isinstance(anomalies_obj, list) else []
    max_sev = 0
    for a in anomalies:
        if not isinstance(a, dict):
            continue
        # store already uses string severities like low/medium/high; map to int
        s = str(a.get("severity") or "").strip().lower()
        if s == "high":
            max_sev = max(max_sev, 3)
        elif s == "medium":
            max_sev = max(max_sev, 2)
        elif s == "low":
            max_sev = max(max_sev, 1)
    return int(max_sev)


def create_app() -> FastAPI:
    settings = load_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO)
    )
    logger = logging.getLogger("dashboard-api")

    app = FastAPI(title="Agentic Fault GPT Dashboard API")

    if settings.cors_origins == ["*"]:
        allow_origins = ["*"]
        allow_credentials = False
    else:
        allow_origins = settings.cors_origins
        allow_credentials = True

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    telemetry_store = TelemetryStore(
        retention_mins=settings.telemetry_retention_mins, max_points=settings.max_points
    )
    window_store = WindowStore(maxlen=settings.windows_maxlen)

    ingest = KafkaIngest(
        settings=settings,
        telemetry_store=telemetry_store,
        window_store=window_store,
    )

    app.state.settings = settings
    app.state.telemetry_store = telemetry_store
    app.state.window_store = window_store
    app.state.ingest = ingest

    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> Dict[str, Any]:
        last_ts = telemetry_store.last_ts()
        last_win = window_store.last_window_end()
        ahus = sorted(set(telemetry_store.ahus()) | set(window_store.ahus()))
        return {
            "status": "ok",
            "telemetry": {
                "last_ts": isoformat_z(last_ts) if last_ts else None,
                "points_cached_total": telemetry_store.points_cached_total(),
            },
            "windows": {
                "last_window_end": isoformat_z(last_win) if last_win else None,
                "windows_cached_total": window_store.windows_cached_total(),
            },
            "ahus": ahus,
        }

    @router.get("/ahus")
    def list_ahus() -> Dict[str, Any]:
        items = sorted(set(telemetry_store.ahus()) | set(window_store.ahus()))
        return {"items": items}

    @router.get("/live/overview")
    def live_overview(
        ahu_id: Optional[str] = Query(None, min_length=1)
    ) -> Dict[str, Any]:
        # Contract used by the Vite dashboard:
        # {system_online,last_updated,sat,rat,valve_pos,fan_speed,diagnosis,confidence,severity,active_window_id}
        resolved_ahu = (
            str(ahu_id)
            if ahu_id
            else _pick_default_ahu_id(telemetry_store, window_store)
        )
        if not resolved_ahu:
            return {
                "system_online": False,
                "last_updated": None,
                "sat": None,
                "rat": None,
                "valve_pos": None,
                "fan_speed": None,
                "diagnosis": None,
                "confidence": None,
                "severity": None,
                "active_window_id": None,
            }

        latest_tel = telemetry_store.latest(resolved_ahu)
        last_updated: Optional[str] = None
        system_online = False

        sat = rat = valve_pos = fan_speed = None
        if latest_tel is not None:
            ts, values = latest_tel
            last_updated = isoformat_z(ts)
            age = (_now_utc() - ts).total_seconds()
            system_online = age <= float(settings.online_threshold_secs)

            sat = _pick_signal_value(values, "sat")
            rat = _pick_signal_value(values, "rat")
            valve_pos = _pick_signal_value(values, "valve_pos")
            fan_speed = _pick_signal_value(values, "fan_speed")

        latest_win_items = window_store.latest_min_items(resolved_ahu, limit=1)
        latest_win_min = latest_win_items[0] if latest_win_items else None

        diagnosis = None
        severity = None
        active_window_id = None
        if latest_win_min is not None:
            active_window_id = str(latest_win_min.get("window_id") or "") or None
            diagnosis = str(latest_win_min.get("text_summary") or "") or None
            severity = int(latest_win_min.get("max_severity") or 0)

        return {
            "system_online": bool(system_online),
            "last_updated": last_updated,
            "sat": float(sat) if isinstance(sat, (int, float)) else None,
            "rat": float(rat) if isinstance(rat, (int, float)) else None,
            "valve_pos": (
                float(valve_pos) if isinstance(valve_pos, (int, float)) else None
            ),
            "fan_speed": (
                float(fan_speed) if isinstance(fan_speed, (int, float)) else None
            ),
            "diagnosis": diagnosis,
            "confidence": None,
            "severity": severity,
            "active_window_id": active_window_id,
        }

    @router.get("/live/timeseries")
    def live_timeseries(
        ahu_id: Optional[str] = Query(None, min_length=1),
        mins: int = Query(30, ge=1),
        signals: str = Query(""),
    ) -> Dict[str, Any]:
        resolved_ahu = (
            str(ahu_id)
            if ahu_id
            else _pick_default_ahu_id(telemetry_store, window_store)
        )
        if not resolved_ahu:
            return {
                "from": None,
                "to": None,
                "signals": [],
                "points": [],
            }

        mins_capped = min(int(mins), int(settings.max_mins))
        to_ts = _now_utc()
        from_ts = to_ts - timedelta(minutes=mins_capped)

        # If we're not receiving "live" telemetry (e.g., replayed historical Kafka data),
        # anchor the window at the latest available telemetry timestamp so charts still populate.
        latest_for_window = telemetry_store.latest(resolved_ahu)
        if latest_for_window is not None:
            latest_ts = latest_for_window[0]
            if latest_ts < from_ts:
                to_ts = latest_ts
                from_ts = to_ts - timedelta(minutes=mins_capped)

        requested = [s.strip() for s in signals.split(",") if s.strip()]
        # Ignore unknown signals by intersecting with latest values keys (best effort)
        latest = telemetry_store.latest(resolved_ahu)
        if latest is None:
            known_signals: List[str] = []
        else:
            known_signals = sorted(set(latest[1].keys()))

        # Allow dashboard canonical names (sat,rat,valve_pos,fan_speed) to map to simulator keys.
        resolved: List[tuple[str, str]] = []  # (requested_name, actual_key)
        for req in requested:
            actual = _resolve_signal_key(known_signals, req)
            if actual is not None:
                resolved.append((req, actual))

        actual_keys = [a for _, a in resolved]
        points = telemetry_store.range(
            resolved_ahu, from_ts=from_ts, to_ts=to_ts, signals=actual_keys
        )

        if resolved:
            remapped: List[Dict[str, Any]] = []
            for p in points:
                row: Dict[str, Any] = {"ts": p.get("ts")}
                for req, actual in resolved:
                    if actual in p:
                        row[req] = p.get(actual)
                remapped.append(row)
            points = remapped

        return {
            "from": isoformat_z(from_ts),
            "to": isoformat_z(to_ts),
            "signals": [req for req, _ in resolved],
            "points": points,
        }

    @router.get("/live/last")
    def live_last(
        ahu_id: Optional[str] = Query(None, min_length=1),
        limit: int = Query(30, ge=1),
        signals: str = Query("sat,rat,oat,valve_pos,fan_speed"),
    ) -> Dict[str, Any]:
        resolved_ahu = (
            str(ahu_id)
            if ahu_id
            else _pick_default_ahu_id(telemetry_store, window_store)
        )
        if not resolved_ahu:
            return {
                "system_online": False,
                "last_updated": None,
                "signals": [],
                "points": [],
            }

        # Resolve requested canonical names against whatever keys we currently have.
        requested = [s.strip() for s in str(signals).split(",") if s.strip()]
        latest = telemetry_store.latest(resolved_ahu)
        if latest is None:
            return {
                "system_online": False,
                "last_updated": None,
                "signals": [],
                "points": [],
            }

        latest_ts, latest_vals = latest
        known_signals = sorted(set(latest_vals.keys()))

        resolved: List[tuple[str, str]] = []  # (requested_name, actual_key)
        for req in requested:
            actual = _resolve_signal_key(known_signals, req)
            if actual is not None:
                resolved.append((req, actual))

        # Pull last N points using actual keys, then remap to requested canonical names.
        lim = min(int(limit), int(settings.max_points))
        actual_keys = [a for _, a in resolved]
        raw_points = telemetry_store.last_n(
            resolved_ahu, limit=lim, signals=actual_keys
        )

        points: List[Dict[str, Any]] = []
        for p in raw_points:
            row: Dict[str, Any] = {"ts": p.get("ts")}
            for req, actual in resolved:
                if actual in p:
                    row[req] = p.get(actual)
            points.append(row)

        age = (_now_utc() - latest_ts).total_seconds()
        system_online = age <= float(settings.online_threshold_secs)

        return {
            "system_online": bool(system_online),
            "last_updated": isoformat_z(latest_ts),
            "signals": [req for req, _ in resolved],
            "points": points,
        }

    @router.get("/windows/latest")
    def windows_latest(
        ahu_id: Optional[str] = Query(None, min_length=1),
        limit: int = Query(50, ge=1),
    ) -> Dict[str, Any]:
        resolved_ahu = (
            str(ahu_id)
            if ahu_id
            else _pick_default_ahu_id(telemetry_store, window_store)
        )
        if not resolved_ahu:
            return {"windows": []}

        lim = min(int(limit), int(settings.max_limit))
        items = window_store.latest_min_items(resolved_ahu, limit=lim)
        windows = []
        for it in items:
            windows.append(
                {
                    "window_id": it.get("window_id"),
                    "start_ts": it.get("start"),
                    "end_ts": it.get("end"),
                    "severity": it.get("max_severity"),
                    "diagnosis": it.get("text_summary"),
                }
            )
        return {"windows": windows}

    @router.get("/windows/{window_id}")
    def window_get(window_id: str) -> Dict[str, Any]:
        w = window_store.get(window_id)
        if w is None:
            raise HTTPException(status_code=404, detail={"error": "window_not_found"})

        # Shape expected by the dashboard
        time_obj = w.get("time")
        time_map: Mapping[str, Any] = time_obj if isinstance(time_obj, Mapping) else {}
        start_ts = time_map.get("start")
        end_ts = time_map.get("end")

        anomalies_obj = w.get("anomalies")
        anomalies: List[Any] = anomalies_obj if isinstance(anomalies_obj, list) else []
        failed_rules: List[Dict[str, Any]] = [
            a for a in anomalies if isinstance(a, dict)
        ]

        detail = {
            "window_id": str(w.get("window_id", "")),
            "start_ts": str(start_ts) if start_ts is not None else None,
            "end_ts": str(end_ts) if end_ts is not None else None,
            "severity": _max_window_severity(w),
            "diagnosis": str(w.get("text_summary") or "") or None,
            "confidence": None,
            "summary": {
                "ahu_id": w.get("ahu_id"),
                "signature": w.get("signature"),
                "text_summary": w.get("text_summary"),
            },
            "features": (
                w.get("features") if isinstance(w.get("features"), dict) else None
            ),
            "rules": {
                "failed": failed_rules,
                "passed": [],
            },
        }

        return detail

    @router.get("/incidents/active")
    def incidents_active(
        ahu_id: str = Query(..., min_length=1),
        mins: int = Query(30, ge=1),
    ) -> Dict[str, Any]:
        known = set(telemetry_store.ahus()) | set(window_store.ahus())
        if ahu_id not in known:
            raise HTTPException(status_code=404, detail={"error": "ahu_not_found"})

        mins_capped = min(int(mins), int(settings.max_mins))
        windows = window_store.windows_in_last_mins(ahu_id, mins=mins_capped)
        items = compute_active_incidents(windows)
        return {"ahu_id": ahu_id, "items": items}

    @router.get("/incidents/{signature}")
    def incident_windows(
        signature: str,
        ahu_id: str = Query(..., min_length=1),
        limit: int = Query(50, ge=1),
    ) -> Dict[str, Any]:
        known = set(telemetry_store.ahus()) | set(window_store.ahus())
        if ahu_id not in known:
            raise HTTPException(status_code=404, detail={"error": "ahu_not_found"})

        lim = min(int(limit), int(settings.max_limit))
        windows = window_store.windows_in_last_mins(ahu_id, mins=settings.max_mins)
        matches = [w for w in windows if str(w.get("signature", "")) == str(signature)]
        matches = list(reversed(matches))[:lim]
        return {
            "ahu_id": ahu_id,
            "signature": signature,
            "items": [min_window_item(w) for w in matches],
        }

    app.include_router(router)

    @app.on_event("startup")
    def _startup() -> None:
        logger.info(
            "Starting Kafka ingest: telemetry_topics=%s window_topics=%s bootstrap=%s",
            settings.kafka_telemetry_topics,
            settings.kafka_window_topics,
            settings.kafka_bootstrap_servers,
        )
        ingest.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        logger.info("Stopping Kafka ingest")
        ingest.stop()

    return app


app = create_app()
