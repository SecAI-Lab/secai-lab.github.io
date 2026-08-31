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
from unittest import mock

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


class PessimisticByDefault(unittest.TestCase):
    """The gate must start at "not checked" and earn VERIFIED.

    It used to start at VERIFIED and only degrade, so every field it could not
    check counted as a pass: a note-only proposal with a fabricated quote came
    back accepted against a page containing none of its text.
    """

    def setUp(self):
        self.dir = fixture_dir({"https://x.example/": "<p>Nothing relevant here.</p>"})
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.f = V.Fetcher(offline=True, fixtures=self.dir)

    def v(self, fields):
        return V.verify_proposal(proposal("https://x.example/", fields), self.f)

    def test_uncheckable_fields_are_not_verified(self):
        for label, fields in (
            ("note", {"note": claim("anything", "totally made up text here")}),
            ("link", {"link": claim("https://y.example", "totally made up text here")}),
            ("TBA deadline", {"deadline": claim("TBA", "totally made up text here")}),
        ):
            with self.subTest(label):
                self.assertEqual(self.v(fields)["status"], "UNCHECKED")

    def test_a_checked_field_still_verifies(self):
        d = fixture_dir({"https://y.example/":
                         "<li>Paper Submission Deadline: February 10, 2026</li>"})
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        f = V.Fetcher(offline=True, fixtures=d)
        v = V.verify_proposal(proposal("https://y.example/", {"deadline": claim(
            "2026-02-10 23:59", "Paper Submission Deadline: February 10, 2026")}), f)
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_verified_plus_unchecked_is_not_globally_verified(self):
        d = fixture_dir({"https://y.example/":
                         "<li>Paper Submission Deadline: February 10, 2026</li>"})
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        f = V.Fetcher(offline=True, fixtures=d)
        v = V.verify_proposal(proposal("https://y.example/", {
            "deadline": claim(
                "2026-02-10 23:59", "Paper Submission Deadline: February 10, 2026"),
            "note": claim("Free-form text has no checkable surface form", "invented quote"),
        }), f)
        self.assertEqual(v["fields"]["deadline"]["status"], "VERIFIED", v)
        self.assertEqual(v["fields"]["note"]["status"], "UNCHECKED", v)
        self.assertEqual(v["status"], "UNCHECKED", v)

    def test_verified_plus_failed_is_not_globally_verified(self):
        d = fixture_dir({"https://y.example/":
                         "<li>Paper Submission Deadline: February 10, 2026</li>"})
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        f = V.Fetcher(offline=True, fixtures=d)
        v = V.verify_proposal(proposal("https://y.example/", {
            "deadline": claim(
                "2026-02-10 23:59", "Paper Submission Deadline: February 10, 2026"),
            "place": claim("Lisbon, Portugal", "The event takes place in Lisbon, Portugal"),
        }), f)
        self.assertEqual(v["fields"]["deadline"]["status"], "VERIFIED", v)
        self.assertEqual(v["fields"]["place"]["status"], "UNCONFIRMED", v)
        self.assertEqual(v["status"], "UNCONFIRMED", v)

    def test_one_bad_field_sinks_the_proposal(self):
        v = self.v({"deadline": claim("2026-02-10 23:59", "Paper Submission Deadline: "
                                                          "February 10, 2026")})
        self.assertEqual(v["status"], "UNCONFIRMED", v)


