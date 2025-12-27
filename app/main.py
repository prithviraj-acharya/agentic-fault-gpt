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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
    def live_overview(ahu_id: str = Query(..., min_length=1)) -> Dict[str, Any]:
        # Unknown AHU policy: 404
        known = set(telemetry_store.ahus()) | set(window_store.ahus())
        if ahu_id not in known:
            raise HTTPException(status_code=404, detail={"error": "ahu_not_found"})

        latest_tel = telemetry_store.latest(ahu_id)
        latest_win_items = window_store.latest_min_items(ahu_id, limit=1)
        latest_win = latest_win_items[0] if latest_win_items else None

        system_status = "offline"
        last_telemetry_ts: Optional[str] = None
        kpis: Dict[str, float] = {}

        if latest_tel is not None:
            ts, values = latest_tel
            last_telemetry_ts = isoformat_z(ts)
            age = (_now_utc() - ts).total_seconds()
            system_status = (
                "online" if age <= float(settings.online_threshold_secs) else "offline"
            )
            kpis = {k: float(v) for k, v in values.items()}

        active_incident = None
        if latest_win is not None and latest_win.get("signature"):
            mins = 30
            windows = window_store.windows_in_last_mins(ahu_id, mins=mins)
            incidents = compute_active_incidents(windows)
            sig = str(latest_win.get("signature"))
            match = next((i for i in incidents if i.get("signature") == sig), None)
            if match is not None:
                active_incident = {
                    "signature": match.get("signature"),
                    "first_seen": match.get("first_seen"),
                    "last_seen": match.get("last_seen"),
                    "count": match.get("count"),
                    "max_severity": match.get("max_severity"),
                }

        return {
            "ahu_id": ahu_id,
            "system_status": system_status,
            "last_telemetry_ts": last_telemetry_ts,
            "kpis": kpis,
            "latest_window": latest_win,
            "active_incident": active_incident,
        }

    @router.get("/live/timeseries")
    def live_timeseries(
        ahu_id: str = Query(..., min_length=1),
        mins: int = Query(30, ge=1),
        signals: str = Query(""),
    ) -> Dict[str, Any]:
        known = set(telemetry_store.ahus()) | set(window_store.ahus())
        if ahu_id not in known:
            raise HTTPException(status_code=404, detail={"error": "ahu_not_found"})

        mins_capped = min(int(mins), int(settings.max_mins))
        to_ts = _now_utc()
        from_ts = to_ts - timedelta(minutes=mins_capped)

        requested = [s.strip() for s in signals.split(",") if s.strip()]
        # Ignore unknown signals by intersecting with latest values keys (best effort)
        latest = telemetry_store.latest(ahu_id)
        if latest is None:
            known_signals: List[str] = []
        else:
            known_signals = sorted(set(latest[1].keys()))

        use_signals = [s for s in requested if s in set(known_signals)]

        points = telemetry_store.range(
            ahu_id, from_ts=from_ts, to_ts=to_ts, signals=use_signals
        )

        return {
            "ahu_id": ahu_id,
            "from": isoformat_z(from_ts),
            "to": isoformat_z(to_ts),
            "signals": use_signals,
            "points": points,
        }

    @router.get("/windows/latest")
    def windows_latest(
        ahu_id: str = Query(..., min_length=1),
        limit: int = Query(50, ge=1),
    ) -> Dict[str, Any]:
        known = set(telemetry_store.ahus()) | set(window_store.ahus())
        if ahu_id not in known:
            raise HTTPException(status_code=404, detail={"error": "ahu_not_found"})

        lim = min(int(limit), int(settings.max_limit))
        return {
            "ahu_id": ahu_id,
            "items": window_store.latest_min_items(ahu_id, limit=lim),
        }

    @router.get("/windows/{window_id}")
    def window_get(window_id: str) -> Dict[str, Any]:
        w = window_store.get(window_id)
        if w is None:
            raise HTTPException(status_code=404, detail={"error": "window_not_found"})
        return w

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
