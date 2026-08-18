"""VOD naming shares sanitize_filename, so the character rules apply to movie
filenames and to the show/season folders series episodes are filed under."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.vod_namer import movie_output_path, series_episode_output_path


class MovieNameTests(unittest.TestCase):
    def test_colon_in_a_movie_title_becomes_a_separator(self):
        self.assertEqual(
            movie_output_path("/vod", "Star Wars: A New Hope", 1977, "mkv"),
            "/vod/Star Wars - A New Hope (1977).mkv",
        )

    def test_slash_in_a_movie_title_does_not_create_a_folder(self):
        self.assertEqual(
            movie_output_path("/vod", "Frost/Nixon", 2008, "mp4"),
            "/vod/Frost-Nixon (2008).mp4",
        )


class SeriesFolderTests(unittest.TestCase):
    def test_slash_in_a_show_name_stays_one_folder(self):
        path = series_episode_output_path("/vod", "AC/DC", 1, 2, "Thunderstruck", "mkv")
        self.assertEqual(
            path,
            "/vod/AC-DC/Season 01/S01E02 - AC-DC - Thunderstruck.mkv",
        )

    def test_reserved_show_name_gets_a_usable_folder(self):
        # A folder literally named "Aux" cannot be created on Windows or an
        # SMB share, which would break the whole series.
        path = series_episode_output_path("/vod", "Aux", 2, 3, None, "mp4")
        self.assertEqual(path, "/vod/Aux_/Season 02/S02E03 - Aux_.mp4")

    def test_colon_in_a_show_name_becomes_a_separator(self):
        path = series_episode_output_path("/vod", "Star Trek: Picard", 1, 1, "Remembrance", "mkv")
        self.assertEqual(
            path,
            "/vod/Star Trek - Picard/Season 01/S01E01 - Star Trek - Picard - Remembrance.mkv",
        )


if __name__ == "__main__":
    unittest.main()