class AbsenceClaims(unittest.TestCase):
    """A deletion says a field is NOT there. Unfalsifiable in general, but
    decidable within the block the auditor cited - so the block must be real."""

    BLOCK = ("<h2>Important Dates</h2><ul>"
             "<li>Wed, 6 August 2025: Paper submission deadline</li>"
             "<li>Wed, 2 July 2025: Author notification</li></ul>")
    QUOTE = ("Wed, 6 August 2025: Paper submission deadline "
             "Wed, 2 July 2025: Author notification")

    def toks(self, html):
        return V.tokens(V.strip_html(html))

    def test_real_block_without_the_field_establishes_absence(self):
        ok, why = V.verify_absence(self.toks(self.BLOCK), "abstract_deadline", self.QUOTE)
        self.assertTrue(ok, why)

    def test_block_containing_the_field_refuses(self):
        html = self.BLOCK.replace("</ul>", "<li>Wed, 30 July 2025: Abstract registration</li></ul>")
        ok, why = V.verify_absence(self.toks(html), "abstract_deadline",
                                   self.QUOTE + " Wed, 30 July 2025: Abstract registration")
        self.assertFalse(ok, why)

    def test_primary_deadline_phrase_with_a_date_cannot_prove_its_absence(self):
        ok, why = V.verify_absence(self.toks(self.BLOCK), "deadline", self.QUOTE)
        self.assertFalse(ok, why)
        self.assertIn("absence not established", why)

    def test_fabricated_block_refuses(self):
        ok, why = V.verify_absence(self.toks(self.BLOCK), "abstract_deadline",
                                   "THIS TEXT IS NOT ON THE PAGE AT ALL ANYWHERE EVER")
        self.assertFalse(ok, why)
        self.assertIn("not on the page", why)

    def test_fragment_is_not_a_block(self):
        ok, why = V.verify_absence(self.toks(self.BLOCK), "abstract_deadline", "Important Dates")
        self.assertFalse(ok, why)


class TrackHeadings(unittest.TestCase):
    """Rows that are identical except for the date, distinguished only by the
    heading above them.

    ACNS 2027 is the real page: paper, poster and workshop sections each read
    "Submission deadline: <date> AoE". The quote alone cannot say which track it
    belongs to, so the poster date verified as the paper deadline at coverage
    1.0 - a false positive, the direction that publishes a wrong deadline.
    """

    PAGE = ("<h3>Paper Submissions Cycle 1</h3>"
            "<p>Submission deadline: 24 September 2026 AoE</p>"
            "<p>Author notification: 18 November 2026</p>"
            "<h3>Paper Submissions Cycle 2</h3>"
            "<p>Submission deadline: 21 January 2027 AoE</p>"
            "<h3>Poster Submissions</h3>"
            "<p>Submission deadline: 12 March 2027 AoE</p>"
            "<h3>Workshop Proposals</h3>"
            "<p>Submission deadline: 22 September 2026 AoE</p>")

    def setUp(self):
        self.dir = fixture_dir({"https://acns.example/": self.PAGE})
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.f = V.Fetcher(offline=True, fixtures=self.dir)

    def v(self, value, quote):
        return V.verify_proposal(proposal("https://acns.example/",
                                          {"deadline": claim(value, quote)}), self.f)["status"]

    def test_the_paper_row_verifies(self):
        self.assertEqual(self.v("2026-09-24 23:59",
                                "Submission deadline: 24 September 2026 AoE"), "VERIFIED")

    def test_second_paper_cycle_is_not_poisoned_by_prior_notification(self):
        self.assertEqual(self.v("2027-01-21 23:59",
                                "Submission deadline: 21 January 2027 AoE"), "VERIFIED")

    def test_the_poster_row_is_refused(self):
        self.assertEqual(self.v("2027-03-12 23:59",
                                "Submission deadline: 12 March 2027 AoE"), "UNCONFIRMED")

    def test_the_workshop_row_is_refused(self):
        self.assertEqual(self.v("2026-09-22 23:59",
                                "Submission deadline: 22 September 2026 AoE"), "UNCONFIRMED")

    def test_generic_deadline_under_milestone_headings_is_refused(self):
        for heading in ("Notification", "Camera-ready"):
            with self.subTest(heading=heading):
                url = f"https://{heading.lower()}.example/"
                d = fixture_dir({url: (f"<h3>{heading}</h3>"
                                       "<p>Submission deadline: 24 September 2026 AoE</p>")})
                self.addCleanup(shutil.rmtree, d, ignore_errors=True)
                f = V.Fetcher(offline=True, fixtures=d)
                v = V.verify_proposal(proposal(url, {"deadline": claim(
                    "2026-09-24 23:59",
                    "Submission deadline: 24 September 2026 AoE")}), f)
                self.assertEqual(v["status"], "UNCONFIRMED", v)

    def test_explicit_paper_row_under_workshops_is_refused(self):
        url = "https://workshop-heading.example/"
        d = fixture_dir({url: ("<h3>Workshops</h3>"
                               "<p>Fri 2 Oct 2026 Research Papers "
                               "Full paper submission</p>")})
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        f = V.Fetcher(offline=True, fixtures=d)
        v = V.verify_proposal(proposal(url, {"deadline": claim(
            "2026-10-02 23:59",
            "Fri 2 Oct 2026 Research Papers Full paper submission")}), f)
        self.assertEqual(v["status"], "UNCONFIRMED", v)

    def test_a_heading_is_cancelled_only_by_a_paper_label(self):
        # A generic "submission deadline" belongs to whatever section it is in,
        # so it must not cancel the heading - otherwise every track's row
        # verifies again. An explicit paper label does cancel it.
        d = fixture_dir({"https://ok.example/":
                         "<h3>Poster Submissions</h3><p>closed</p>"
                         "<h3>Research Papers</h3>"
                         "<p>Paper submission deadline: 24 September 2026</p>"})
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        f = V.Fetcher(offline=True, fixtures=d)
        v = V.verify_proposal(proposal("https://ok.example/", {"deadline": claim(
            "2026-09-24 23:59", "Paper submission deadline: 24 September 2026")}), f)
        self.assertEqual(v["status"], "VERIFIED", v)


