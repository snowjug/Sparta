"""System information: capabilities of this deployment, the signed-in owner and the Home summary."""

from fastapi import APIRouter

from sparta.api.deps import Ctr, Owner
from sparta.api.errors import ERROR_RESPONSES
from sparta.services.views import HomeSummary, MeView, SystemStatus

router = APIRouter(tags=["system"], responses=ERROR_RESPONSES)


@router.get("/system/status", response_model=SystemStatus)
async def system_status(c: Ctr) -> SystemStatus:
    """Public and free of personal data. Clients must show a "Development identity" banner when `dev_banner` is true,
    and must show whether telephony is real or simulated."""
    return c.owner.system_status()


@router.get("/me", response_model=MeView)
async def me(owner: Owner, c: Ctr) -> MeView:
    return c.owner.me(owner)


@router.get("/home", response_model=HomeSummary)
async def home(owner: Owner, c: Ctr) -> HomeSummary:
    """Protection status, the next useful action, today's counters and the calls that need the owner."""
    return await c.owner.home(owner)
