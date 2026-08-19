#!/usr/bin/env python3
"""Tests for verify_citations.py. Offline: never touches the network.

Fixtures reproduce the markup shapes of real CFP pages seen in this corpus -
NDSS (date-first list), EuroSec (label-first with a struck date), DSN
(date-first table), WWW (dates hidden in an HTML comment).
"""

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verify_citations as V  # noqa: E402

NDSS = """<html><body><h2>Important Dates</h2>
<ul>
<li>Wed, 23 April 2025: Paper submission deadline</li>
<li>Wed, 28 May 2025: Early reject notification</li>
<li>Wed, 2 July 2025: Author notification</li>
</ul>
<p>All deadlines are 11:59 PM AoE (UTC-12).</p></body></html>"""

EUROSEC = """<html><body><ul>
<li><strong>Paper Submission Deadline</strong>: <s>February 3, 2026</s>
    February 10, 2026 (AoE)</li>
<li><strong>Notification</strong>: March 5, 2026</li>
</ul></body></html>"""

DSN = """<html><body><table>
<tr><th>Date</th><th>Milestone</th></tr>
<tr><td>November 25, 2026</td><td>Abstract Submission Deadline</td></tr>
<tr><td>December 2, 2026</td><td>Paper Submission Deadline</td></tr>
<tr><td>January 26, 2027</td><td>Early Reject Notification</td></tr>
</table></body></html>"""

WWW_COMMENTED = """<html><body>
<!-- <p>Paper Submission Deadline: April 13, 2026</p> -->
<p>Paper Submission Deadline: October 7, 2025</p></body></html>"""


def fixture_dir(pages):
    d = Path(tempfile.mkdtemp())
    for url, html in pages.items():
        (d / f"{hashlib.sha1(url.encode()).hexdigest()}.html").write_text(
            html, encoding="utf-8")
    return d


def claim(value, *quotes):
    return {"value": value, "evidence": [{"quote": q} for q in quotes]}


def proposal(url, fields, action="upsert_manual", title="X", year=2026):
    return {"id": f"{action}:{title}:{year}", "action": action, "title": title,
            "year": year, "source_url": url, "fields": fields}


class Normalization(unittest.TestCase):
    def test_html_comments_are_stripped_before_tags(self):
        # The real WWW 2026 trap: superseded dates inside commented-out markup.
        text = V.strip_html(WWW_COMMENTED)
        self.assertNotIn("April 13", text)
        self.assertIn("October 7", text)

    def test_struck_text_is_dropped(self):
        text = V.strip_html(EUROSEC)
        self.assertNotIn("February 3", text)
        self.assertIn("February 10", text)

    def test_scripts_are_dropped(self):
        self.assertNotIn("2026-02-10", V.strip_html(
            '<html><script>{"deadline":"2026-02-10"}</script><p>hi</p></html>'))

    def test_entities_and_nbsp_collapse(self):
        self.assertEqual(V.flatten(V.strip_html("February&nbsp;10,<br>2026")), "february 10 2026")


class DateForms(unittest.TestCase):
    def test_spelled_month_variants(self):
        import datetime as dt
        forms = V.date_forms(dt.date(2026, 2, 10))
        for want in ("february 10 2026", "feb 10 2026", "10 february 2026"):
            self.assertIn(want, forms)

    def test_numeric_form_only_when_unambiguous(self):
        import datetime as dt
        # day 20 > 12, so 11/20/26 cannot be read the other way round
        self.assertIn("11 20 2026", V.date_forms(dt.date(2026, 11, 20)))
        # day 3 <= 12 is genuinely ambiguous and must not be generated
        self.assertNotIn("2 3 2026", V.date_forms(dt.date(2026, 2, 3)))


