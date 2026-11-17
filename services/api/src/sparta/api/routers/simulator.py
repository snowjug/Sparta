"""Simulator Lab: scenarios, simulated calls (always the simulator adapter) and deterministic replay."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from sparta.api.deps import Ctr, Owner, create_call_limit, require_simulator, run_idempotent
from sparta.api.errors import ERROR_RESPONSES
from sparta.domain.models import CallDetail
from sparta.services.dto import CreateCallRequest
from sparta.services.views import (
    CreateScenarioRequest,
    ProviderOption,
    ReplayRequest,
    ReplayResult,
    ScenarioSummary,
)

router = APIRouter(
    prefix="/simulator", tags=["simulator"], responses=ERROR_RESPONSES, dependencies=[Depends(require_simulator)]
)


@router.get("/providers", response_model=list[ProviderOption])
async def providers(owner: Owner, c: Ctr) -> list[ProviderOption]:
    """Which adapters are active and which could be: a provider that is not configured says what is missing."""
    return c.simulator.providers_list()


@router.get("/scenarios", response_model=list[ScenarioSummary])
async def scenarios(owner: Owner, c: Ctr) -> list[ScenarioSummary]:
    return await c.simulator.list_scenarios(owner)


@router.post("/scenarios", response_model=ScenarioSummary, status_code=201)
async def create_scenario(
    req: CreateScenarioRequest, request: Request, owner: Owner, c: Ctr
) -> ScenarioSummary | JSONResponse:
    async def go() -> ScenarioSummary:
        return await c.simulator.create_scenario(owner, req)

    return await run_idempotent(request, owner, c, go, status_code=201, body=req)


@router.post("/calls", response_model=CallDetail, status_code=201, dependencies=[Depends(create_call_limit)])
async def create_simulated_call(
    req: CreateCallRequest, request: Request, owner: Owner, c: Ctr
) -> CallDetail | JSONResponse:
    """With `scenario_id` and `autoplay`, the scripted caller is played server-side with its gaps, and every step is
    streamed over the live socket."""

    async def go() -> CallDetail:
        return await c.simulator.create_call(owner, req)

    return await run_idempotent(request, owner, c, go, status_code=201, body=req)


@router.post("/replay", response_model=ReplayResult, dependencies=[Depends(create_call_limit)])
async def replay(req: ReplayRequest, owner: Owner, c: Ctr) -> ReplayResult:
    """Deterministic replay in an isolated container (virtual clock, in-memory database): the same input yields the same
    `checksum`. Nothing is written to the owner's call history."""
    return await c.simulator.replay(owner, req)
