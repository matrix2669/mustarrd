"""
Unit coverage for the structured guide-metadata module (issue #421, step 1).

guide_metadata owns the complete list of structured fields Mustarrd keeps for a
guide program: subtitle, all categories, season/episode numbers, the raw
episode-number strings they were parsed from, and any external identifiers the
provider published. Parsing and gap-filling are pure, so they are pinned down
here without a database.
"""
import sys
import unittest
from pathlib import Path
from xml.etree.ElementTree import fromstring

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from guide_metadata import GuideMetadata, GuideMetadataColumns


def _programme(inner: str):
    return fromstring(
        '<programme start="20260608120000 +0000" stop="20260608130000 +0000" '
        f'channel="cnn.us">{inner}</programme>'
    )


class XmltvParsingTests(unittest.TestCase):
    def test_all_categories_kept_in_document_order(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme("<category>Series</category><category>Talk</category><category>Sports</category>")
        )
        self.assertEqual(list(meta.categories), ["Series", "Talk", "Sports"])

    def test_primary_category_is_first_category(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme("<category>Series</category><category>Sports</category>")
        )
        self.assertEqual(meta.primary_category, "Series")

    def test_duplicate_categories_collapsed_keeping_first_spelling(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme("<category>Sports</category><category>sports</category><category>SPORTS</category>")
        )
        self.assertEqual(list(meta.categories), ["Sports"])

    def test_blank_categories_ignored(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme("<category>   </category><category>News</category><category></category>")
        )
        self.assertEqual(list(meta.categories), ["News"])

    def test_subtitle_preserved(self):
        meta = GuideMetadata.from_xmltv_element(_programme("<sub-title>The One With The Test</sub-title>"))
        self.assertEqual(meta.subtitle, "The One With The Test")

    def test_blank_subtitle_treated_as_absent(self):
        meta = GuideMetadata.from_xmltv_element(_programme("<sub-title>   </sub-title>"))
        self.assertIsNone(meta.subtitle)

    def test_season_and_episode_from_onscreen_form(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme('<episode-num system="onscreen">S03E07</episode-num>')
        )
        self.assertEqual((meta.season_number, meta.episode_number), (3, 7))
        self.assertEqual(meta.episode_num_onscreen, "S03E07")

    def test_season_and_episode_from_onscreen_x_form(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme('<episode-num system="onscreen">3x07</episode-num>')
        )
        self.assertEqual((meta.season_number, meta.episode_number), (3, 7))

    def test_xmltv_ns_form_converted_to_one_based(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme('<episode-num system="xmltv_ns">2 . 4 . 0/1</episode-num>')
        )
        self.assertEqual((meta.season_number, meta.episode_number), (3, 5))
        self.assertEqual(meta.episode_num_xmltv, "2 . 4 . 0/1")

    def test_onscreen_preferred_when_both_forms_present(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme(
                '<episode-num system="onscreen">S03E07</episode-num>'
                '<episode-num system="xmltv_ns">9 . 9 . 0/1</episode-num>'
            )
        )
        self.assertEqual((meta.season_number, meta.episode_number), (3, 7))

    def test_xmltv_ns_used_when_onscreen_incomplete(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme(
                '<episode-num system="onscreen">Episode 7</episode-num>'
                '<episode-num system="xmltv_ns">1 . 2 . </episode-num>'
            )
        )
        self.assertEqual((meta.season_number, meta.episode_number), (2, 3))

    def test_malformed_episode_numbers_treated_as_absent(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme('<episode-num system="xmltv_ns">not . a . number</episode-num>')
        )
        self.assertIsNone(meta.season_number)
        self.assertIsNone(meta.episode_number)

    def test_unknown_season_marker_is_not_turned_into_season_zero(self):
        """A -1 season means "unknown"; -1 + 1 = 0 is not a real season."""
        meta = GuideMetadata.from_xmltv_element(
            _programme('<episode-num system="xmltv_ns">-1 . 4 . 0/1</episode-num>')
        )
        self.assertIsNone(meta.season_number)
        self.assertEqual(meta.episode_number, 5)

    def test_specials_season_zero_is_kept(self):
        """S00 is the specials season, not a failed parse."""
        meta = GuideMetadata.from_xmltv_element(
            _programme('<episode-num system="onscreen">S00E01</episode-num>')
        )
        self.assertEqual((meta.season_number, meta.episode_number), (0, 1))

    def test_numbers_are_never_mixed_between_the_two_forms(self):
        """A season from one system must not be paired with an episode from the other."""
        meta = GuideMetadata.from_xmltv_element(
            _programme(
                '<episode-num system="onscreen">Season 3</episode-num>'
                '<episode-num system="xmltv_ns">1 . 2 . 0/1</episode-num>'
            )
        )
        self.assertEqual((meta.season_number, meta.episode_number), (2, 3))

    def test_raw_episode_number_strings_preserved(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme('<episode-num system="onscreen">bananas</episode-num>')
        )
        self.assertEqual(meta.episode_num_onscreen, "bananas")
        self.assertIsNone(meta.season_number)

    def test_external_identifiers_stored(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme(
                '<episode-num system="dd_progid">EP012345670001</episode-num>'
                '<episode-num system="thetvdb.com">series/71663</episode-num>'
                '<episode-num system="themoviedb.org">movie/603</episode-num>'
                '<episode-num system="imdb.com">tt0133093</episode-num>'
            )
        )
        self.assertEqual(meta.gracenote_id, "EP012345670001")
        self.assertEqual(meta.tvdb_id, "series/71663")
        self.assertEqual(meta.tmdb_id, "movie/603")
        self.assertEqual(meta.imdb_id, "tt0133093")

    def test_empty_programme_yields_empty_metadata(self):
        meta = GuideMetadata.from_xmltv_element(_programme(""))
        self.assertEqual(meta, GuideMetadata())
        self.assertEqual(list(meta.categories), [])
        self.assertIsNone(meta.primary_category)


