from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.api import control_plane as router
from app.services import incidents as incident_service


class FakeRecord:
    async def save(self, **_kwargs: Any) -> None:
        return None


class FakeIncident(FakeRecord):
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


class FakeAlert(FakeRecord):
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


class FakeAlertQuery:
    def __init__(self, items: list[FakeAlert]) -> None:
        self.items = items

    def exclude(self, **filters: Any) -> "FakeAlertQuery":
        return FakeAlertQuery(
            [
                item
                for item in self.items
                if not all(getattr(item, key) == value for key, value in filters.items())
            ]
        )

    async def exists(self) -> bool:
        return bool(self.items)

    def order_by(self, field: str) -> "FakeAlertQuery":
        key = field.removeprefix("-")
        self.items.sort(
            key=lambda item: getattr(item, key) or datetime.min.replace(tzinfo=UTC),
            reverse=field.startswith("-"),
        )
        return self

    async def first(self) -> FakeAlert | None:
        return self.items[0] if self.items else None


class FakeIncidentModel:
    items: dict[str, FakeIncident] = {}

    @classmethod
    async def get_or_none(cls, **filters: Any) -> FakeIncident | None:
        return next(
            (
                item
                for item in cls.items.values()
                if all(getattr(item, key) == value for key, value in filters.items())
            ),
            None,
        )

    @classmethod
    async def get(cls, *, id: str) -> FakeIncident:
        return cls.items[id]

    @classmethod
    async def create(cls, **values: Any) -> FakeIncident:
        item = FakeIncident(**values)
        cls.items[item.id] = item
        return item


class FakeAlertModel:
    items: list[FakeAlert] = []

    @classmethod
    async def get_or_none(cls, **filters: Any) -> FakeAlert | None:
        return next(
            (
                item
                for item in cls.items
                if all(getattr(item, key) == value for key, value in filters.items())
            ),
            None,
        )

    @classmethod
    async def create(cls, **values: Any) -> FakeAlert:
        item = FakeAlert(**values)
        cls.items.append(item)
        return item

    @classmethod
    def filter(cls, **filters: Any) -> FakeAlertQuery:
        return FakeAlertQuery(
            [
                item
                for item in cls.items
                if all(getattr(item, key) == value for key, value in filters.items())
            ]
        )


@pytest.fixture(autouse=True)
def fake_incident_models(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeIncidentModel.items = {}
    FakeAlertModel.items = []
    monkeypatch.setattr(incident_service, "Incident", FakeIncidentModel)
    monkeypatch.setattr(incident_service, "AlertEvent", FakeAlertModel)
    counter = iter(range(100))
    monkeypatch.setattr(
        incident_service,
        "new_id",
        lambda prefix: f"{prefix}_{next(counter)}",
    )


def _alert(
    fingerprint: str,
    *,
    status: str = "firing",
    instance: str = "pod-a",
    started_at: datetime,
) -> dict[str, Any]:
    ended_at = started_at + timedelta(minutes=3) if status == "resolved" else None
    return {
        "fingerprint": fingerprint,
        "status": status,
        "startsAt": started_at.isoformat(),
        "endsAt": ended_at.isoformat() if ended_at else "0001-01-01T00:00:00Z",
        "labels": {
            "alertname": "PodCrashLooping",
            "service": "checkout",
            "namespace": "production",
            "instance": instance,
            "severity": "critical",
        },
        "annotations": {"summary": "Pod is restarting"},
    }


@pytest.mark.asyncio
async def test_resolved_notification_updates_original_event_and_incident() -> None:
    started_at = datetime(2026, 7, 29, 10, tzinfo=UTC)
    firing = {"status": "firing", "alerts": [_alert("fingerprint-one", started_at=started_at)]}
    incident = (await incident_service.ingest_alertmanager(firing))[0]

    resolved = {
        "status": "resolved",
        "alerts": [
            _alert(
                "fingerprint-one",
                status="resolved",
                started_at=started_at,
            )
        ],
    }
    resolved_incident = (await incident_service.ingest_alertmanager(resolved))[0]
    event = FakeAlertModel.items[0]

    assert resolved_incident.id == incident.id
    assert resolved_incident.status == "resolved"
    assert resolved_incident.ended_at == started_at + timedelta(minutes=3)
    assert resolved_incident.alert_count == 1
    assert event.status == "resolved"
    assert event.ended_at == started_at + timedelta(minutes=3)


@pytest.mark.asyncio
async def test_incident_closes_only_after_all_aggregated_alerts_resolve() -> None:
    started_at = datetime(2026, 7, 29, 11, tzinfo=UTC)
    alerts = [
        _alert("fingerprint-two", instance="pod-b", started_at=started_at),
        _alert("fingerprint-three", instance="pod-c", started_at=started_at),
    ]
    incident = (
        await incident_service.ingest_alertmanager({"status": "firing", "alerts": alerts})
    )[0]

    await incident_service.ingest_alertmanager(
        {
            "status": "resolved",
            "alerts": [
                _alert(
                    "fingerprint-two",
                    status="resolved",
                    instance="pod-b",
                    started_at=started_at,
                )
            ],
        }
    )
    assert incident.status == "open"

    await incident_service.ingest_alertmanager(
        {
            "status": "resolved",
            "alerts": [
                _alert(
                    "fingerprint-three",
                    status="resolved",
                    instance="pod-c",
                    started_at=started_at,
                )
            ],
        }
    )
    assert incident.status == "resolved"


@pytest.mark.asyncio
async def test_auto_analysis_is_enqueued_once_for_firing_incident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis_runs: list[SimpleNamespace] = []

    class AnalysisRunQuery:
        async def exists(self) -> bool:
            return bool(analysis_runs)

    class AnalysisRunModel:
        @staticmethod
        def filter(**_filters: Any) -> AnalysisRunQuery:
            return AnalysisRunQuery()

    async def new_analysis_run(incident_id: str) -> SimpleNamespace:
        run = SimpleNamespace(id=f"run-{incident_id}")
        analysis_runs.append(run)
        return run

    class Supervisor:
        def __init__(self) -> None:
            self.enqueued: list[str] = []

        async def enqueue(self, run_id: str) -> None:
            self.enqueued.append(run_id)

    monkeypatch.setattr(router, "AnalysisRun", AnalysisRunModel)
    monkeypatch.setattr(router, "_new_analysis_run", new_analysis_run)
    supervisor = Supervisor()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(rca_supervisor=supervisor))
    )
    incident = SimpleNamespace(id="incident-one", status="open")
    payload = {"status": "firing", "alerts": [{"status": "firing"}]}

    firing_incidents = router._firing_incidents(payload, [incident])
    first = await router._enqueue_analysis_runs(request, firing_incidents)
    second = await router._enqueue_analysis_runs(request, firing_incidents)

    assert first == ["run-incident-one"]
    assert second == []
    assert supervisor.enqueued == first
    assert router._firing_incidents(
        {"status": "resolved", "alerts": [{"status": "resolved"}]},
        [incident],
    ) == []
