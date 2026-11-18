"""Owner settings: preferences, assistant profile, voices and personal-voice consent."""

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from sparta.api.deps import Ctr, Owner, profile_write_limit, run_idempotent
from sparta.api.errors import ERROR_RESPONSES
from sparta.domain.models import AssistantProfile, UserPreferences, VoiceOption, VoiceProfileView
from sparta.services.views import PreviewRequest, PreviewResult, VoiceConsentView, VoiceEnrollRequest

router = APIRouter(tags=["account"], responses=ERROR_RESPONSES)


@router.get("/preferences", response_model=UserPreferences)
async def get_preferences(owner: Owner, c: Ctr) -> UserPreferences:
    return await c.owner.get_preferences(owner)


@router.put("/preferences", response_model=UserPreferences)
async def put_preferences(prefs: UserPreferences, owner: Owner, c: Ctr) -> UserPreferences:
    """Replaces the owner's preferences. Unknown fields are rejected; languages and retention are validated."""
    return await c.owner.save_preferences(owner, prefs)


@router.get("/assistant-profile", response_model=AssistantProfile)
async def get_profile(owner: Owner, c: Ctr) -> AssistantProfile:
    return await c.owner.get_profile(owner)


@router.put("/assistant-profile", response_model=AssistantProfile, dependencies=[Depends(profile_write_limit)])
async def put_profile(profile: AssistantProfile, owner: Owner, c: Ctr) -> AssistantProfile:
    """The AI disclosure is not part of the profile: it cannot be switched off. `use_personal_voice` is refused (409)
    unless the voice is `ready` and the feature is enabled."""
    return await c.owner.save_profile(owner, profile)


@router.post("/assistant-profile/preview", response_model=PreviewResult)
async def preview(req: PreviewRequest, owner: Owner, c: Ctr) -> PreviewResult:
    """Runs the real conversation engine on `sample_text` without creating a call or storing anything."""
    return await c.owner.preview(owner, req)


@router.get("/voices", response_model=list[VoiceOption])
async def voices(
    owner: Owner,
    c: Ctr,
    locale: str | None = Query(default=None, pattern=r"^[a-z]{2,3}-[A-Z]{2}$"),
) -> list[VoiceOption]:
    return await c.owner.voices(locale)


@router.get("/voice/status", response_model=VoiceProfileView)
async def voice_status(owner: Owner, c: Ctr) -> VoiceProfileView:
    return await c.owner.voice_status(owner)


@router.get("/voice/consent", response_model=VoiceConsentView)
async def voice_consent(owner: Owner, c: Ctr) -> VoiceConsentView:
    return c.owner.voice_consent()


@router.post("/voice/enroll", response_model=VoiceProfileView)
async def voice_enroll(
    req: VoiceEnrollRequest, request: Request, owner: Owner, c: Ctr
) -> VoiceProfileView | JSONResponse:
    """Records consent. The status becomes `pending_provider_approval`: the voice provider's approval cannot be
    completed inside Sparta."""

    async def go() -> VoiceProfileView:
        return await c.owner.enroll_voice(owner, req)

    return await run_idempotent(request, owner, c, go, body=req)


@router.delete("/voice", status_code=204)
async def voice_delete(owner: Owner, c: Ctr) -> Response:
    await c.owner.delete_voice(owner)
    return Response(status_code=204)
