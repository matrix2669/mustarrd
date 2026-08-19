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

    def test_pipe_becomes_dash_because_it_separates_words(self):
        self.assertEqual(file_namer.sanitize_filename("News|Weather"), "News-Weather")

    def test_dash_runs_collapse(self):
        self.assertEqual(file_namer.sanitize_filename("Show//Name"), "Show-Name")

    def test_trailing_separator_is_stripped(self):
        self.assertEqual(file_namer.sanitize_filename("Episode Title:"), "Episode Title")


class LeadingAndTrailingDashTests(unittest.TestCase):
    """Dashes are legal on every filesystem, so real titles keep theirs."""

    def test_title_that_is_entirely_dashed_survives(self):
        self.assertEqual(file_namer.sanitize_filename("-30-"), "-30-")

    def test_dashed_title_after_a_template_separator_survives(self):
        self.assertEqual(
            file_namer.sanitize_filename("Sports Night - -30-"),
            "Sports Night - -30-",
        )

    def test_colon_absorbs_an_adjacent_separator(self):
        self.assertEqual(file_namer.sanitize_filename("Show - : The Movie"), "Show - The Movie")

    def test_real_hyphens_in_a_title_are_untouched(self):
        self.assertEqual(file_namer.sanitize_filename("9-1-1: Lone Star"), "9-1-1 - Lone Star")
        self.assertEqual(file_namer.sanitize_filename("Spider-Man"), "Spider-Man")


class DeletedCharacterTests(unittest.TestCase):
    def test_question_mark_leaves_no_gap(self):
        self.assertEqual(file_namer.sanitize_filename("Who?"), "Who")

    def test_quotes_and_angle_brackets_deleted(self):
        self.assertEqual(
            file_namer.sanitize_filename('The "Best" <Show> Ever'),
            "The Best Show Ever",
        )

    def test_asterisk_deleted(self):
        self.assertEqual(file_namer.sanitize_filename("M*A*S*H"), "MASH")

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

    def test_reserved_stem_with_extension_is_suffixed(self):
        self.assertEqual(file_namer.sanitize_filename("AUX.txt"), "AUX_.txt")
        self.assertEqual(file_namer.sanitize_filename("CON.log"), "CON_.log")
        self.assertEqual(file_namer.sanitize_filename("Aux.txt"), "Aux_.txt")

    def test_custom_ts_name_protects_reserved_stem_before_inner_extension(self):
        self.assertEqual(
            file_namer.sanitize_custom_filename("CON.log.ts"),
            "CON_.log.ts",
        )

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
