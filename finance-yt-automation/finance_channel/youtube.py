"""YouTube Data API v3 upload (private/unlisted drafts by default).

Authenticates via OAuth (installed-app flow), caches the token, uploads the
video, sets the synthetic-media disclosure, and attaches the custom thumbnail
when the channel is allowed to use custom thumbnails.
"""

from __future__ import annotations

from pathlib import Path

from .config import ROOT, Config, env
from .jobs import Job
from .utils import log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = ROOT / "token.json"


def get_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            "Google API client not installed. `pip install google-api-python-client "
            "google-auth-oauthlib google-auth-httplib2`."
        ) from e

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secret = Path(env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json"))
            if not secret.is_absolute():
                secret = ROOT / secret
            if not secret.exists():
                raise RuntimeError(
                    f"OAuth client secret not found at '{secret}'. See docs/SETUP.md."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def upload(job: Job, config: Config) -> str:
    """Upload the job's video. Returns the YouTube video ID."""
    from googleapiclient.http import MediaFileUpload

    video = Path(job.video_path)
    if not video.exists():
        raise FileNotFoundError(f"Render not found: {video}")
    if job.review_status == "blocked":
        raise RuntimeError(f"Job {job.id} was blocked by the compliance review; not uploading.")

    privacy = config.get("upload.privacy", "private")
    if privacy == "public":
        log("upload.privacy is 'public': this publishes with no human review. "
            "Finance content should be reviewed first.", level="warn")

    body = {
        "snippet": {
            "title": (job.title or "Untitled")[:100],
            "description": job.description[:5000],
            "tags": job.tags[:30],
            "categoryId": str(config.get("upload.category_id", "27")),
            "defaultLanguage": config.get("channel.language", "en"),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(config.get("upload.made_for_kids", False)),
            "containsSyntheticMedia": bool(config.get("upload.contains_synthetic_media", True)),
        },
    }

    service = get_service()
    media = MediaFileUpload(str(video), chunksize=-1, resumable=True)
    log(f"Uploading '{job.title}' as {privacy}...", level="step")
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"  upload {int(status.progress() * 100)}%", level="info")
    video_id = response["id"]
    log(f"Uploaded as {privacy}: https://youtu.be/{video_id}", level="ok")

    thumb = Path(job.thumbnail_path) if job.thumbnail_path else None
    if thumb and thumb.exists() and job.video_format == "long":
        try:
            service.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb))).execute()
            log("Custom thumbnail set.", level="ok")
        except Exception as e:  # unverified channels can't set custom thumbnails
            log(f"Thumbnail not set ({e}). Verify the channel to enable custom thumbnails.",
                level="warn")
    return video_id