class GuideEntryParsingTests(unittest.TestCase):
    def test_reads_a_normalized_guide_entry(self):
        meta = GuideMetadata.from_guide_entry(
            {
                "subtitle": "Pilot",
                "categories": ["Series", "Drama"],
                "season_number": 1,
                "episode_number": 2,
                "tvdb_id": "series/1",
            }
        )
        self.assertEqual(meta.subtitle, "Pilot")
        self.assertEqual(list(meta.categories), ["Series", "Drama"])
        self.assertEqual((meta.season_number, meta.episode_number), (1, 2))
        self.assertEqual(meta.tvdb_id, "series/1")

    def test_single_category_string_becomes_the_category_list(self):
        meta = GuideMetadata.from_guide_entry({"category": "Sports"})
        self.assertEqual(list(meta.categories), ["Sports"])
        self.assertEqual(meta.primary_category, "Sports")

    def test_blank_and_unparsable_values_treated_as_absent(self):
        meta = GuideMetadata.from_guide_entry(
            {"subtitle": "  ", "category": "", "season_number": "n/a", "episode_number": None}
        )
        self.assertEqual(meta, GuideMetadata())


class SeasonEpisodeTests(unittest.TestCase):
    def test_both_numbers_present(self):
        meta = GuideMetadata(season_number=54, episode_number=173)
        self.assertEqual(meta.season_episode, (54, 173))

    def test_season_zero_is_a_real_season(self):
        meta = GuideMetadata(season_number=0, episode_number=2)
        self.assertEqual(meta.season_episode, (0, 2))

    def test_season_without_episode_is_nothing(self):
        self.assertIsNone(GuideMetadata(season_number=3).season_episode)

    def test_episode_without_season_is_nothing(self):
        self.assertIsNone(GuideMetadata(episode_number=7).season_episode)

    def test_neither_is_nothing(self):
        self.assertIsNone(GuideMetadata().season_episode)