class FalseNegatives(unittest.TestCase):
    """Correct data the gate used to refuse.

    A local reliability harness found 5 of 17 true field-claims (29%)
    unprovable against pages that state them plainly - so a diligent auditor
    proposing what the watchlist asks for scored 1/3, while one that omitted
    the unprovable fields scored 3/3. The gap was entirely knowing what to drop,
    which is the opposite of what a gate should teach.
    """

    def setUp(self):
        self.dir = fixture_dir({
            "https://eurosys.example/": "<li>Paper titles and abstracts due: "
                                        "Thursday, September 17, 2026</li>",
            "https://span.example/": "<p>The conference is held April 19-23, "
                                     "2027 in Edinburgh.</p>",
            "https://wrongspan.example/": "<p>The conference is held April 19-24, "
                                          "2027 in Edinburgh.</p>",
            "https://acns.example/": "<li>Submission deadline: 24 September 2026, "
                                     "23:59 AoE</li>",
            "https://clock.example/": "<li>Submission deadline: 24 September 2026, "
                                      "12:00 AoE</li>",
            "https://exactclock.example/": "<li>Submission deadline: "
                                           "24 September 2026, 12:00 AoE</li>",
            "https://noclock.example/": "<li>Submission deadline: "
                                        "24 September 2026</li>",
            "https://fivepm.example/": "<li>Submission deadline: "
                                        "24 September 2026 at 5 PM</li>",
            "https://noonword.example/": "<li>Submission deadline: "
                                          "24 September 2026 at noon</li>",
            "https://midnight.example/": "<li>Submission deadline: "
                                          "24 September 2026 at midnight</li>",
            "https://dottedclock.example/": "<li>Submission deadline: "
                                             "24 September 2026, 23.59 AoE</li>",
            "https://dotteddate.example/": "<li>Submission deadline: "
                                            "11.20.2026</li>",
            "https://place.example/": "<p>The conference takes place in "
                                      "Lisbon, Portugal</p>",
            "https://ws.example/": "<li>Workshops paper submission deadline: "
                                   "March 1, 2026</li>",
            "https://fse.example/": ("<nav>Tracks Industry Papers Research Papers "
                                     "Software Engineering Education Workshops</nav>"
                                     "<h2>Important Dates</h2><div>Fri 2 Oct 2026 "
                                     "Research Papers Full paper submission</div>"),
        })
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.f = V.Fetcher(offline=True, fixtures=self.dir)

    def v(self, url, fields):
        return V.verify_proposal(proposal(url, fields), self.f)["status"]

    def test_plural_abstracts_due_verifies(self):
        # 3 of 4 natural CFP phrasings write "abstracts", not "abstract".
        self.assertEqual(self.v("https://eurosys.example/", {"abstract_deadline": claim(
            "2026-09-17 23:59",
            "Paper titles and abstracts due: Thursday, September 17, 2026")}), "VERIFIED")

    def test_compact_date_range_verifies(self):
        # Spans are written "April 19-23, 2027", not as two full dates. Emitting
        # only month-day-year made 83 of the repo's 107 date values ungroundable
        # by their own text - including AUDITOR.md's documented example.
        self.assertEqual(self.v("https://span.example/", {"date": claim(
            "April 19-23, 2027",
            "The conference is held April 19-23, 2027 in Edinburgh.")}), "VERIFIED")

    def test_a_mismatched_range_is_still_refused(self):
        self.assertEqual(self.v("https://wrongspan.example/", {"date": claim(
            "April 19-23, 2027",
            "The conference is held April 19-24, 2027 in Edinburgh.")}), "UNCONFIRMED")

    def test_a_clock_time_is_not_a_second_date(self):
        # "23:59" flattened to "23 59" and counted as another date, so the MORE
        # precise quote - the one naming the exact instant - was the one refused.
        self.assertEqual(self.v("https://acns.example/", {"deadline": claim(
            "2026-09-24 23:59",
            "Submission deadline: 24 September 2026, 23:59 AoE")}), "VERIFIED")

    def test_explicit_noon_cannot_verify_an_end_of_day_claim(self):
        self.assertEqual(self.v("https://clock.example/", {"deadline": claim(
            "2026-09-24 23:59",
            "Submission deadline: 24 September 2026, 12:00 AoE")}),
            "UNCONFIRMED")

    def test_exact_explicit_clock_can_verify(self):
        self.assertEqual(self.v("https://exactclock.example/", {"deadline": claim(
            "2026-09-24 12:00",
            "Submission deadline: 24 September 2026, 12:00 AoE")}),
            "VERIFIED")

    def test_nondefault_clock_cannot_be_invented_on_a_date_only_page(self):
        self.assertEqual(self.v("https://noclock.example/", {"deadline": claim(
            "2026-09-24 12:00",
            "Submission deadline: 24 September 2026")}), "UNCONFIRMED")

    def test_bare_pm_clock_cannot_hide_behind_end_of_day_default(self):
        quote = "Submission deadline: 24 September 2026 at 5 PM"
        self.assertEqual(self.v("https://fivepm.example/", {"deadline": claim(
            "2026-09-24 23:59", quote)}), "UNCONFIRMED")
        self.assertEqual(self.v("https://fivepm.example/", {"deadline": claim(
            "2026-09-24 17:00", quote)}), "VERIFIED")

    def test_noon_word_is_treated_as_an_explicit_clock(self):
        quote = "Submission deadline: 24 September 2026 at noon"
        self.assertEqual(self.v("https://noonword.example/", {"deadline": claim(
            "2026-09-24 23:59", quote)}), "UNCONFIRMED")
        self.assertEqual(self.v("https://noonword.example/", {"deadline": claim(
            "2026-09-24 12:00", quote)}), "VERIFIED")

    def test_midnight_fails_closed_because_its_date_is_ambiguous(self):
        quote = "Submission deadline: 24 September 2026 at midnight"
        self.assertEqual(self.v("https://midnight.example/", {"deadline": claim(
            "2026-09-24 00:00", quote)}), "UNCONFIRMED")

    def test_dotted_24_hour_clock_is_not_mistaken_for_date_only(self):
        quote = "Submission deadline: 24 September 2026, 23.59 AoE"
        self.assertEqual(self.v("https://dottedclock.example/", {"deadline": claim(
            "2026-09-24 23:59", quote)}), "VERIFIED")

    def test_dotted_numeric_date_is_not_mistaken_for_a_clock(self):
        quote = "Submission deadline: 11.20.2026"
        self.assertEqual(self.v("https://dotteddate.example/", {"deadline": claim(
            "2026-11-20 23:59", quote)}), "VERIFIED")

    def test_place_requires_the_whole_claim_not_only_the_city(self):
        self.assertEqual(self.v("https://place.example/", {"place": claim(
            "Lisbon, Mars", "The conference takes place in Lisbon, Portugal")}),
            "UNCONFIRMED")

    def test_plural_forbid_terms_still_disqualify(self):
        # The plural fix must not open a hole: "Workshops" was evading a block
        # on "workshop".
        self.assertEqual(self.v("https://ws.example/", {"deadline": claim(
            "2026-03-01 23:59",
            "Workshops paper submission deadline: March 1, 2026")}), "UNCONFIRMED")

    def test_explicit_fse_paper_row_outranks_navigation(self):
        self.assertEqual(self.v("https://fse.example/", {"deadline": claim(
            "2026-10-02 23:59",
            "Fri 2 Oct 2026 Research Papers Full paper submission")}), "VERIFIED")


