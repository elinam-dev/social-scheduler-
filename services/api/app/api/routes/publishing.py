import logging
import secrets
import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Clip, PlatformToken, ScheduledPost
from app.db.session import get_session
from app.schemas.scheduled_post import (
    PlatformConnectionStatus,
    ScheduledPostCreate,
    ScheduledPostRead,
)
from app.token_crypto import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["publishing"])

# In-memory CSRF state store (single-user local app — good enough)
_oauth_states: dict[str, str] = {}

_YOUTUBE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.upload"
_YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"

_TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

_INSTAGRAM_AUTH_URL = "https://api.instagram.com/oauth/authorize"
_INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
_INSTAGRAM_LONG_TOKEN_URL = "https://graph.instagram.com/access_token"
_INSTAGRAM_SCOPES = "instagram_basic,instagram_content_publish"


def _settings() -> Settings:
    return Settings()


def _redirect_uri(platform: str, settings: Settings) -> str:
    return f"{settings.public_api_url.rstrip('/')}/auth/{platform}/callback"


@router.get("/auth/{platform}/connect")
def connect_platform(
    platform: str,
    settings: Settings = Depends(_settings),
) -> PlatformConnectionStatus:
    _validate_platform(platform)
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = platform
    redirect = _redirect_uri(platform, settings)

    if platform == "youtube":
        if not settings.youtube_client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="YouTube OAuth is not configured. Set CLIPPER_YOUTUBE_CLIENT_ID.",
            )
        params = {
            "client_id": settings.youtube_client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": _YOUTUBE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        auth_url = f"{_YOUTUBE_AUTH_URL}?{urlencode(params)}"

    elif platform == "tiktok":
        if not settings.tiktok_client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TikTok OAuth is not configured. Set CLIPPER_TIKTOK_CLIENT_ID.",
            )
        params = {
            "client_key": settings.tiktok_client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "video.upload",
            "state": state,
        }
        auth_url = f"{_TIKTOK_AUTH_URL}?{urlencode(params)}"

    else:  # instagram
        if not settings.instagram_client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Instagram OAuth is not configured. Set CLIPPER_INSTAGRAM_CLIENT_ID.",
            )
        params = {
            "client_id": settings.instagram_client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": _INSTAGRAM_SCOPES,
            "state": state,
        }
        auth_url = f"{_INSTAGRAM_AUTH_URL}?{urlencode(params)}"

    return PlatformConnectionStatus(platform=platform, connected=False, auth_url=auth_url)


@router.get("/auth/{platform}/callback")
def oauth_callback(
    platform: str,
    code: str = Query(...),
    state: str = Query(...),
    session: Session = Depends(get_session),
    settings: Settings = Depends(_settings),
) -> RedirectResponse:
    _validate_platform(platform)
    if _oauth_states.pop(state, None) != platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )

    redirect = _redirect_uri(platform, settings)
    token_data = _exchange_code(platform, code, redirect, settings)
    encrypted = encrypt_token(token_data, settings)

    existing = session.scalar(
        select(PlatformToken).where(PlatformToken.platform == platform)
    )
    if existing:
        existing.encrypted_token = encrypted
    else:
        session.add(PlatformToken(platform=platform, encrypted_token=encrypted))
    session.commit()

    logger.info("OAuth token stored for platform %s", platform)
    # Redirect back to the UI
    return RedirectResponse(url="http://localhost:3000", status_code=302)


@router.delete("/auth/{platform}/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_platform(
    platform: str,
    session: Session = Depends(get_session),
) -> None:
    _validate_platform(platform)
    token = session.scalar(
        select(PlatformToken).where(PlatformToken.platform == platform)
    )
    if token:
        session.delete(token)
        session.commit()


