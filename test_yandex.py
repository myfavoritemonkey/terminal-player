"""Offline checks for the optional Yandex Music integration."""

from pathlib import Path
import runpy
import stat
import tempfile
import unittest
from unittest.mock import patch

try:
    from yandex_source import Collection, RemoteTrack, YandexCatalog, load_token, save_token, token_path
except ModuleNotFoundError as error:
    if error.name != "yandex_music":
        raise
    YandexCatalog = None


class FakeTrack:
    def __init__(self, identifier, title, duration_ms=120000, available=True):
        self.id = identifier
        self.title = title
        self.duration_ms = duration_ms
        self.available = available

    def artists_name(self):
        return ["Исполнитель"]


class FakeShort:
    def __init__(self, identifier, track=None):
        self.id = identifier
        self.track_id = str(identifier)
        self.track = track


@unittest.skipIf(YandexCatalog is None, "requires yandex-music")
class YandexTests(unittest.TestCase):
    def test_token_stays_outside_repository_and_is_private(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict("os.environ", {"XDG_STATE_HOME": temp}):
            token = type("Token", (), {"access_token": "test-only", "expires_in": 3600})()
            save_token(token)
            self.assertEqual(load_token(), "test-only")
            self.assertEqual(stat.S_IMODE(token_path().stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(token_path().parent.stat().st_mode), 0o700)

    def test_collection_order_and_stream_selection(self):
        source = FakeTrack(1, "Первый")
        fetched = FakeTrack(2, "Второй")

        class Client:
            def users_likes_tracks(self):
                return type("Likes", (), {"tracks": [FakeShort(1, source)]})()

            def users_playlists_list(self):
                return [type("Playlist", (), {"kind": 10, "title": "Мой список"})()]

            def users_playlists(self, kind):
                return type("Full", (), {"tracks": [FakeShort(2)]})()

            def tracks(self, identifiers):
                return [fetched]

        with patch("yandex_source.connect_client", return_value=Client()):
            catalog = YandexCatalog.connect()
        self.assertEqual([item.title for item in catalog.collections],
                         ["Мне нравится", "Мой список"])
        self.assertEqual(catalog.collections[1].tracks[0].title, "Исполнитель — Второй")

        class Variant:
            def __init__(self, codec, bitrate, url):
                self.codec = codec
                self.bitrate_in_kbps = bitrate
                self.url = url

            def get_direct_link(self):
                return self.url

        source.get_download_info = lambda: [Variant("aac", 320, "aac-url"),
                                            Variant("mp3", 128, "low-url"),
                                            Variant("mp3", 320, "high-url")]
        self.assertEqual(catalog.stream_url(catalog.collections[0].tracks[0]), "high-url")

    def test_yandex_player_uses_collection_labels(self):
        player_module = runpy.run_path(str(Path(__file__).with_name("player")))
        YandexPlayer = player_module["YandexPlayer"]
        song = RemoteTrack("Исполнитель — Песня", 120.0, FakeTrack(1, "Песня"))

        class Catalog:
            collections = [Collection("Мне нравится", [song])]

            def stream_url(self, track):
                return "https://example.test/audio.mp3"

        player = YandexPlayer(Catalog())
        self.assertEqual(player.title_for(0), "Мне нравится / Исполнитель — Песня")
        self.assertEqual(player.label_for(player.rows[0].path), "Мне нравится")
        self.assertEqual(player.media_for(0), ("https://example.test/audio.mp3", 120.0))
        with patch("subprocess.Popen") as launch:
            launch.return_value.poll.return_value = 0
            player.play(0)
            self.assertEqual(launch.call_args.args[0][-1], "https://example.test/audio.mp3")
            player.stop()


if __name__ == "__main__":
    unittest.main()
