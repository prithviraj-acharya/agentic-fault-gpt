from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


@dataclass(frozen=True)
class TicketApiClient:
    """Client wrapper around the backend ticket API.

    IMPORTANT: Phase 6 must never access SQLite directly.
    """

    base_url: str
    timeout_s: float = 5.0

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url.rstrip("/"), timeout=self.timeout_s)

    def get_active_ticket(
        self, *, ahu_id: str, detected_fault_type: str
    ) -> Optional[Dict[str, Any]]:
        params = {
            "lifecycle_status": "OPEN",
            "ahu_id": ahu_id,
            "fault_type": detected_fault_type,
            "limit": 1,
            "offset": 0,
            "sort": "updated_at",
            "order": "desc",
        }
        with self._client() as client:
            r = client.get("/tickets", params=params)
            r.raise_for_status()
            data = r.json()
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list) or not items:
                return None
            first = items[0]
            return first if isinstance(first, dict) else None

    def create_ticket(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Backend expects upsert with explicit ticket_id.
        body = dict(payload)
        body.setdefault("ticket_id", str(uuid.uuid4()))
        with self._client() as client:
            r = client.post("/tickets/upsert", json=body)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {"ticket_id": body["ticket_id"]}

    def patch_ticket(
        self, ticket_id: str, patch_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        # Backend exposes an upsert endpoint (no generic PATCH). We emulate patch.
        body = dict(patch_payload)
        body["ticket_id"] = str(ticket_id)
        with self._client() as client:
            r = client.post("/tickets/upsert", json=body)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {"ticket_id": str(ticket_id)}
