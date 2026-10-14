"""Account library and streaming URLs for the optional Yandex Music mode."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from yandex_music import Client
from yandex_music.exceptions import UnauthorizedError


@dataclass(frozen=True)
class RemoteTrack:
    title: str
    duration: float | None
    model: Any


@dataclass(frozen=True)
class Collection:
    title: str
    tracks: list[RemoteTrack]


def token_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "player" / "yandex_auth.json"


def load_token() -> str | None:
    try:
        data = json.loads(token_path().read_text(encoding="utf-8"))
        if float(data["expires_at"]) > time.time() + 60:
            return str(data["access_token"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save_token(token: Any) -> None:
    path = token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".yandex_auth_", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump({"access_token": token.access_token,
                       "expires_at": time.time() + (token.expires_in or 3600)}, output)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def authorize() -> Client:
    def show_code(code: Any) -> None:
        print(f"Откройте {code.verification_url} и введите код {code.user_code}", flush=True)

    token = Client().device_auth(on_code=show_code)
    save_token(token)
    return Client(token.access_token).init()


def connect_client() -> Client:
    token = load_token()
    if token:
        try:
            return Client(token).init()
        except UnauthorizedError:
            pass
    return authorize()


class YandexCatalog:
    def __init__(self, client: Client, collections: list[Collection]):
        self.client = client
        self.collections = collections

    @classmethod
    def connect(cls) -> YandexCatalog:
        client = connect_client()
        print("Загружаю «Мне нравится» и плейлисты...", flush=True)
        collections = []

        liked = client.users_likes_tracks()
        if liked is not None and liked.tracks:
            tracks = cls._tracks(client, liked.tracks)
            if tracks:
                collections.append(Collection("Мне нравится", tracks))

        for playlist in client.users_playlists_list():
            if playlist.kind is None:
                continue
            full = client.users_playlists(playlist.kind)
            if full is None or isinstance(full, list):
                continue
            tracks = cls._tracks(client, full.tracks or [])
            if tracks:
                collections.append(Collection(playlist.title or "Плейлист", tracks))

        return cls(client, collections)

    @staticmethod
    def _tracks(client: Client, short_tracks: list[Any]) -> list[RemoteTrack]:
        missing = [short.track_id for short in short_tracks
                   if short.track is None or short.track.title is None]
        fetched = {}
        for start in range(0, len(missing), 100):
            for track in client.tracks(missing[start:start + 100]):
                fetched[str(track.id)] = track

        tracks = []
        for short in short_tracks:
            track = short.track if short.track is not None and short.track.title else fetched.get(str(short.id))
            if track is None or track.available is False:
                continue
            artists = ", ".join(track.artists_name())
            title = f"{artists} — {track.title}" if artists else (track.title or str(track.id))
            duration = track.duration_ms / 1000 if track.duration_ms else None
            tracks.append(RemoteTrack(title, duration, track))
        return tracks

    def stream_url(self, track: RemoteTrack) -> str:
        variants = track.model.get_download_info()
        mp3 = [variant for variant in variants if variant.codec == "mp3"]
        if not mp3:
            raise RuntimeError("для этого трека нет доступного MP3-потока")
        best = max(mp3, key=lambda variant: variant.bitrate_in_kbps)
        url = best.get_direct_link()
        if not url:
            raise RuntimeError("сервис не вернул ссылку на аудио")
        return url
