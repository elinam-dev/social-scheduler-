"""Platform publishing: upload a rendered clip to YouTube, TikTok, or Instagram."""

import json
import logging
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_TIKTOK_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
_INSTAGRAM_GRAPH_URL = "https://graph.instagram.com/v19.0"


class PublishError(RuntimeError):
    pass


def publish_clip(
    platform: str,
    token_data: dict,
    clip_path: Path,
    title: str,
    description: str = "",
) -> str:
    """Upload clip_path to the given platform. Returns the platform post ID."""
    if platform == "youtube":
        return _publish_youtube(token_data, clip_path, title, description)
    if platform == "tiktok":
        return _publish_tiktok(token_data, clip_path, title)
    if platform == "instagram":
        return _publish_instagram(token_data, clip_path, title, description)
    raise PublishError(f"Unknown platform: {platform}")


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

def _publish_youtube(
    token_data: dict, clip_path: Path, title: str, description: str
) -> str:
    access_token = _youtube_valid_token(token_data)
    file_size = clip_path.stat().st_size

    # Step 1: initiate resumable upload
    metadata = json.dumps(
        {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "categoryId": "22",  # People & Blogs
            },
            "status": {"privacyStatus": "private"},
        }
    ).encode()

    init_url = (
        f"{_YOUTUBE_UPLOAD_URL}?uploadType=resumable&part=snippet,status"
    )
    init_req = Request(
        init_url,
        data=metadata,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(file_size),
        },
        method="POST",
    )
    try:
        with urlopen(init_req, timeout=30) as resp:
            upload_url = resp.headers.get("Location")
    except HTTPError as error:
        raise PublishError(
            f"YouTube upload init failed: {error.read().decode(errors='replace')}"
        ) from error

    if not upload_url:
        raise PublishError("YouTube did not return a resumable upload URL")

    # Step 2: upload the file
    with clip_path.open("rb") as video_file:
        video_data = video_file.read()

    upload_req = Request(
        upload_url,
        data=video_data,
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size),
        },
        method="PUT",
    )
    try:
        with urlopen(upload_req, timeout=600) as resp:
            result = json.loads(resp.read())
    except HTTPError as error:
        raise PublishError(
            f"YouTube upload failed: {error.read().decode(errors='replace')}"
        ) from error

    video_id = result.get("id")
    if not video_id:
        raise PublishError("YouTube did not return a video ID after upload")
    logger.info("Published to YouTube: %s", video_id)
    return str(video_id)


