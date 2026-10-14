"""Small behavior checks that do not require an audio device."""

from pathlib import Path
import curses
import runpy
import tempfile
import unittest
from unittest.mock import patch


module = runpy.run_path(str(Path(__file__).with_name("player")))
Player = module["Player"]
songs_in = module["songs_in"]
render = module["render"]
configure_folder_colors = module["configure_folder_colors"]
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


class FakeScreen:
    def __init__(self):
        self.lines = {}
        self.attributes = {}

    def erase(self):
        self.lines.clear()
        self.attributes.clear()

    def getmaxyx(self):
        return 20, 80

    def addnstr(self, row, column, value, width, attributes):
        self.lines[row] = value[:width]
        self.attributes[row] = attributes

    def refresh(self):
        pass


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

    def test_nested_folders_can_collapse_without_changing_playback_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ["Album/Disc 2/track10.mp3", "Album/Disc 2/track2.mp3",
                         "Album/Disc 1/track1.mp3", "other.ogg"]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            player = Player(root, songs_in(root))
            self.assertEqual([row.path.name for row in player.rows],
                             ["Album", "Disc 1", "track1.mp3", "Disc 2",
                              "track2.mp3", "track10.mp3", "other.ogg"])
            screen = FakeScreen()
            render(screen, player)
            self.assertTrue(any("▾ Album/" in line for line in screen.lines.values()))

            disc = root / "Album" / "Disc 2"
            player.selected = next(i for i, row in enumerate(player.rows) if row.path == disc)
            player.activate_selected()
            self.assertEqual([row.path.name for row in player.rows],
                             ["Album", "Disc 1", "track1.mp3", "Disc 2", "other.ogg"])
            self.assertEqual(player.rows[player.selected].path, disc)
            render(screen, player)
            self.assertTrue(any("▸ Disc 2/" in line for line in screen.lines.values()))
            self.assertEqual([song.name for song in player.songs],
                             ["track1.mp3", "track2.mp3", "track10.mp3", "other.ogg"])

            with patch.dict(Player.play.__globals__, {"duration_of": lambda path: None}), \
                 patch("subprocess.Popen", return_value=FakeProcess()):
                player.play(1)
                self.assertEqual(player.rows[player.selected].path, disc)
                player.next()
                self.assertEqual(player.current, 2)
                self.assertEqual(player.rows[player.selected].path, disc)
                player.stop()

            player.activate_selected()
            self.assertEqual(player.rows[player.selected].path, disc)
            self.assertIn("track2.mp3", [row.path.name for row in player.rows])

    def test_muted_colors_group_tracks_by_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ["Album 1/song.mp3", "Album 2/song.mp3"]:
                path = root / name
                path.parent.mkdir(parents=True)
                path.touch()
            player = Player(root, songs_in(root))
            with patch.object(curses, "has_colors", return_value=True), \
                 patch.object(curses, "start_color"), \
                 patch.object(curses, "use_default_colors"), \
                 patch.object(curses, "init_pair"), \
                 patch.object(curses, "color_pair", side_effect=lambda pair: pair << 8), \
                 patch.object(curses, "COLORS", 256, create=True), \
                 patch.object(curses, "COLOR_PAIRS", 32, create=True):
                configure_folder_colors(player)
            first = player.folder_styles[root / "Album 1"]
            second = player.folder_styles[root / "Album 2"]
            self.assertNotEqual(first, second)
            screen = FakeScreen()
            render(screen, player)
            for folder, style in [("Album 1", first), ("Album 2", second)]:
                folder_row = next(row for row, line in screen.lines.items()
                                  if f"▾ {folder}/" in line)
                song_row = folder_row + 1
                self.assertEqual(screen.attributes[folder_row] & ~curses.A_REVERSE, style)
                self.assertEqual(screen.attributes[song_row], style)


if __name__ == "__main__":
    unittest.main()
