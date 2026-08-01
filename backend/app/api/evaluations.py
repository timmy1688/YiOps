from time import monotonic
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.evaluation.benchmark import run_benchmark
from app.models import EvaluationRun, new_id
from app.schemas import EvaluationRunRead
from app.security.tenant import DEFAULT_TENANT_ID, current_tenant_id

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def _tenant_id() -> str:
    return current_tenant_id() or DEFAULT_TENANT_ID


@router.get("/preview")
async def preview_benchmark() -> dict[str, Any]:
    return run_benchmark()


@router.get("/runs", response_model=list[EvaluationRunRead])
async def list_evaluation_runs(limit: int = 10) -> list[EvaluationRunRead]:
    items = (
        await EvaluationRun.filter(tenant_id=_tenant_id())
        .order_by("-created_at")
        .limit(min(max(limit, 1), 50))
    )
    return [EvaluationRunRead.model_validate(item) for item in items]


@router.get("/runs/{run_id}", response_model=EvaluationRunRead)
async def get_evaluation_run(run_id: str) -> EvaluationRunRead:
    item = await EvaluationRun.get_or_none(id=run_id, tenant_id=_tenant_id())
    if item is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return EvaluationRunRead.model_validate(item)


@router.post(
    "/runs",
    response_model=EvaluationRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation_run() -> EvaluationRunRead:
    started = monotonic()
    report = run_benchmark()
    item = await EvaluationRun.create(
        id=new_id("eval"),
        tenant_id=_tenant_id(),
        benchmark=report["benchmark"],
        engine="evidence-rules-baseline",
        scenario_count=report["scenario_count"],
        aggregate=report["aggregate"],
        categories=report["categories"],
        results=report["results"],
        duration_ms=int((monotonic() - started) * 1000),
    )
    return EvaluationRunRead.model_validate(item)