class Grounding(unittest.TestCase):
    def setUp(self):
        self.pages = {"https://ndss.example/cfp": NDSS,
                      "https://eurosec.example/": EUROSEC,
                      "https://dsn.example/cfc": DSN,
                      "https://www.example/": WWW_COMMENTED}
        self.dir = fixture_dir(self.pages)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.f = V.Fetcher(offline=True, fixtures=self.dir)

    def verify(self, p):
        return V.verify_proposal(p, self.f)

    def test_date_first_list_verifies(self):
        v = self.verify(proposal("https://ndss.example/cfp", {"deadline": claim(
            "2025-04-23 23:59", "Wed, 23 April 2025: Paper submission deadline")}))
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_label_first_with_struck_date_verifies_the_live_one(self):
        v = self.verify(proposal("https://eurosec.example/", {"deadline": claim(
            "2026-02-10 23:59", "Paper Submission Deadline: February 10, 2026 (AoE)")}))
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_superseded_struck_date_does_not_verify(self):
        # February 3 is struck through; adopting it would publish a stale value.
        v = self.verify(proposal("https://eurosec.example/", {"deadline": claim(
            "2026-02-03 23:59", "Paper Submission Deadline: February 3, 2026")}))
        self.assertEqual(v["status"], "UNCONFIRMED", v)

    def test_date_first_table_verifies_the_right_row(self):
        v = self.verify(proposal("https://dsn.example/cfc", {"deadline": claim(
            "2026-12-02 23:59", "December 2, 2026 Paper Submission Deadline")}))
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_notification_date_cannot_pass_as_a_deadline(self):
        # January 26 is the Early Reject Notification: 55 days late if adopted.
        v = self.verify(proposal("https://dsn.example/cfc", {"deadline": claim(
            "2027-01-26 23:59", "January 26, 2027 Early Reject Notification")}))
        self.assertEqual(v["status"], "UNCONFIRMED", v)

    def test_hallucinated_quote_fails(self):
        v = self.verify(proposal("https://ndss.example/cfp", {"deadline": claim(
            "2025-04-23 23:59", "Paper submission deadline: 23 April 2025 (AoE, firm)")}))
        self.assertEqual(v["status"], "UNCONFIRMED", v)

    def test_date_only_in_an_html_comment_fails(self):
        v = self.verify(proposal("https://www.example/", {"deadline": claim(
            "2026-04-13 23:59", "Paper Submission Deadline: April 13, 2026")}))
        self.assertEqual(v["status"], "UNCONFIRMED", v)

    def test_abstract_label_required_for_abstract_field(self):
        v = self.verify(proposal("https://dsn.example/cfc", {"abstract_deadline": claim(
            "2026-11-25 23:59", "November 25, 2026 Abstract Submission Deadline")}))
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_timezone_grounds_against_the_page(self):
        v = self.verify(proposal("https://ndss.example/cfp", {"timezone": claim(
            "AoE", "All deadlines are 11:59 PM AoE (UTC-12).")}))
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_no_evidence_is_unconfirmed(self):
        v = self.verify(proposal("https://ndss.example/cfp",
                                 {"deadline": {"value": "2025-04-23 23:59"}}))
        self.assertEqual(v["status"], "UNCONFIRMED", v)


class SourceAuthority(unittest.TestCase):
    def test_trackers_are_rejected(self):
        for url in ("https://ccfddl.github.io/conference/",
                    "https://sec-deadlines.github.io/",
                    "https://www.wikicfp.com/cfp/x",
                    "https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/x.yml"):
            ok, why = V.source_ok(url)
            self.assertFalse(ok, url)

    def test_archives_and_caches_are_rejected(self):
        for url in ("https://web.archive.org/web/2026/https://ndss.example/",
                    "https://webcache.googleusercontent.com/x"):
            self.assertFalse(V.source_ok(url)[0], url)

    def test_official_hosts_pass(self):
        for url in ("https://www.ndss-symposium.org/ndss2026/",
                    "https://www.ieee-security.org/Calendar/cfps/cfp-EuroSnP2027.html"):
            self.assertTrue(V.source_ok(url)[0], url)

    def test_rejected_source_short_circuits_before_fetching(self):
        f = V.Fetcher(offline=True, fixtures=None)
        v = V.verify_proposal(proposal("https://ccfddl.github.io/x",
                                       {"deadline": claim("2026-02-10 23:59", "x y z w")}), f)
        self.assertEqual(v["status"], "REJECTED_SOURCE")


class Unreachable(unittest.TestCase):
    def test_unreachable_is_never_verified(self):
        f = V.Fetcher(offline=True, fixtures=None)
        v = V.verify_proposal(proposal("https://nope.example/", {"deadline": claim(
            "2026-02-10 23:59", "Paper Submission Deadline: February 10, 2026")}), f)
        self.assertEqual(v["status"], "UNREACHABLE")
        self.assertFalse(v.get("accepted", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
