import unittest

from plagiarism_checker import PlagiarismChecker

SOURCE = (
    "Plagiarism is the representation of another person's language, thoughts, "
    "ideas, or expressions as one's own original work."
)


class PlagiarismCheckerTest(unittest.TestCase):
    def setUp(self):
        self.checker = PlagiarismChecker(":memory:")
        self.checker.add_document("Plagiarism", "https://example.com/plagiarism", SOURCE)
        self.checker.add_document(
            "Cats", "https://example.com/cats",
            "The cat is a small domesticated carnivorous mammal kept as a pet.",
        )

    def tearDown(self):
        self.checker.close()

    def test_copied_text_is_found_with_link(self):
        report = self.checker.check("Someone wrote: " + SOURCE.upper())
        self.assertTrue(report.found)
        self.assertEqual(report.matches[0].url, "https://example.com/plagiarism")
        self.assertEqual(len(report.matches), 1)

    def test_original_text_is_not_found(self):
        report = self.checker.check("My own essay about rivers, mountains and the weather in spring.")
        self.assertFalse(report.found)
        self.assertEqual(report.matches, [])

    def test_short_phrase_uses_exact_match(self):
        self.assertTrue(self.checker.check("domesticated carnivorous").found)
        self.assertFalse(self.checker.check("carnivorous domesticated").found)

    def test_readding_same_url_replaces_document(self):
        self.checker.add_document("Cats v2", "https://example.com/cats", "Completely different words here now.")
        self.assertEqual(len(self.checker.list_documents()), 2)
        self.assertFalse(self.checker.check("small domesticated carnivorous mammal kept").found)

    def test_empty_text(self):
        self.assertFalse(self.checker.check("  !!  ").found)


if __name__ == "__main__":
    unittest.main()