class CombinedRows(unittest.TestCase):
    """CFP rows often cover two things at once. A disqualifying term should only
    disqualify when it LEADS the row, not merely when it appears in it.

    The first live gate run flagged SAC 2027 UNCONFIRMED because its real paper
    deadline reads "Submission of regular papers and SRC research abstracts" and
    'src' was a blanket forbid - making the one line that states SAC's deadline
    permanently uncitable.
    """

    def setUp(self):
        self.pages = {
            "https://sac.example/": ("<li>November 13, 2026 Notification of paper "
                                     "acceptance/rejection</li>"
                                     "<li>October 2, 2026 (EST) Submission of "
                                     "regular papers and SRC research abstracts</li>"),
            "https://ws.example/": "<li>Workshop paper submission deadline: "
                                   "March 1, 2026</li>",
            "https://srconly.example/": "<li>SRC research abstracts submission "
                                        "deadline: October 2, 2026</li>",
        }
        self.dir = fixture_dir(self.pages)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.f = V.Fetcher(offline=True, fixtures=self.dir)

    def v(self, url, value, quote):
        return V.verify_proposal(
            proposal(url, {"deadline": claim(value, quote)}), self.f)["status"]

    def test_combined_row_led_by_the_real_label_verifies(self):
        self.assertEqual(self.v(
            "https://sac.example/", "2026-10-02 23:59",
            "October 2, 2026 (EST) Submission of regular papers and SRC research abstracts"),
            "VERIFIED")

    def test_row_led_by_a_disqualifying_term_still_fails(self):
        self.assertEqual(self.v(
            "https://ws.example/", "2026-03-01 23:59",
            "Workshop paper submission deadline: March 1, 2026"), "UNCONFIRMED")

    def test_row_about_only_the_disqualifying_thing_still_fails(self):
        self.assertEqual(self.v(
            "https://srconly.example/", "2026-10-02 23:59",
            "SRC research abstracts submission deadline: October 2, 2026"), "UNCONFIRMED")


