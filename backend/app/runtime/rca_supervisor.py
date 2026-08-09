import asyncio
from contextlib import suppress

from app.agents.rca import RcaAgent
from app.models import AnalysisRun


class RcaSupervisor:
    def __init__(self, agent: RcaAgent, concurrency: int) -> None:
        self.agent = agent
        self.concurrency = concurrency
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._queued: set[str] = set()
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._worker(), name=f"analysis-worker-{index}")
            for index in range(self.concurrency)
        ]
        pending = await AnalysisRun.filter(status__in=["queued", "running"]).all()
        for run in pending:
            await self.enqueue(run.id)

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            with suppress(asyncio.CancelledError):
                await worker
        self._workers.clear()

    async def enqueue(self, run_id: str) -> None:
        if run_id in self._queued:
            return
        self._queued.add(run_id)
        await self.queue.put(run_id)

    async def _worker(self) -> None:
        while True:
            run_id = await self.queue.get()
            try:
                await self.agent.run(run_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                await self.agent.fail(run_id, exc)
            finally:
                self._queued.discard(run_id)
                self.queue.task_done()
