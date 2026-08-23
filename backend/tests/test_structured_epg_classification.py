import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.epg_service import EPGService


class StructuredEpgClassificationTests(unittest.TestCase):
    def setUp(self):
        self.service = EPGService()

    def classify(self, program, channel_category=""):
        return self.service.detect_program_type(
            program,
            {"name": "Test Channel", "category_name": channel_category},
        )

    def test_sports_series_is_tv_show(self):
        self.assertEqual(
            self.classify({
                "title": "30 for 30",
                "categories": ["Sports", "Series", "Documentary"],
                "season_number": 1,
                "episode_number": 22,
            }),
            "tv_show",
        )

    def test_sports_recap_series_is_tv_show(self):
        self.assertEqual(
            self.classify({
                "title": "MLB Tonight",
                "categories": ["Sports", "Series"],
                "season_number": 0,
                "episode_number": 105,
            }),
            "tv_show",
        )

    def test_nfl_game_is_sports_even_with_external_series_ids(self):
        self.assertEqual(
            self.classify({
                "title": "NFL Football",
                "subtitle": "Chicago Bears at Cincinnati Bengals",
                "categories": ["Sports", "Reality"],
                "season_number": 2026,
                "episode_number": 1,
                "gracenote_id": "EP00003128.5663",
                "tvdb_id": "series/341356",
                "tmdb_id": "series/76013",
            }),
            "sports",
        )

    def test_soccer_match_is_sports_event(self):
        self.assertEqual(
            self.classify({
                "title": "Premier League Soccer",
                "subtitle": "Manchester City vs. Bournemouth",
                "categories": ["Sports"],
            }),
            "sports",
        )

    def test_henry_v_is_not_a_sports_match(self):
        self.assertEqual(self.classify({"title": "Henry V"}), "other")

    def test_generic_program_on_sports_channel_falls_back_to_sports(self):
        self.assertEqual(
            self.classify({"title": "Regional Sports Showcase"}, "Sports"),
            "sports",
        )

    def test_sports_channel_filler_is_not_sports(self):
        for title in ("Paid Programming", "To Be Announced", "TBA", "Off Air"):
            with self.subTest(title=title):
                self.assertEqual(
                    self.classify({"title": title, "categories": ["Sports"]}, "Sports"),
                    "other",
                )

    def test_news_sports_program_is_news(self):
        self.assertEqual(
            self.classify({
                "title": "College Football Live",
                "categories": ["News", "Sports"],
            }),
            "news",
        )

    def test_series_category_after_first_category_is_tv(self):
        self.assertEqual(
            self.classify({
                "title": "Speed Racer",
                "category": "Family",
                "categories": ["Family", "Series", "Animation"],
                "season_number": 1,
                "episode_number": 27,
            }),
            "tv_show",
        )

    def test_movie_metadata_is_movie(self):
        self.assertEqual(
            self.classify({
                "title": "Out of the Furnace",
                "categories": ["Movie", "Thriller", "Drama"],
                "gracenote_id": "MV00481528.0000",
                "tmdb_id": "movie/164457",
            }),
            "movie",
        )

    def test_external_series_id_is_tv_when_not_sports_event(self):
        self.assertEqual(
            self.classify({
                "title": "My Three Sons",
                "categories": ["Comedy", "Family"],
                "tvdb_id": "series/71404",
                "tmdb_id": "series/1530",
            }),
            "tv_show",
        )


if __name__ == "__main__":
    unittest.main()
