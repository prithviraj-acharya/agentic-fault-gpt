from __future__ import annotations

from dataclasses import dataclass

from diagnostic_agent.controller.schemas import DiagnosisResult, IncidentContext


@dataclass(frozen=True)
class MockReasoner:
    """Deterministic reasoner for demos/tests."""

    def diagnose(self, ctx: IncidentContext) -> DiagnosisResult:
        ft = ctx.detected_fault_type
        if ft == "COOLING_COIL_FAULT":
            return DiagnosisResult(
                title="Cooling coil underperforming",
                root_cause="Supply air temperature remains high despite high cooling demand; possible fouled coil or valve/actuator issue.",
                confidence=0.78 if ctx.stage == 1 else 0.88,
                recommended_actions=[
                    "Inspect cooling coil for fouling/blocked airflow",
                    "Verify chilled water flow and valve actuator operation",
                    "Check SAT sensor calibration",
                ],
                evidence_ids=[
                    "manuals:cooling_coil_section",
                    "past_cases:cc_underperforming",
                ],
            )

        if ft in {"OA_DAMPER_STUCK", "RA_DAMPER_STUCK"}:
            damper = "Outdoor air" if ft == "OA_DAMPER_STUCK" else "Return air"
            return DiagnosisResult(
                title=f"{damper} damper stuck or flatlined",
                root_cause="Damper position shows near-zero variance across windows; could be stuck linkage, failed actuator, or sensor flatline.",
                confidence=0.8 if ctx.stage == 1 else 0.9,
                recommended_actions=[
                    "Check damper actuator command vs feedback",
                    "Inspect damper linkage for binding",
                    "Validate damper position sensor signal integrity",
                ],
                evidence_ids=["manuals:damper_actuator", "past_cases:damper_stuck"],
            )

        if ft == "ZONE_TEMP_SENSOR_DRIFT":
            return DiagnosisResult(
                title="Zone temperature sensing anomaly",
                root_cause="Zone temperature trend/variance suggests sensor drift/noise or unstable zone conditions.",
                confidence=0.7 if ctx.stage == 1 else 0.82,
                recommended_actions=[
                    "Compare zone sensor against reference thermometer",
                    "Check sensor wiring and controller input noise",
                    "Review recent setpoint and occupancy changes",
                ],
                evidence_ids=[
                    "manuals:sensor_calibration",
                    "past_cases:zone_temp_drift",
                ],
            )

        return DiagnosisResult(
            title="Unknown fault",
            root_cause="Insufficient evidence to determine a specific root cause.",
            confidence=0.4 if ctx.stage == 1 else 0.55,
            recommended_actions=["Collect more data and review anomalies"],
            evidence_ids=[],
        )