def _youtube_valid_token(token_data: dict) -> str:
    """Return a valid access token, refreshing if needed."""
    from app.config import Settings

    expires_at = token_data.get("expires_at", 0)
    if time.time() < float(expires_at) - 60:
        return token_data["access_token"]

    settings = Settings()
    payload = {
        "client_id": settings.youtube_client_id,
        "client_secret": settings.youtube_client_secret.get_secret_value()
        if settings.youtube_client_secret
        else "",
        "refresh_token": token_data.get("refresh_token", ""),
        "grant_type": "refresh_token",
    }
    req = Request(
        _YOUTUBE_TOKEN_URL,
        data=urlencode(payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            refreshed = json.loads(resp.read())
    except HTTPError as error:
        raise PublishError(
            f"YouTube token refresh failed: {error.read().decode(errors='replace')}"
        ) from error

    token_data["access_token"] = refreshed["access_token"]
    token_data["expires_at"] = time.time() + refreshed.get("expires_in", 3600)
    return token_data["access_token"]


# ---------------------------------------------------------------------------
# TikTok
# ---------------------------------------------------------------------------

def _publish_tiktok(token_data: dict, clip_path: Path, title: str) -> str:
    access_token = token_data.get("access_token", "")
    file_size = clip_path.stat().st_size

    # Step 1: init upload
    init_payload = json.dumps(
        {
            "post_info": {
                "title": title[:150],
                "privacy_level": "SELF_ONLY",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1,
            },
        }
    ).encode()

    init_req = Request(
        _TIKTOK_INIT_URL,
        data=init_payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urlopen(init_req, timeout=30) as resp:
            init_result = json.loads(resp.read())
    except HTTPError as error:
        raise PublishError(
            f"TikTok upload init failed: {error.read().decode(errors='replace')}"
        ) from error

    data = init_result.get("data", {})
    publish_id = data.get("publish_id")
    upload_url = data.get("upload_url")
    if not publish_id or not upload_url:
        raise PublishError(f"TikTok init did not return publish_id/upload_url: {init_result}")

    # Step 2: upload the file as a single chunk
    with clip_path.open("rb") as video_file:
        video_data = video_file.read()

    upload_req = Request(
        upload_url,
        data=video_data,
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size),
            "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
        },
        method="PUT",
    )
    try:
        with urlopen(upload_req, timeout=600):
            pass
    except HTTPError as error:
        raise PublishError(
            f"TikTok video upload failed: {error.read().decode(errors='replace')}"
        ) from error

    # Step 3: poll for processing completion (up to 5 minutes)
    for _ in range(30):
        time.sleep(10)
        status_payload = json.dumps({"publish_id": publish_id}).encode()
        status_req = Request(
            _TIKTOK_STATUS_URL,
            data=status_payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            method="POST",
        )
        try:
            with urlopen(status_req, timeout=30) as resp:
                status_result = json.loads(resp.read())
        except HTTPError:
            continue

        post_status = status_result.get("data", {}).get("status", "")
        if post_status == "PUBLISH_COMPLETE":
            logger.info("Published to TikTok: %s", publish_id)
            return str(publish_id)
        if post_status in ("FAILED", "CANCELLED"):
            raise PublishError(f"TikTok publish failed with status: {post_status}")

    raise PublishError("TikTok publish timed out waiting for processing")


# ---------------------------------------------------------------------------
# Instagram (Reels via Content Publishing API)
# ---------------------------------------------------------------------------

def _publish_instagram(
    token_data: dict, clip_path: Path, title: str, description: str
) -> str:
    access_token = token_data.get("access_token", "")

    # Step 1: get the user's Instagram account ID
    user_url = f"{_INSTAGRAM_GRAPH_URL}/me?fields=id&access_token={access_token}"
    try:
        with urlopen(user_url, timeout=30) as resp:
            user_data = json.loads(resp.read())
    except HTTPError as error:
        raise PublishError(
            f"Instagram user lookup failed: {error.read().decode(errors='replace')}"
        ) from error

    user_id = user_data.get("id")
    if not user_id:
        raise PublishError("Instagram did not return a user ID")

    # Instagram requires a publicly accessible video URL — we need to upload to
    # a temporary public URL. For a local setup we use a pre-signed MinIO URL.
    # The caller (task) must pass the public video URL via description field hack.
    # We encode it as JSON in description: {"video_url": "...", "caption": "..."}
    try:
        extra = json.loads(description)
        video_url = extra["video_url"]
        caption = extra.get("caption", title)
    except (json.JSONDecodeError, KeyError) as error:
        raise PublishError(
            "Instagram publishing requires a public video URL. "
            "Pass {\"video_url\": \"...\", \"caption\": \"...\"} as description."
        ) from error

    # Step 2: create a media container
    container_url = f"{_INSTAGRAM_GRAPH_URL}/{user_id}/media"
    container_payload = urlencode(
        {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption[:2200],
            "access_token": access_token,
        }
    ).encode()
    container_req = Request(
        container_url,
        data=container_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(container_req, timeout=60) as resp:
            container_result = json.loads(resp.read())
    except HTTPError as error:
        raise PublishError(
            f"Instagram container creation failed: {error.read().decode(errors='replace')}"
        ) from error

    container_id = container_result.get("id")
    if not container_id:
        raise PublishError(f"Instagram did not return a container ID: {container_result}")

    # Step 3: poll until container is ready
    status_url = (
        f"{_INSTAGRAM_GRAPH_URL}/{container_id}"
        f"?fields=status_code&access_token={access_token}"
    )
    for _ in range(30):
        time.sleep(10)
        try:
            with urlopen(status_url, timeout=30) as resp:
                status_result = json.loads(resp.read())
        except HTTPError:
            continue
        code = status_result.get("status_code", "")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise PublishError("Instagram media container processing failed")
    else:
        raise PublishError("Instagram media container timed out")

    # Step 4: publish the container
    publish_url = f"{_INSTAGRAM_GRAPH_URL}/{user_id}/media_publish"
    publish_payload = urlencode(
        {"creation_id": container_id, "access_token": access_token}
    ).encode()
    publish_req = Request(
        publish_url,
        data=publish_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(publish_req, timeout=30) as resp:
            publish_result = json.loads(resp.read())
    except HTTPError as error:
        raise PublishError(
            f"Instagram publish failed: {error.read().decode(errors='replace')}"
        ) from error

    media_id = publish_result.get("id")
    if not media_id:
        raise PublishError(f"Instagram did not return a media ID: {publish_result}")
    logger.info("Published to Instagram: %s", media_id)
    return str(media_id)
