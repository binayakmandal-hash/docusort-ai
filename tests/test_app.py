"""Sensitive-data finder, key details and the web API. No network needed."""
import io
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import fields  # noqa: E402
import sensitive  # noqa: E402


def aadhaar(base="38291045617"):
    return next(base + str(d) for d in range(10) if sensitive.verhoeff_ok(base + str(d)))


class SensitiveTest(unittest.TestCase):
    def test_checksums(self):
        self.assertTrue(sensitive.luhn_ok("4539148803436467"))
        self.assertFalse(sensitive.luhn_ok("4539148803436468"))
        a = aadhaar()
        self.assertTrue(sensitive.verhoeff_ok(a))
        self.assertFalse(sensitive.verhoeff_ok(a[:-1] + str((int(a[-1]) + 1) % 10)))

    def test_finds_and_masks(self):
        a = aadhaar()
        text = (f"Aadhaar {a[:4]} {a[4:8]} {a[8:]}, PAN ABCPD1234E, card 4539 1488 0343 6467, "
                "A/c No 50100234871265 IFSC HDFC0001875, call +91 98450 12345, mail priya.das@gmail.com, UPI priya@okaxis")
        kinds = [h["kind"] for h in sensitive.find(text)]
        self.assertEqual(kinds, ["aadhaar", "pan", "card", "account", "ifsc", "phone", "email", "upi"])
        red = sensitive.redact(text)
        for secret in ("ABCPD1234E", "4539 1488 0343", "50100234871265", "priya.das@", "98450 1"):
            self.assertNotIn(secret, red)
        self.assertIn(a[8:], red)  # last 4 digits stay, so the number is still recognisable

    def test_ignores_lookalikes(self):
        text = "Order 123456789012 shipped. Invoice total 1234567890123. Reference ABC1234567. Date 2026-10-08."
        self.assertEqual(sensitive.find(text), [])


class FieldsTest(unittest.TestCase):
    def test_receipt(self):
        text = "SUPER MART SDN BHD\nTAX INVOICE\nDate: 12/01/2019\nMilo 12.90\nSUBTOTAL 16.40\nGST 0.98\nTOTAL 17.38\nCASH 20.00\nCHANGE 2.62"
        got = {f["name"]: f["value"] for f in fields.extract("receipt_invoice", text)}
        self.assertEqual((got["Seller"], got["Date"], got["Total"]), ("SUPER MART SDN BHD", "12/01/2019", "17.38"))

    def test_contract(self):
        text = ('THIS DISTRIBUTOR AGREEMENT is made by and between Electric City Corp., a Delaware corporation ("Company") '
                'and Electric City of Illinois LLC ("Distributor") this 7th day of September, 1999.')
        got = {f["name"]: f["value"] for f in fields.extract("contract", text)}
        self.assertEqual(got["Parties"], "Electric City Corp; Electric City of Illinois LLC")
        self.assertEqual(got["Date"], "7th day of September, 1999")


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.client = app.app.test_client()

    def test_pages(self):
        for path in ("/", "/accuracy", "/privacy", "/terms"):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, path)
            self.assertNotIn("\u2014", res.get_data(as_text=True), path)
        self.assertEqual(self.client.get("/nope").status_code, 404)

    def test_batch_sort_and_zip(self):
        names = ["distributor-agreement.txt", "email-meeting.txt", "invoice.pdf", "resume-arjun-mehta.docx"]
        files = [(open(ROOT / "samples" / n, "rb"), n) for n in names] + [(io.BytesIO(b"MZ"), "virus.exe")]
        data = self.client.post("/api/sort", data={"files": files}, content_type="multipart/form-data").get_json()
        docs = {d["file"]: d for d in data["documents"]}
        self.assertEqual(docs["distributor-agreement.txt"]["label"], "contract")
        self.assertEqual(docs["email-meeting.txt"]["label"], "email")
        self.assertEqual(docs["invoice.pdf"]["label"], "receipt_invoice")
        self.assertEqual(docs["resume-arjun-mehta.docx"]["label"], "resume")
        self.assertFalse(docs["virus.exe"]["ok"])
        self.assertTrue(docs["invoice.pdf"]["sensitive"]["items"])
        z = zipfile.ZipFile(io.BytesIO(self.client.get(f"/api/batch/{data['batch']}.zip?redacted=1").data))
        listing = z.namelist()
        self.assertIn("Contract/distributor-agreement.txt", listing)
        self.assertIn("Receipt or invoice/invoice (redacted text).txt", listing)
        self.assertIn("Could not read/virus.exe", listing)
        self.assertIn("index.csv", listing)
        self.assertNotIn("50100234871265", z.read("Receipt or invoice/invoice (redacted text).txt").decode())

    def test_paste_and_redact(self):
        data = self.client.post("/api/sort", json={"text": "Subject: lunch\nHi team, lunch is at 1 pm in the cafeteria today. Call me on 98450 12345 if you're late. Thanks, Ravi"}).get_json()
        self.assertIsNone(data["batch"])
        self.assertEqual(data["documents"][0]["label"], "email")
        res = self.client.post("/api/redact", json={"text": "call 98450 12345", "name": "a.txt"})
        self.assertNotIn("98450 1", res.get_data(as_text=True))

    def test_bad_input(self):
        self.assertEqual(self.client.post("/api/sort", json={"text": "  "}).status_code, 400)
        self.assertEqual(self.client.get("/api/batch/../../etc.zip").status_code, 404)
        self.assertEqual(self.client.get("/api/batch/" + "0" * 32 + ".zip").status_code, 404)
        self.assertEqual(self.client.get("/samples/../app.py").status_code, 404)


if __name__ == "__main__":
    unittest.main()
