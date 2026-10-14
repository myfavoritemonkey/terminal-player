"""Small behavior checks that do not require an audio device."""

from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


module = runpy.run_path(str(Path(__file__).with_name("player")))
Player = module["Player"]
songs_in = module["songs_in"]
last_playlist = module["last_playlist"]
remember_playlist = module["remember_playlist"]


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.signals = []

    def poll(self):
        return self.exit_code

    def send_signal(self, value):
        self.signals.append(value)

    def terminate(self):
        self.exit_code = 0

    def wait(self, timeout=None):
        return self.exit_code


class PlayerTests(unittest.TestCase):
    def test_recursive_natural_order_and_last_playlist(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            music = root / "music"
            (music / "Disc 2").mkdir(parents=True)
            for name in ["track10.mp3", "track2.flac", "notes.txt"]:
                (music / "Disc 2" / name).touch()
            (music / "Disc 1").mkdir()
            (music / "Disc 1" / "track1.ogg").touch()
            self.assertEqual([p.name for p in songs_in(music)],
                             ["track1.ogg", "track2.flac", "track10.mp3"])
            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                remember_playlist(music)
                self.assertEqual(last_playlist(), music)

    def test_seek_pause_and_automatic_next(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            songs = [root / "1.mp3", root / "2.mp3"]
            for song in songs:
                song.touch()
            processes = []

            def launch(*args, **kwargs):
                proc = FakeProcess()
                processes.append((args[0], proc))
                return proc

            with patch.dict(Player.play.__globals__, {"duration_of": lambda path: 120.0}), \
                 patch("subprocess.Popen", side_effect=launch):
                player = Player(root, songs)
                player.play(0)
                player.toggle_pause()
                self.assertTrue(player.paused)
                player.seek(10)
                self.assertTrue(player.paused)
                self.assertIn("-ss", processes[-1][0])
                self.assertEqual(processes[-1][0][-1], str(songs[0]))
                player.toggle_pause()
                processes[-1][1].exit_code = 0
                player.tick()
                self.assertEqual(player.current, 1)
                player.stop()


if __name__ == "__main__":
    unittest.main()