@router.get("/auth/status", response_model=list[PlatformConnectionStatus])
def auth_status(
    session: Session = Depends(get_session),
    settings: Settings = Depends(_settings),
) -> list[PlatformConnectionStatus]:
    connected_platforms = {
        row.platform
        for row in session.scalars(select(PlatformToken)).all()
    }
    result = []
    for platform in ("youtube", "tiktok", "instagram"):
        connected = platform in connected_platforms
        auth_url = None
        if not connected:
            try:
                status_obj = connect_platform(platform, settings)
                auth_url = status_obj.auth_url
            except HTTPException:
                pass
        result.append(
            PlatformConnectionStatus(
                platform=platform, connected=connected, auth_url=auth_url
            )
        )
    return result


@router.post(
    "/clips/{clip_id}/schedule",
    response_model=list[ScheduledPostRead],
    status_code=status.HTTP_201_CREATED,
)
def schedule_clip(
    clip_id: uuid.UUID,
    body: ScheduledPostCreate,
    session: Session = Depends(get_session),
) -> list[ScheduledPost]:
    clip = session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found"
        )
    if clip.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Clip must be rendered (status=ready) before scheduling",
        )
    if not body.platforms:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one platform must be selected",
        )
    scheduled_at = body.scheduled_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    if scheduled_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scheduled_at must be in the future",
        )

    posts = []
    for platform in body.platforms:
        post = ScheduledPost(
            clip_id=clip_id,
            platform=platform,
            scheduled_at=scheduled_at,
        )
        session.add(post)
        posts.append(post)
    session.commit()
    for post in posts:
        session.refresh(post)
    return posts


@router.get(
    "/clips/{clip_id}/scheduled-posts",
    response_model=list[ScheduledPostRead],
)
def list_scheduled_posts(
    clip_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> list[ScheduledPost]:
    if session.get(Clip, clip_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found"
        )
    return list(
        session.scalars(
            select(ScheduledPost)
            .where(ScheduledPost.clip_id == clip_id)
            .order_by(ScheduledPost.scheduled_at.asc())
        ).all()
    )


@router.delete(
    "/scheduled-posts/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def cancel_scheduled_post(
    post_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> None:
    post = session.get(ScheduledPost, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled post not found"
        )
    if post.status in ("published", "publishing"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a post with status '{post.status}'",
        )
    post.status = "cancelled"
    session.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_platform(platform: str) -> None:
    if platform not in ("youtube", "tiktok", "instagram"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown platform: {platform}",
        )


def _exchange_code(
    platform: str, code: str, redirect_uri: str, settings: Settings
) -> dict:
    import json
    from urllib.error import HTTPError
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    if platform == "youtube":
        payload = {
            "code": code,
            "client_id": settings.youtube_client_id,
            "client_secret": settings.youtube_client_secret.get_secret_value()
            if settings.youtube_client_secret
            else "",
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        req = Request(
            _YOUTUBE_TOKEN_URL,
            data=urlencode(payload).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

    elif platform == "tiktok":
        payload = {
            "code": code,
            "client_key": settings.tiktok_client_id,
            "client_secret": settings.tiktok_client_secret.get_secret_value()
            if settings.tiktok_client_secret
            else "",
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        req = Request(
            _TIKTOK_TOKEN_URL,
            data=urlencode(payload).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

    else:  # instagram
        payload = {
            "code": code,
            "client_id": settings.instagram_client_id,
            "client_secret": settings.instagram_client_secret.get_secret_value()
            if settings.instagram_client_secret
            else "",
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        req = Request(
            _INSTAGRAM_TOKEN_URL,
            data=urlencode(payload).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

    try:
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
    except HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OAuth token exchange failed: {detail}",
        ) from error

    # For Instagram, exchange short-lived token for long-lived one
    if platform == "instagram" and "access_token" in data:
        data = _instagram_long_lived_token(
            data["access_token"],
            settings.instagram_client_secret.get_secret_value()
            if settings.instagram_client_secret
            else "",
        )

    return data


def _instagram_long_lived_token(short_token: str, client_secret: str) -> dict:
    import json
    from urllib.parse import urlencode
    from urllib.request import urlopen

    params = urlencode(
        {
            "grant_type": "ig_exchange_token",
            "client_secret": client_secret,
            "access_token": short_token,
        }
    )
    url = f"{_INSTAGRAM_LONG_TOKEN_URL}?{params}"
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read())
