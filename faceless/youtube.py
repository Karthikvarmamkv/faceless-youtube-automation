"""YouTube Data API v3 upload.

Authenticates via OAuth (installed-app flow), caches the token, and uploads a
rendered video as a PRIVATE (or unlisted) draft. See docs/SETUP.md for how to
create the OAuth client_secret.json.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config, env
from .jobs import Job
from .utils import log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = "token.json"


def get_service():
    """Return an authenticated YouTube API client, running OAuth if needed."""
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
    token_path = Path(TOKEN_FILE)
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secret_file = env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
            if not Path(secret_file).exists():
                raise RuntimeError(
                    f"OAuth client secret not found at '{secret_file}'. "
                    "Create one in Google Cloud Console (see docs/SETUP.md) and "
                    "set YOUTUBE_CLIENT_SECRET_FILE in .env."
                )
            flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload(job: Job, config: Config) -> str:
    """Upload the job's rendered video. Returns the YouTube video ID."""
    from googleapiclient.http import MediaFileUpload

    video_path = Path(job.video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Render not found: {video_path}")

    privacy = config.get("upload.privacy", "private")
    if privacy == "public":
        log(
            "upload.privacy is 'public' — this publishes immediately with no "
            "review. Strongly consider 'private' or 'unlisted'.",
            level="warn",
        )

    description = job.description
    footer = config.get("upload.default_footer", "")
    if footer:
        description = f"{description}\n{footer}"
    tags = list(job.tags)
    # Fold hashtags from metadata into the description tail if present.
    hashtags = job.extra.get("hashtags") or []
    if hashtags:
        description = f"{description}\n\n{' '.join(hashtags)}"

    body = {
        "snippet": {
            "title": job.title[:100] or "Untitled",
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": str(config.get("upload.category_id", "22")),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(config.get("upload.made_for_kids", False)),
        },
    }

    service = get_service()
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    log(f"Uploading '{job.title}' as {privacy}...", level="step")
    request = service.videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"  upload {int(status.progress() * 100)}%", level="info")

    video_id = response["id"]
    log(f"Uploaded as {privacy}: https://youtu.be/{video_id}", level="ok")
    return video_id
