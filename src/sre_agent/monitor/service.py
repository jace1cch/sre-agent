"""Monitoring orchestration for the SRE Agent."""

from sre_agent.actions import ActionExecutor
from sre_agent.core.agent import diagnose_incident
from sre_agent.core.cycle import IncidentCluster, cluster_incidents
from sre_agent.core.models import ContainerSnapshot, ErrorDiagnosis, EvidenceBundle, HostSnapshot, Incident, MonitorFinding, SourceAvailability
from sre_agent.core.settings import AgentSettings, get_settings
from sre_agent.detectors import BusinessDetector, DockerDetector, HostDetector, JavaDetector
from sre_agent.notify import WebhookNotifier
from sre_agent.storage import store_incident
from sre_agent.tools import ToolRuntime, build_runtime_tool_registry
from sre_agent.tools.runtime import describe_runtime_sources

SEVERITY_ORDER = {"info": 1, "warning": 2, "critical": 3}
IncidentResult = tuple[Incident, ErrorDiagnosis | None]


class MonitorService:
    """Run the monitor loop for the local MVP."""

    def __init__(self, settings: AgentSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.host_detector = HostDetector(self.settings)
        self.docker_detector = DockerDetector(self.settings)
        self.java_detector = JavaDetector(self.settings)
        self.business_detector = BusinessDetector(self.settings)
        self.notifier = WebhookNotifier(self.settings)
        self.executor = ActionExecutor(self.settings)

    def test_notify(self, message: str) -> bool:
        """Send a test notification."""

        return self.notifier.send_text(message)

    async def run_once(
        self,
        notify: bool = True,
        remediate: bool | None = None,
    ) -> tuple[Incident | None, ErrorDiagnosis | None]:
        """Run one monitoring cycle and return the first incident."""

        results = await self.run_cycle(notify=notify, remediate=remediate)
        if not results:
            return None, None
        return results[0]

    async def run_cycle(
        self,
        notify: bool = True,
        remediate: bool | None = None,
    ) -> list[IncidentResult]:
        """Run one monitoring cycle across the configured targets."""

        if self.settings.graph_enable_autonomous_loop:
            return await self._run_autonomous_cycle(notify=notify, remediate=remediate)
        return await self._run_legacy_cycle(notify=notify, remediate=remediate)

    async def _run_legacy_cycle(
        self,
        notify: bool,
        remediate: bool | None,
    ) -> list[IncidentResult]:
        """Run the existing per-target monitoring path."""

        host_snapshot = self.host_detector.collect_snapshot()
        incidents = self._collect_cycle_incidents(host_snapshot)
        results: list[IncidentResult] = []
        for incident in incidents:
            results.append(await self._finalise_incident(incident, notify=notify, remediate=remediate))
        return results

    async def _run_autonomous_cycle(
        self,
        notify: bool,
        remediate: bool | None,
    ) -> list[IncidentResult]:
        """Run the cycle-aware autonomous monitoring path."""

        host_snapshot = self.host_detector.collect_snapshot()
        incidents = self._collect_cycle_incidents(host_snapshot)
        if not incidents:
            return []

        runtime = self._build_tool_runtime()
        tool_registry = build_runtime_tool_registry(runtime)

        results: list[IncidentResult] = []
        for cluster in cluster_incidents(incidents):
            merged_incident = self._merge_cluster(cluster)
            merged_incident.evidence.input_sources = tool_registry.describe_sources(
                self._current_source_inventory(runtime)
            )
            results.append(
                await self._finalise_incident(
                    merged_incident,
                    notify=notify,
                    remediate=remediate,
                    tool_registry=tool_registry,
                )
            )
        return results

    def _build_tool_runtime(self) -> ToolRuntime:
        """Build shared runtime objects for source-aware tools."""

        return ToolRuntime(
            settings=self.settings,
            host_detector=self.host_detector,
            docker_detector=self.docker_detector,
            java_detector=self.java_detector,
            business_detector=self.business_detector,
        )

    def _current_source_inventory(self, runtime: ToolRuntime) -> list[SourceAvailability]:
        """Describe known input sources for this runtime."""

        return describe_runtime_sources(runtime)

    def _collect_cycle_incidents(self, host_snapshot: HostSnapshot) -> list[Incident]:
        """Collect all incidents detected in one cycle."""

        incidents: list[Incident] = []
        host_incident = self._build_host_incident(host_snapshot)
        if host_incident is not None:
            incidents.append(host_incident)

        for container_name in self.settings.monitored_container_names():
            incident = self._build_container_incident(container_name, host_snapshot)
            if incident is not None:
                incidents.append(incident)
        return incidents

    def _build_host_incident(self, host_snapshot: HostSnapshot) -> Incident | None:
        """Build an incident for host-level issues."""

        findings = self.host_detector.detect(host_snapshot)
        if not findings:
            return None
        runtime = self._build_tool_runtime()
        return Incident(
            service_name=f"host:{host_snapshot.hostname}",
            severity=self._highest_severity(findings),
            findings=findings,
            evidence=EvidenceBundle(
                host=host_snapshot,
                input_sources=self._current_source_inventory(runtime),
            ),
        )

    def _build_container_incident(
        self,
        container_name: str,
        host_snapshot: HostSnapshot,
    ) -> Incident | None:
        """Build an incident for one monitored container."""

        container_snapshot = self.docker_detector.inspect_container(container_name)
        findings = self.docker_detector.detect(container_snapshot)

        log_lines = self.docker_detector.read_recent_logs(container_name=container_name)
        java_analysis = self.java_detector.analyse(log_lines)
        findings.extend(java_analysis.findings)

        business_findings, business_events = self.business_detector.analyse(log_lines)
        findings.extend(business_findings)

        if not findings:
            return None

        thread_dump_excerpt: list[str] = []
        if java_analysis.thread_dump_required and container_snapshot is not None and container_snapshot.running:
            thread_dump_excerpt = self.java_detector.capture_thread_dump(container_snapshot.name)

        runtime = self._build_tool_runtime()
        return Incident(
            service_name=container_name,
            severity=self._highest_severity(findings),
            findings=findings,
            evidence=EvidenceBundle(
                host=host_snapshot,
                container=container_snapshot,
                log_excerpt=java_analysis.log_excerpt,
                gc_excerpt=java_analysis.gc_excerpt,
                thread_dump_excerpt=thread_dump_excerpt,
                business_events=business_events,
                input_sources=self._current_source_inventory(runtime),
            ),
        )

    def _merge_cluster(self, cluster: IncidentCluster) -> Incident:
        """Merge a clustered set of incidents into one report target."""

        if len(cluster.incidents) == 1:
            return cluster.incidents[0]

        findings: list[MonitorFinding] = []
        log_excerpt: list[str] = []
        gc_excerpt: list[str] = []
        thread_dump_excerpt: list[str] = []
        business_events: list[dict[str, object]] = []
        input_sources: list[SourceAvailability] = []
        host_snapshot = None
        container_snapshots: list[ContainerSnapshot] = []

        for incident in cluster.incidents:
            findings.extend(incident.findings)
            if host_snapshot is None and incident.evidence.host is not None:
                host_snapshot = incident.evidence.host
            if incident.evidence.container is not None:
                container_snapshots.append(incident.evidence.container)
            log_excerpt.extend(incident.evidence.log_excerpt)
            gc_excerpt.extend(incident.evidence.gc_excerpt)
            thread_dump_excerpt.extend(incident.evidence.thread_dump_excerpt)
            business_events.extend(incident.evidence.business_events)
            input_sources.extend(incident.evidence.input_sources)

        merged_service_name = ",".join(dict.fromkeys(incident.service_name for incident in cluster.incidents))
        details = {
            "cluster_size": len(cluster.incidents),
            "correlation_method": cluster.correlation_method,
            "containers": [snapshot.name for snapshot in container_snapshots],
        }
        findings.insert(
            0,
            MonitorFinding(
                code="clustered_incident",
                detector="cycle",
                severity=self._highest_severity(findings),
                summary=f"Clustered {len(cluster.incidents)} related incidents.",
                details=(
                    f"Merged incidents using {cluster.correlation_method} correlation "
                    f"for services {merged_service_name}."
                ),
                evidence=details,
            ),
        )

        deduplicated_sources: dict[str, SourceAvailability] = {
            source.name: source for source in input_sources
        }
        return Incident(
            service_name=merged_service_name,
            severity=self._highest_severity(findings),
            observed_at=cluster.window_start,
            findings=findings,
            evidence=EvidenceBundle(
                host=host_snapshot,
                container=container_snapshots[0] if len(container_snapshots) == 1 else None,
                log_excerpt=log_excerpt[-40:],
                gc_excerpt=gc_excerpt[-40:],
                thread_dump_excerpt=thread_dump_excerpt[-80:],
                business_events=business_events[-20:],
                input_sources=list(deduplicated_sources.values()),
            ),
        )

    async def _finalise_incident(
        self,
        incident: Incident,
        notify: bool,
        remediate: bool | None,
        tool_registry=None,
    ) -> IncidentResult:
        """Diagnose, store, notify, and optionally remediate an incident."""

        diagnosis = await diagnose_incident(incident, self.settings, tool_registry=tool_registry)

        should_remediate = self.settings.auto_remediate if remediate is None else remediate
        if should_remediate:
            incident.actions = self.executor.execute(incident)

        store_incident(incident, diagnosis, self.settings.incident_store_path)

        if notify:
            self.notifier.send_incident(incident, diagnosis)

        return incident, diagnosis

    def _highest_severity(self, findings: list[MonitorFinding]) -> str:
        highest = max(findings, key=lambda finding: SEVERITY_ORDER[finding.severity])
        return highest.severity