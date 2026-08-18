"""Character-level rules for filenames: separator mapping, deletions,
Windows reserved device names and Unicode normalization."""
import os
import sys
import unicodedata
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.file_namer import file_namer


class SeparatorMappingTests(unittest.TestCase):
    def test_slash_becomes_dash(self):
        self.assertEqual(file_namer.sanitize_filename("AC/DC"), "AC-DC")

    def test_backslash_becomes_dash(self):
        self.assertEqual(file_namer.sanitize_filename("AC\\DC"), "AC-DC")

    def test_colon_becomes_space_dash(self):
        self.assertEqual(
            file_namer.sanitize_filename("Star Wars: A New Hope"),
            "Star Wars - A New Hope",
        )

    def test_colon_without_trailing_space_still_reads_as_subtitle(self):
        self.assertEqual(file_namer.sanitize_filename("Alien:Romulus"), "Alien - Romulus")

    def test_dash_runs_collapse(self):
        self.assertEqual(file_namer.sanitize_filename("Show//Name"), "Show-Name")

    def test_trailing_separator_is_stripped(self):
        self.assertEqual(file_namer.sanitize_filename("Episode Title:"), "Episode Title")


class DeletedCharacterTests(unittest.TestCase):
    def test_question_mark_leaves_no_gap(self):
        self.assertEqual(file_namer.sanitize_filename("Who?"), "Who")

    def test_quotes_and_angle_brackets_deleted(self):
        self.assertEqual(
            file_namer.sanitize_filename('The "Best" <Show> Ever'),
            "The Best Show Ever",
        )

    def test_pipe_and_asterisk_deleted(self):
        self.assertEqual(file_namer.sanitize_filename("News|Update*"), "NewsUpdate")

    def test_control_chars_become_a_space_not_a_fusion(self):
        self.assertEqual(file_namer.sanitize_filename("Show\x00Name"), "Show Name")

    def test_legal_punctuation_is_preserved(self):
        self.assertEqual(
            file_namer.sanitize_filename("Rock & Roll, Vol. 2 (1999) #1!"),
            "Rock & Roll, Vol. 2 (1999) #1!",
        )


class ReservedDeviceNameTests(unittest.TestCase):
    def test_reserved_stem_is_suffixed(self):
        for stem in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9"):
            with self.subTest(stem=stem):
                self.assertEqual(file_namer.sanitize_filename(stem), stem + "_")

    def test_reserved_match_is_case_insensitive(self):
        self.assertEqual(file_namer.sanitize_filename("Aux"), "Aux_")

    def test_reserved_word_inside_a_title_is_untouched(self):
        self.assertEqual(file_namer.sanitize_filename("Aux Cord"), "Aux Cord")

    def test_com0_is_not_reserved(self):
        self.assertEqual(file_namer.sanitize_filename("COM0"), "COM0")


class UnicodeNormalizationTests(unittest.TestCase):
    def test_decomposed_accents_are_composed(self):
        decomposed = unicodedata.normalize("NFD", "Amélie")
        self.assertNotEqual(decomposed, "Amélie")
        self.assertEqual(file_namer.sanitize_filename(decomposed), "Amélie")

    def test_both_forms_land_on_the_same_filename(self):
        self.assertEqual(
            file_namer.sanitize_filename(unicodedata.normalize("NFD", "Amélie")),
            file_namer.sanitize_filename(unicodedata.normalize("NFC", "Amélie")),
        )


class TraversalComponentTests(unittest.TestCase):
    def test_parent_components_are_dropped_not_replaced(self):
        self.assertEqual(
            file_namer.sanitize_relative_path("../../Escape"),
            "Escape",
        )

    def test_current_dir_components_are_dropped(self):
        self.assertEqual(
            file_namer.sanitize_relative_path("./TV Shows/./Episode"),
            "TV Shows/Episode",
        )

    def test_path_of_only_traversal_falls_back(self):
        self.assertEqual(file_namer.sanitize_relative_path("../.."), "unknown-program")

    def test_leading_slash_stays_relative(self):
        self.assertEqual(
            file_namer.sanitize_relative_path("/TV Shows/Episode"),
            "TV Shows/Episode",
        )


if __name__ == "__main__":
    unittest.main()
