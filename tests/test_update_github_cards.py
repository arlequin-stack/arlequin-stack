import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from scripts.update_github_cards import (
    CARD_HEIGHT,
    CARD_WIDTH,
    ProfileData,
    language_breakdown,
    load_fixture,
    write_cards,
)


ROOT = Path(__file__).resolve().parents[1]


class CardGeneratorTests(unittest.TestCase):
    def test_fixture_aggregates_owned_non_fork_languages(self):
        data = load_fixture(ROOT / "tests/fixtures/profile.json", "arlequin-stack")
        self.assertEqual(data.stars, 10)
        self.assertEqual(data.languages["Python"], 4000)
        self.assertEqual(data.repositories, 5)

    def test_more_than_four_languages_are_grouped_as_other(self):
        result = language_breakdown({"A": 50, "B": 20, "C": 15, "D": 10, "E": 5})
        self.assertEqual([name for name, _ in result], ["A", "B", "C", "Other"])
        self.assertAlmostEqual(sum(value for _, value in result), 100.0)

    def test_generated_cards_are_valid_equal_size_svg(self):
        data = ProfileData(
            username="name<&>",
            commits=12,
            stars=3,
            pull_requests=4,
            repositories=5,
            languages={"C++": 10, "HTML": 30},
            updated_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_cards(data, output)
            for filename in ("statistics.svg", "languages.svg"):
                svg = output / filename
                root = ET.parse(svg).getroot()
                self.assertEqual(root.attrib["width"], str(CARD_WIDTH))
                self.assertEqual(root.attrib["height"], str(CARD_HEIGHT))
                self.assertIn("LIVE PUBLIC DATA", svg.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