class OrdinalDates(unittest.TestCase):
    """A local dry run found AISec's real published deadline was uncitable by
    ANY quote: tokens("July 24th, 2026") is ['july','24','th','2026'] and the
    interposed 'th' broke contiguity with every generated form. The auditor was
    told its perfect verbatim quote "was not found on the page" - exactly the
    input that makes a model conclude its evidence is unusable and give up."""

    def ground(self, line, d):
        return V.ground_quote(V.tokens(line), line, V.date_forms(d),
                              V.FIELD_LABELS["deadline"], single_date=True)

    def test_ordinal_suffixes_verify(self):
        import datetime as dt
        for line, d in (
            ("Paper Submission Deadline: July 24th, 2026", dt.date(2026, 7, 24)),
            ("Paper Submission Deadline: 3rd February 2026", dt.date(2026, 2, 3)),
            ("Paper Submission Deadline: February 1st, 2026", dt.date(2026, 2, 1)),
            ("Paper Submission Deadline: May 22nd, 2026", dt.date(2026, 5, 22)),
        ):
            with self.subTest(line):
                self.assertIsNotNone(self.ground(line, d)[0], line)

    def test_plain_dates_still_verify(self):
        import datetime as dt
        self.assertIsNotNone(
            self.ground("Paper Submission Deadline: July 24, 2026", dt.date(2026, 7, 24))[0])

    def test_a_wrong_date_is_still_refused(self):
        import datetime as dt
        self.assertIsNone(
            self.ground("Paper Submission Deadline: July 24th, 2026", dt.date(2026, 7, 25))[0])


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

    def test_local_addresses_credentials_and_odd_ports_are_rejected(self):
        for url in (
            "http://127.0.0.1/cfp",
            "http://[::1]/cfp",
            "http://169.254.169.254/latest/meta-data/",
            "http://2130706433/cfp",
            "https://user:secret@official.example/cfp",
            "https://official.example:8443/cfp",
        ):
            self.assertFalse(V.source_ok(url)[0], url)

    def test_redirect_handler_refuses_untrusted_target_before_following(self):
        handler = V.SafeRedirectHandler({"official.example"})
        request = V.urllib.request.Request("https://official.example/cfp")
        with self.assertRaises(V.urllib.error.HTTPError):
            handler.redirect_request(
                request, None, 302, "Found", {}, "http://127.0.0.1/private"
            )

    def test_rejected_source_short_circuits_before_fetching(self):
        f = V.Fetcher(offline=True, fixtures=None)
        v = V.verify_proposal(proposal("https://ccfddl.github.io/x",
                                       {"deadline": claim("2026-02-10 23:59", "x y z w")}), f)
        self.assertEqual(v["status"], "REJECTED_SOURCE")