class GapFillTests(unittest.TestCase):
    def test_missing_fields_taken_from_the_other_instance(self):
        live = GuideMetadata(subtitle="Pilot")
        stored = GuideMetadata(categories=("Series",), season_number=1, episode_number=2)

        merged = live.fill_gaps_from(stored)

        self.assertEqual(merged.subtitle, "Pilot")
        self.assertEqual(list(merged.categories), ["Series"])
        self.assertEqual((merged.season_number, merged.episode_number), (1, 2))

    def test_present_fields_are_never_overwritten(self):
        live = GuideMetadata(subtitle="Live Subtitle", categories=("News",), season_number=4)
        stored = GuideMetadata(subtitle="Stale Subtitle", categories=("Series",), season_number=9)

        merged = live.fill_gaps_from(stored)

        self.assertEqual(merged.subtitle, "Live Subtitle")
        self.assertEqual(list(merged.categories), ["News"])
        self.assertEqual(merged.season_number, 4)

    def test_season_zero_counts_as_present(self):
        live = GuideMetadata(season_number=0, episode_number=1)
        stored = GuideMetadata(season_number=9, episode_number=9)

        merged = live.fill_gaps_from(stored)

        self.assertEqual((merged.season_number, merged.episode_number), (0, 1))

    def test_filling_from_empty_metadata_changes_nothing(self):
        live = GuideMetadata(subtitle="Pilot", categories=("Series",))
        self.assertEqual(live.fill_gaps_from(GuideMetadata()), live)


class ProjectionTests(unittest.TestCase):
    def test_columns_round_trip_through_a_stored_row(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme(
                "<sub-title>Pilot</sub-title>"
                "<category>Series</category><category>Drama</category>"
                '<episode-num system="onscreen">S01E02</episode-num>'
                '<episode-num system="imdb.com">tt0133093</episode-num>'
            )
        )

        row = _Row(meta.to_columns())

        self.assertEqual(GuideMetadata.from_row(row), meta)

    def test_primary_category_written_to_the_existing_category_column(self):
        meta = GuideMetadata(categories=("Series", "Drama"))
        self.assertEqual(meta.to_columns()["category"], "Series")

    def test_legacy_row_with_only_a_category_column_reads_back_as_one_category(self):
        row = _Row({name: None for name in GuideMetadata.COLUMN_NAMES})
        row.category = "Sports"

        meta = GuideMetadata.from_row(row)

        self.assertEqual(list(meta.categories), ["Sports"])
        self.assertEqual(meta.primary_category, "Sports")

    def test_api_shape_exposes_every_field(self):
        meta = GuideMetadata.from_xmltv_element(
            _programme(
                "<sub-title>Pilot</sub-title>"
                "<category>Series</category><category>Drama</category>"
                '<episode-num system="onscreen">S01E02</episode-num>'
            )
        )

        payload = meta.to_api()

        self.assertEqual(payload["subtitle"], "Pilot")
        self.assertEqual(payload["categories"], ["Series", "Drama"])
        self.assertEqual(payload["season_number"], 1)
        self.assertEqual(payload["episode_number"], 2)
        self.assertEqual(payload["episode_num_onscreen"], "S01E02")
        self.assertIsNone(payload["tvdb_id"])

    def test_declared_columns_match_the_field_list(self):
        """The model columns and the field list cannot drift apart."""
        declared = {name for name in vars(GuideMetadataColumns) if not name.startswith("_")}
        self.assertEqual(declared, set(GuideMetadata.NEW_COLUMN_NAMES))

    def test_column_names_cover_every_declared_field(self):
        """The field list is the single source of truth for storage."""
        self.assertEqual(
            set(GuideMetadata().to_columns()), set(GuideMetadata.COLUMN_NAMES)
        )


class _Row:
    """Stand-in for an EPGProgram row."""

    def __init__(self, values: dict):
        for key, value in values.items():
            setattr(self, key, value)


if __name__ == "__main__":
    unittest.main()
