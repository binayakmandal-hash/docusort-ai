"""Reader and classifier tests. They use the committed model; no network needed."""
import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import classifier  # noqa: E402
import reader  # noqa: E402

SAMPLES = {
    "receipt_invoice": "TAX INVOICE\nSUPER MART SDN BHD\nQty Item Price\n2 Milo 3 in 1 12.90\n1 Bread 3.50\nSUBTOTAL 16.40\nGST 6% 0.98\nTOTAL 17.38\nCASH 20.00\nCHANGE 2.62\nThank you, please come again",
    "resume": "PROFESSIONAL SUMMARY\nSoftware engineer with 4 years of experience in Python and SQL.\nSKILLS\nPython, Django, PostgreSQL, Docker\nEXPERIENCE\nBackend Developer, Acme Corp, 2021 - present\nEDUCATION\nB.Tech in Computer Science",
    "contract": "THIS AGREEMENT is made and entered into as of the Effective Date by and between the Company and the Distributor. 1. Term. This Agreement shall commence on the Effective Date and continue for a period of three years unless terminated in accordance with Section 9. 2. Governing Law. This Agreement shall be governed by the laws of the State of Delaware.",
    "medical_report": "CHIEF COMPLAINT: Chest pain.\nHISTORY OF PRESENT ILLNESS: The patient is a 54-year-old male who presents with substernal chest pain radiating to the left arm.\nPHYSICAL EXAMINATION: Blood pressure 150/90, pulse 96.\nASSESSMENT AND PLAN: Rule out myocardial infarction. ECG and troponins ordered.",
}


class ReaderTest(unittest.TestCase):
    def test_text_file(self):
        doc = reader.read("note.txt", b"Hello  world\r\n\r\n\r\nsecond   line")
        self.assertEqual((doc.kind, doc.text), ("text", "Hello world\n\nsecond line"))

    def test_docx(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Invoice &amp; receipt</w:t></w:r></w:p>"
                                             "<w:p><w:r><w:t>Total 100</w:t></w:r></w:p></w:body></w:document>")
        doc = reader.read("a.docx", buf.getvalue())
        self.assertEqual(doc.text, "Invoice & receipt\nTotal 100")

    def test_rejects_unknown_and_large_files(self):
        with self.assertRaises(reader.ReadError):
            reader.read("a.exe", b"MZ")
        with self.assertRaises(reader.ReadError):
            reader.read("a.txt", b"x" * (reader.MAX_BYTES + 1))
        with self.assertRaises(reader.ReadError):
            reader.read("broken.docx", b"not a zip")


class ClassifierTest(unittest.TestCase):
    def test_samples(self):
        for label, text in SAMPLES.items():
            r = classifier.classify(text)
            self.assertEqual(r["label"], label, text[:40])
            self.assertAlmostEqual(sum(p["probability"] for p in r["probabilities"]), 1.0, places=2)

    def test_explanation_terms_come_from_the_document(self):
        r = classifier.classify(SAMPLES["receipt_invoice"])
        self.assertTrue(r["explanation"]["for"])
        for t in r["explanation"]["for"]:
            for word in t["term"].split():
                self.assertIn(word, SAMPLES["receipt_invoice"].lower())

    def test_metrics_file_matches_model_classes(self):
        m = classifier.metrics()
        self.assertEqual(sorted(m["dataset"]["per_class"]), sorted(classifier.model().classes_))


if __name__ == "__main__":
    unittest.main()