class OfficialHostBinding(unittest.TestCase):
    PAGE = ("<h1>X 2026</h1>"
            "<p>Paper Submission Deadline: February 10, 2026</p>")
    QUOTE = "Paper Submission Deadline: February 10, 2026"

    def p(self, url):
        return proposal(url, {"deadline": claim("2026-02-10 23:59", self.QUOTE)})

    def fixture_fetcher(self, url):
        directory = fixture_dir({url: self.PAGE})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return V.Fetcher(offline=True, fixtures=directory)

    def test_www_is_normalized_and_source_subdomains_are_allowed(self):
        self.assertEqual(V.normalized_host("https://WWW.Official.Example./cfp"),
                         "official.example")
        self.assertTrue(V.source_bound_to_hosts(
            "https://cfp.official.example/dates", {"www.official.example"})[0])

    def test_parent_and_suffix_spoofs_are_not_authorized_by_a_subdomain(self):
        self.assertFalse(V.source_bound_to_hosts(
            "https://official.example/cfp", {"cfp.official.example"})[0])
        self.assertFalse(V.source_bound_to_hosts(
            "https://evilofficial.example/cfp", {"official.example"})[0])

    def test_unconfirmed_current_link_cannot_expand_historical_trust(self):
        watchlist = [{"title": "X", "year": 2027,
                      "record": {"link": "https://www.current.example/cfp"}}]
        historical = [
            {"title": "X", "year": 2026, "link": "https://old.example/"},
            {"title": "Y", "year": 2026, "link": "https://other.example/"},
        ]
        trusted = V.trusted_hosts_by_title(watchlist, historical)
        self.assertEqual(trusted["X"], {"old.example"})
        self.assertEqual(trusted["Y"], {"other.example"})

    def test_deferred_old_identity_does_not_hide_a_newer_historical_anchor(self):
        watchlist = [
            {"title": "X", "year": 2024, "record": {},
             "reasons": ["audit-deferred"]},
            {"title": "X", "year": 2027, "record": {},
             "reasons": ["coverage-gap"]},
        ]
        historical = [
            {"title": "X", "year": 2024, "link": "https://untrusted-current.example"},
            {"title": "X", "year": 2026, "link": "https://official.example"},
        ]
        trusted = V.trusted_hosts_by_title(watchlist, historical)
        self.assertEqual(trusted["X"], {"official.example"})

    def test_two_independent_upstreams_can_bootstrap_a_new_current_host(self):
        watchlist = [{
            "title": "X", "year": 2027,
            "record": {"link": "https://2027.official.example/cfp"},
            "upstream_link_candidates": [
                {"source": "ccfddl", "link": "https://2027.official.example/cfp"},
                {"source": "secdl", "link": "https://2027.official.example/dates"},
            ],
        }]
        trusted = V.trusted_hosts_by_title(watchlist, ())
        self.assertEqual(trusted["X"], {"2027.official.example"})

    def test_duplicate_evidence_from_one_source_does_not_bootstrap_host(self):
        watchlist = [{
            "title": "X", "year": 2027, "record": {},
            "upstream_link_candidates": [
                {"source": "ccfddl", "link": "https://new.example/cfp"},
                {"source": "ccfddl", "link": "https://new.example/dates"},
            ],
        }]
        self.assertNotIn("X", V.trusted_hosts_by_title(watchlist, ()))

    def test_curated_host_bootstraps_a_linkless_coverage_gap(self):
        watchlist = [{"title": "DFRWS US", "year": 2027, "record": {}}]
        trusted = V.trusted_hosts_by_title(
            watchlist, (), {"DFRWS US": ["dfrws.org"]}
        )
        self.assertEqual(trusted["DFRWS US"], {"dfrws.org"})
        self.assertTrue(V.source_bound_to_hosts(
            "https://dfrws.org/conferences/dfrws-usa-2027/",
            trusted["DFRWS US"],
        )[0])

    def test_repo_config_anchors_every_manual_only_target(self):
        configured = V.configured_official_hosts()
        self.assertTrue({"BAR", "CCS-LAMPS", "DFRWS US"}.issubset(configured))

    def test_unrelated_source_is_rejected_before_fetch(self):
        url = "https://evil.example/cfp"
        fetcher = self.fixture_fetcher(url)
        v = V.verify_proposal(self.p(url), fetcher, {"official.example"})
        self.assertEqual(v["status"], "REJECTED_SOURCE", v)
        self.assertIn("unrelated", v["reason"])
        self.assertNotIn(url, fetcher.cache)

    def test_no_trusted_host_does_not_bootstrap_from_the_proposal(self):
        url = "https://new.example/cfp"
        fetcher = self.fixture_fetcher(url)
        v = V.verify_proposal(self.p(url), fetcher, set())
        self.assertEqual(v["status"], "REJECTED_SOURCE", v)
        self.assertIn("no trusted official link host", v["reason"])
        self.assertNotIn(url, fetcher.cache)

    def test_a_bound_source_still_verifies(self):
        url = "https://cfp.official.example/dates"
        v = V.verify_proposal(self.p(url), self.fixture_fetcher(url),
                              {"official.example"})
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_redirect_cannot_escape_to_an_unrelated_host(self):
        url = "https://official.example/cfp"

        class RedirectFetcher:
            final_urls = {url: "https://evil.example/copied-cfp"}

            def get(self, unused):
                return OfficialHostBinding.PAGE, None

        v = V.verify_proposal(self.p(url), RedirectFetcher(), {"official.example"})
        self.assertEqual(v["status"], "REJECTED_SOURCE", v)
        self.assertIn("redirect target rejected", v["reason"])
        self.assertEqual(v["final_url"], "https://evil.example/copied-cfp")

    def test_redirect_cannot_escape_to_a_denied_tracker(self):
        url = "https://official.example/cfp"

        class RedirectFetcher:
            final_urls = {url: "https://sec-deadlines.github.io/copied-cfp"}

            def get(self, unused):
                return OfficialHostBinding.PAGE, None

        v = V.verify_proposal(self.p(url), RedirectFetcher(), {"official.example"})
        self.assertEqual(v["status"], "REJECTED_SOURCE", v)
        self.assertIn("community tracker", v["reason"])

    def test_redirect_to_a_trusted_subdomain_is_allowed(self):
        url = "https://official.example/cfp"

        class RedirectFetcher:
            final_urls = {url: "https://dates.official.example/cfp"}

            def get(self, unused):
                return OfficialHostBinding.PAGE, None

        v = V.verify_proposal(self.p(url), RedirectFetcher(), {"official.example"})
        self.assertEqual(v["status"], "VERIFIED", v)
        self.assertEqual(v["final_url"], "https://dates.official.example/cfp")

    def test_production_main_uses_watchlist_trust_and_rejects_no_trust(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        trusted_url = "https://official.example/cfp"
        unknown_url = "https://brand-new.example/cfp"
        fixtures = fixture_dir({trusted_url: self.PAGE, unknown_url: self.PAGE})
        self.addCleanup(shutil.rmtree, fixtures, ignore_errors=True)
        proposals_path = directory / "audit-proposals.json"
        watchlist_path = directory / "watchlist.json"
        out_path = directory / "audit-verdicts.json"
        proposals_path.write_text(json.dumps({"proposals": [
            self.p(trusted_url),
            proposal(unknown_url, {"deadline": claim(
                "2026-02-10 23:59", self.QUOTE)}, title="NoTrust"),
        ]}), encoding="utf-8")
        watchlist_path.write_text(json.dumps([
            {"title": "X", "year": 2026,
             "record": {"link": "https://www.official.example/"},
             "upstream_link_candidates": [
                 {"source": "ccfddl", "link": "https://official.example/cfp"},
                 {"source": "secdl", "link": "https://official.example/dates"},
             ]},
            {"title": "NoTrust", "year": 2026, "record": {}},
        ]), encoding="utf-8")
        argv = ["verify_citations.py", "--proposals", str(proposals_path),
                "--watchlist", str(watchlist_path), "--out", str(out_path),
                "--offline", "--fixtures", str(fixtures)]
        targets = [
            {"key": "X", "full_name": "Example Conference", "aliases": ["X"]},
            {"key": "NoTrust", "full_name": "No Trust Conference",
             "aliases": ["NoTrust"]},
        ]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(V.U, "load_existing", return_value={}), \
                mock.patch.object(V.U, "load_config", return_value=targets):
            code = V.main()

        self.assertEqual(code, 2)
        verdicts = json.loads(out_path.read_text(encoding="utf-8"))["verdicts"]
        self.assertEqual([verdict["status"] for verdict in verdicts],
                         ["accepted", "rejected"])
        self.assertIn("no trusted official link host",
                      verdicts[1]["detail"]["reason"])


class ConferenceEditionIdentity(unittest.TestCase):
    QUOTE_2027 = "Paper Submission Deadline: February 10, 2027"

    def verify(self, html, title="FSE", year=2027, aliases=None):
        url = "https://conf.researchr.org/home/fse-2027"
        directory = fixture_dir({url: html})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        fetcher = V.Fetcher(offline=True, fixtures=directory)
        return V.verify_proposal(
            proposal(url, {"deadline": claim(
                "2027-02-10 23:59", self.QUOTE_2027,
            )}, title=title, year=year),
            fetcher,
            {"conf.researchr.org"},
            aliases if aliases is not None else [title],
            {"FSE": ["FSE", "Foundations of Software Engineering"],
             "ASE": ["ASE", "Automated Software Engineering"]},
        )

    def test_matching_title_and_year_verifies(self):
        v = self.verify(
            "<title>FSE 2027 - Research Papers</title>"
            f"<p>{self.QUOTE_2027}</p>"
        )
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_full_name_in_real_page_text_shape_verifies(self):
        full_name = ("ACM International Conference on the Foundations of "
                     "Software Engineering")
        v = self.verify(
            f"<main><p>Welcome to the 2027 {full_name}.</p>"
            f"<p>{self.QUOTE_2027}</p></main>",
            aliases=["FSE", full_name],
        )
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_apostrophe_year_in_title_verifies(self):
        v = self.verify(
            "<meta property='og:title' content=\"FSE '27 Call for Papers\">"
            f"<p>{self.QUOTE_2027}</p>"
        )
        self.assertEqual(v["status"], "VERIFIED", v)

    def test_wrong_conference_on_same_official_host_is_rejected(self):
        # The deadline quote and host are both admissible, but this is ASE's
        # page. Shared conference platforms cannot confer venue identity.
        v = self.verify(
            "<title>ASE 2027 - Research Papers</title>"
            "<nav><a href='/home/fse-2027'>FSE 2027</a></nav>"
            f"<p>{self.QUOTE_2027}</p>"
        )
        self.assertEqual(v["status"], "REJECTED_SOURCE", v)
        self.assertIn("identifies conference 'ASE', not 'FSE'", v["reason"])

    def test_wrong_edition_header_overrides_expected_year_in_deadline(self):
        # The expected year does occur on the page, but only in a field date.
        # An explicit FSE 2026 page title must make a 2027 proposal fail closed.
        v = self.verify(
            "<title>FSE 2026 - Research Papers</title>"
            f"<p>{self.QUOTE_2027}</p>"
        )
        self.assertEqual(v["status"], "REJECTED_SOURCE", v)
        self.assertIn("2026, not 2027", v["reason"])

    def test_missing_configured_identity_is_rejected(self):
        v = self.verify(
            "<title>FSE 2027 - Research Papers</title>"
            f"<p>{self.QUOTE_2027}</p>",
            aliases=[],
        )
        self.assertEqual(v["status"], "REJECTED_SOURCE", v)
        self.assertIn("no configured conference identity", v["reason"])

    def test_config_identity_vocabulary_includes_key_aliases_and_full_name(self):
        identities = V.configured_conference_identities([{
            "key": "FSE",
            "full_name": "Foundations of Software Engineering",
            "aliases": ["FSE", "ESEC/FSE"],
        }])
        self.assertEqual(
            identities["FSE"],
            ["FSE", "Foundations of Software Engineering", "ESEC/FSE"],
        )


class Unreachable(unittest.TestCase):
    def test_unreachable_is_never_verified(self):
        f = V.Fetcher(offline=True, fixtures=None)
        v = V.verify_proposal(proposal("https://nope.example/", {"deadline": claim(
            "2026-02-10 23:59", "Paper Submission Deadline: February 10, 2026")}), f)
        self.assertEqual(v["status"], "UNREACHABLE")
        self.assertFalse(v.get("accepted", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
