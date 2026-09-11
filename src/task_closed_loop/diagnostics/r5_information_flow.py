from __future__ import annotations

from .models import DiagnosticFinding, DiagnosticSnapshot


ROOT = "R5"


def _destination_ref(destination) -> str:
    if destination is None:
        return ""
    if isinstance(destination, str):
        return destination
    if isinstance(destination, dict):
        for key in ("destination_id", "id", "ref", "name"):
            if destination.get(key):
                return str(destination[key])
        return repr(sorted(destination.items()))
    return str(destination)


class R5Reviewer:
    root = ROOT

    def review(self, snapshot: DiagnosticSnapshot) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []

        for flow in snapshot.information_flows:
            context = flow.context
            destination = _destination_ref(context.destination)

            if not flow.source_lineage_complete:
                findings.append(
                    DiagnosticFinding(
                        root=ROOT,
                        code="incomplete_source_lineage",
                        severity="critical",
                        subject=flow.flow_id,
                        challenge="Derived Content 的来源关系是否完整到足以审查当前信息流？",
                        evidence=tuple(context.source_refs + context.derived_refs),
                        consequence="信息流缺少完整 Source Lineage。",
                    )
                )

            if (
                flow.permitted_destination_refs
                and destination not in set(flow.permitted_destination_refs)
            ):
                findings.append(
                    DiagnosticFinding(
                        root=ROOT,
                        code="destination_outside_disclosure_relation",
                        severity="critical",
                        subject=flow.flow_id,
                        challenge="当前 Destination 是否仍在这份信息的现实披露关系内？",
                        evidence=(destination,) + tuple(flow.permitted_destination_refs),
                        consequence="Destination 超出已提供的披露范围。",
                    )
                )

            if flow.permitted_audience:
                extra_audience = (
                    set(context.audience)
                    - set(flow.permitted_audience)
                )
                if extra_audience:
                    findings.append(
                        DiagnosticFinding(
                            root=ROOT,
                            code="audience_outside_disclosure_relation",
                            severity="critical",
                            subject=flow.flow_id,
                            challenge="当前 Audience 是否扩大到了来源现实没有支持的人群？",
                            evidence=tuple(sorted(extra_audience)),
                            consequence="Audience 超出已提供的披露关系。",
                        )
                    )

        return findings


def inspect(snapshot: DiagnosticSnapshot):
    return R5Reviewer().review(snapshot)
