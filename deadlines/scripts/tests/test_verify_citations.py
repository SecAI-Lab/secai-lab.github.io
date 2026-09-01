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


class StructuralClockScoping(unittest.TestCase):
    """Researchr puts a changing message timestamp immediately after its dates
    table.  It is a sibling widget, never part of the paper-deadline row."""

    BASE = """<html><body><div id='page'>
    <p>All deadlines are anywhere on Earth (AoE).</p><table>
    <tr href='/track' class='clickable-row past'>
      <td><strong>Thu 26 Mar 2026</strong>
          <span title='Timezone: AoE (UTC-12h)'>clock</span></td>
      <td><strong>Research Papers</strong></td>
      <td><strong>Paper Submission</strong>{row_clock}</td>
    </tr></table>
    <div id='messages-placeholder'><a>x</a><em>Tue 1 Sep 07:37</em></div>
    </div></body></html>"""
    QUOTE = "Thu 26 Mar 2026 Research Papers Paper Submission"

    def verify(self, row_clock=""):
        url = "https://researchr-clock.example/dates"
        directory = fixture_dir({url: self.BASE.format(row_clock=row_clock)})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return V.verify_proposal(proposal(url, {"deadline": claim(
            "2026-03-26 23:59", self.QUOTE)}),
            V.Fetcher(offline=True, fixtures=directory))

    def test_sibling_live_clock_does_not_poison_deadline(self):
        self.assertEqual(self.verify()["status"], "VERIFIED")

    def test_conflicting_clock_inside_same_row_still_fails_closed(self):
        verdict = self.verify(" at 5 PM")
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("not proposed minute", verdict["fields"]["deadline"]["reason"])

    def verify_custom(self, html):
        url = "https://nested-clock.example/cfp"
        directory = fixture_dir({url: html})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return V.verify_proposal(
            proposal(url, {"deadline": claim(
                "2026-09-24 23:59",
                "Submission deadline: September 24, 2026",
            )}),
            V.Fetcher(offline=True, fixtures=directory),
        )

    def test_clock_in_enclosing_logical_row_cannot_be_omitted_from_quote(self):
        html = ("<li><p>Submission deadline: September 24, 2026</p>"
                "<span>at 17:00 AoE</span></li>")
        verdict = self.verify_custom(html)
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("not proposed minute",
                      verdict["fields"]["deadline"]["reason"])

    def test_unrelated_structural_unit_does_not_disable_line_fallback(self):
        html = ("<div>Navigation</div> Submission deadline: "
                "September 24, 2026 at 17:00 AoE")
        verdict = self.verify_custom(html)
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("not proposed minute",
                      verdict["fields"]["deadline"]["reason"])

    def test_div_grid_row_cannot_hide_clock_in_sibling_cell(self):
        html = ("<div class='deadline-row'>"
                "<div>Submission deadline: September 24, 2026</div>"
                "<div>at 17:00 AoE</div></div>")
        verdict = self.verify_custom(html)
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("not proposed minute",
                      verdict["fields"]["deadline"]["reason"])


class StrongShortContext(unittest.TestCase):
    def verify(self, html, field, value, quote):
        url = f"https://short-{field}.example/"
        directory = fixture_dir({url: html})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return V.verify_proposal(
            proposal(url, {field: claim(value, quote)}),
            V.Fetcher(offline=True, fixtures=directory),
        )["status"]

    def test_short_labelled_place_is_complete_evidence(self):
        self.assertEqual(self.verify("<p>Venue: Rome, Italy</p>", "place",
                                     "Rome, Italy", "Venue: Rome, Italy"),
                         "VERIFIED")

    def test_bare_city_country_remains_too_weak(self):
        self.assertEqual(self.verify("<p>Rome, Italy</p>", "place",
                                     "Rome, Italy", "Rome, Italy"),
                         "UNCONFIRMED")

    def test_short_labelled_conference_date_is_complete_evidence(self):
        quote = "Conference: September 14-18, 2026"
        self.assertEqual(self.verify(f"<p>{quote}</p>", "date",
                                     "September 14-18, 2026", quote),
                         "VERIFIED")

    def test_bare_conference_date_remains_too_weak(self):
        quote = "September 14-18, 2026"
        self.assertEqual(self.verify(f"<p>{quote}</p>", "date",
                                     "September 14-18, 2026", quote),
                         "UNCONFIRMED")

    def test_short_important_dates_timezone_heading_verifies(self):
        quote = "Important Dates (AoE)"
        self.assertEqual(self.verify(f"<h3>{quote}</h3>", "timezone", "AoE", quote),
                         "VERIFIED")

    def test_exact_submission_key_is_narrowly_accepted(self):
        quote = "Submission: 10 December 2025 (extended!)"
        self.assertEqual(self.verify(f"<h3>Important Dates (AoE)</h3><li>{quote}</li>",
                                     "deadline", "2025-12-10 23:59", quote),
                         "VERIFIED")

    def test_submission_site_and_revised_submission_remain_rejected(self):
        for quote in ("Submission site opens: 10 December 2025",
                      "Submission: revised papers 10 December 2025",
                      "Submission: abstract 10 December 2025",
                      "Submission: artifact 10 December 2025"):
            with self.subTest(quote=quote):
                self.assertEqual(self.verify(f"<li>{quote}</li>", "deadline",
                                             "2025-12-10 23:59", quote),
                                 "UNCONFIRMED")

    def test_generic_submission_under_poster_heading_remains_rejected(self):
        quote = "Submission: 10 December 2025"
        html = f"<h3>Poster Submissions</h3><li>{quote}</li>"
        self.assertEqual(self.verify(html, "deadline", "2025-12-10 23:59", quote),
                         "UNCONFIRMED")


class ElapsedStruckDeadlines(unittest.TestCase):
    EUROSYS = """<html><body><h1>EuroSys 2027</h1>
    <p>All deadlines are anywhere on Earth (AoE).</p>
    <h3>Spring Deadline</h3><ul>
      <li>Paper titles and abstracts due: <s>Thursday, May 7, 2026</s></li>
      <li>Full paper submissions due: <del>Thursday, May 14, 2026</del></li>
    </ul><h3>Fall Deadline</h3><ul>
      <li>Paper titles and abstracts due: Thursday, September 17, 2026</li>
      <li>Full paper submissions due: Thursday, September 24, 2026</li>
    </ul></body></html>"""

    DEADLINES = ["2026-05-14 23:59", "2026-09-24 23:59"]
    EVIDENCE = [
        {"for_value": "2026-05-14 23:59",
         "quote": "Full paper submissions due: Thursday, May 14, 2026"},
        {"for_value": "2026-09-24 23:59",
         "quote": "Full paper submissions due: Thursday, September 24, 2026"},
    ]
    ABSTRACTS = ["2026-05-07 23:59", "2026-09-17 23:59"]
    ABSTRACT_EVIDENCE = [
        {"for_value": "2026-05-07 23:59",
         "quote": "Paper titles and abstracts due: Thursday, May 7, 2026"},
        {"for_value": "2026-09-17 23:59",
         "quote": "Paper titles and abstracts due: Thursday, September 17, 2026"},
    ]

    def verify(self, html, values, evidence, *, action="no_change",
               current=None, audit_date="2026-09-01"):
        url = "https://elapsed.example/cfp"
        directory = fixture_dir({url: html})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        p = proposal(url, {"deadline": {"value": values, "evidence": evidence}},
                     action=action, title="EuroSys", year=2027)
        return V.verify_proposal(
            p, V.Fetcher(offline=True, fixtures=directory),
            current_record=current, audit_date=audit_date,
        )

    def test_elapsed_struck_cycle_can_confirm_exact_immutable_no_change(self):
        verdict = self.verify(
            self.EUROSYS, self.DEADLINES, self.EVIDENCE,
            current={"deadline": list(self.DEADLINES)},
        )
        self.assertEqual(verdict["status"], "VERIFIED", verdict)

    def test_elapsed_struck_abstract_cycle_uses_the_same_safe_path(self):
        url = "https://elapsed-abstract.example/cfp"
        directory = fixture_dir({url: self.EUROSYS})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        p = proposal(url, {"abstract_deadline": {
            "value": list(self.ABSTRACTS),
            "evidence": list(self.ABSTRACT_EVIDENCE),
        }}, action="no_change", title="EuroSys", year=2027)
        verdict = V.verify_proposal(
            p, V.Fetcher(offline=True, fixtures=directory),
            current_record={"abstract_deadline": list(self.ABSTRACTS)},
            audit_date="2026-09-01",
        )
        self.assertEqual(verdict["status"], "VERIFIED", verdict)

    def test_struck_cycle_can_never_authorize_a_mutation(self):
        verdict = self.verify(
            self.EUROSYS, self.DEADLINES, self.EVIDENCE,
            action="upsert_manual", current={"deadline": list(self.DEADLINES)},
        )
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)

    def test_struck_cycle_requires_the_complete_no_change_field_to_match(self):
        verdict = self.verify(
            self.EUROSYS, self.DEADLINES[0], [self.EVIDENCE[0]],
            current={"deadline": list(self.DEADLINES)},
        )
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("complete proposed field",
                      verdict["fields"]["deadline"]["reason"])

    def test_future_struck_deadline_remains_unconfirmed(self):
        quote = "Paper Submission Deadline: September 24, 2026"
        html = f"<p>Paper Submission Deadline: <s>September 24, 2026</s></p>"
        verdict = self.verify(
            html, "2026-09-24 23:59", [{"quote": quote}],
            current={"deadline": "2026-09-24 23:59"}, audit_date="2026-09-01",
        )
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)

    def test_struck_date_with_active_replacement_remains_unconfirmed(self):
        quote = "Submission: 03 December 2025"
        html = ("<h3>Important Dates (AoE)</h3><li>Submission: "
                "<s>03 December 2025</s> <b>10 December 2025 (extended!)</b></li>")
        verdict = self.verify(
            html, "2025-12-03 23:59", [{"quote": quote}],
            current={"deadline": "2025-12-03 23:59"},
        )
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)

    def test_struck_child_cannot_hide_active_ancestor_extension(self):
        quote = "Submission: 03 December 2025"
        html = ("<li><p><del>Submission: 03 December 2025</del></p>"
                "<span>Extended to 10 December 2025</span></li>")
        verdict = self.verify(
            html, "2025-12-03 23:59", [{"quote": quote}],
            current={"deadline": "2025-12-03 23:59"},
        )
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("active replacement date",
                      verdict["fields"]["deadline"]["reason"])

    def test_struck_date_with_tba_replacement_remains_unconfirmed(self):
        quote = "Submission: 03 December 2025"
        html = ("<h3>Important Dates (AoE)</h3><li>Submission: "
                "<del>03 December 2025</del> <b>TBA (rescheduled)</b></li>")
        verdict = self.verify(
            html, "2025-12-03 23:59", [{"quote": quote}],
            current={"deadline": "2025-12-03 23:59"},
        )
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)

    def test_omitted_conflicting_clock_in_struck_row_remains_unconfirmed(self):
        quote = "Submission: 03 December 2025"
        html = ("<h3>Important Dates (AoE)</h3><li>Submission: "
                "<del>03 December 2025 at 5 PM</del></li>")
        verdict = self.verify(
            html, "2025-12-03 23:59", [{"quote": quote}],
            current={"deadline": "2025-12-03 23:59"},
        )
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("not proposed minute",
                      verdict["fields"]["deadline"]["reason"])


class MultiCycleEvidenceBinding(unittest.TestCase):
    PAGE = """<html><body><h2>Important Dates</h2><ul>
      <li>Paper Submission Deadline: May 14, 2026</li>
      <li>Paper Submission Deadline: September 24, 2026</li>
    </ul></body></html>"""
    VALUES = ["2026-05-14 23:59", "2026-09-24 23:59"]

    def verify(self, evidence, values=None, action="upsert_manual"):
        url = "https://cycles.example/cfp"
        directory = fixture_dir({url: self.PAGE})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        p = proposal(url, {"deadline": {
            "value": self.VALUES if values is None else values,
            "evidence": evidence,
        }}, action=action)
        return V.verify_proposal(p, V.Fetcher(offline=True, fixtures=directory))

    def test_for_value_binds_each_quote_to_exactly_one_cycle(self):
        evidence = [
            {"for_value": self.VALUES[0],
             "quote": "Paper Submission Deadline: May 14, 2026"},
            {"for_value": self.VALUES[1],
             "quote": "Paper Submission Deadline: September 24, 2026"},
        ]
        self.assertEqual(self.verify(evidence)["status"], "VERIFIED")

    def test_misbound_quotes_cannot_cross_validate_and_diagnostic_is_bounded(self):
        evidence = [
            {"for_value": self.VALUES[0],
             "quote": "Paper Submission Deadline: September 24, 2026"},
            {"for_value": self.VALUES[1],
             "quote": "Paper Submission Deadline: May 14, 2026"},
        ]
        verdict = self.verify(evidence)
        reason = verdict["fields"]["deadline"]["reason"]
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("evidence[0]", reason)
        self.assertLessEqual(len(reason), 500)

    def test_unbound_multi_cycle_evidence_remains_unconfirmed(self):
        evidence = [
            {"quote": "Paper Submission Deadline: May 14, 2026"},
            {"quote": "Paper Submission Deadline: September 24, 2026"},
        ]
        verdict = self.verify(evidence)
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("for_value", verdict["fields"]["deadline"]["reason"])

    def test_null_cycle_in_mutation_remains_fail_closed(self):
        evidence = [{"for_value": self.VALUES[0],
                     "quote": "Paper Submission Deadline: May 14, 2026"}]
        verdict = self.verify(evidence, values=[self.VALUES[0], None])
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("no checkable form", verdict["fields"]["deadline"]["reason"])

    def test_null_abstract_cycle_in_mutation_remains_fail_closed(self):
        url = "https://abstract-cycles.example/cfp"
        html = ("<p>Paper titles and abstracts due: May 7, 2026</p>"
                "<p>Paper titles and abstracts due: September 17, 2026</p>")
        directory = fixture_dir({url: html})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        value = "2026-05-07 23:59"
        p = proposal(url, {"abstract_deadline": {
            "value": [value, None],
            "evidence": [{
                "for_value": value,
                "quote": "Paper titles and abstracts due: May 7, 2026",
            }],
        }}, action="upsert_manual")
        verdict = V.verify_proposal(
            p, V.Fetcher(offline=True, fixtures=directory)
        )
        self.assertEqual(verdict["status"], "UNCONFIRMED", verdict)
        self.assertIn("no checkable form",
                      verdict["fields"]["abstract_deadline"]["reason"])


class SourceAuthority(unittest.TestCase):
    @staticmethod
    def dns_answers(*addresses):
        answers = []
        for address in addresses:
            family = V.socket.AF_INET6 if ":" in address else V.socket.AF_INET
            sockaddr = ((address, 443, 0, 0) if family == V.socket.AF_INET6
                        else (address, 443))
            answers.append((family, V.socket.SOCK_STREAM, 6, "", sockaddr))
        return answers

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

    def test_network_source_requires_only_public_resolved_addresses(self):
        public = self.dns_answers("93.184.216.34", "2606:4700:4700::1111")
        private = self.dns_answers("127.0.0.1")
        mixed = self.dns_answers("93.184.216.34", "10.0.0.8")

        self.assertTrue(V.network_source_ok(
            "https://official.example/cfp", resolver=lambda *a, **k: public)[0])
        self.assertFalse(V.network_source_ok(
            "https://official.example/cfp", resolver=lambda *a, **k: private)[0])
        ok, why = V.network_source_ok(
            "https://official.example/cfp", resolver=lambda *a, **k: mixed)
        self.assertFalse(ok)
        self.assertIn("non-public", why)

    def test_network_source_rejects_failed_or_empty_resolution(self):
        self.assertFalse(V.network_source_ok(
            "https://official.example/cfp", resolver=lambda *a, **k: [])[0])

        def failed(*args, **kwargs):
            raise V.socket.gaierror("no answer")

        self.assertFalse(V.network_source_ok(
            "https://official.example/cfp", resolver=failed)[0])

    def test_dns_alias_helpers_are_denied_without_resolution(self):
        resolver = mock.Mock(return_value=self.dns_answers("93.184.216.34"))
        ok, why = V.network_source_ok(
            "https://127.0.0.1.nip.io/cfp", resolver=resolver)
        self.assertFalse(ok)
        self.assertIn("helper host", why)
        resolver.assert_not_called()

    def test_fetcher_never_builds_an_opener_for_unsafe_dns(self):
        resolver = mock.Mock(return_value=self.dns_answers("192.168.1.10"))
        fetcher = V.Fetcher(resolver=resolver)
        with mock.patch.object(V.time, "sleep"), \
                mock.patch.object(V.urllib.request, "build_opener") as opener:
            page, error = fetcher.get(
                "https://official.example/cfp", {"official.example"})
        self.assertIsNone(page)
        self.assertIn("URLError", error)
        opener.assert_not_called()

    def test_redirect_handler_refuses_untrusted_target_before_following(self):
        handler = V.SafeRedirectHandler({"official.example"})
        request = V.urllib.request.Request("https://official.example/cfp")
        with self.assertRaises(V.urllib.error.HTTPError):
            handler.redirect_request(
                request, None, 302, "Found", {}, "http://127.0.0.1/private"
            )

    def test_redirect_handler_resolves_target_before_following(self):
        handler = V.SafeRedirectHandler(
            {"official.example"},
            resolver=lambda *a, **k: self.dns_answers("10.0.0.9"),
        )
        request = V.urllib.request.Request("https://official.example/cfp")
        with self.assertRaises(V.urllib.error.HTTPError) as caught:
            handler.redirect_request(
                request, None, 302, "Found", {},
                "https://sub.official.example/private",
            )
        self.assertIn("non-public", str(caught.exception))

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
        self.assertEqual(v["source_trust"], "trusted")

    def test_annual_template_accepts_curated_or_historical_exact_parent(self):
        cases = [
            ([{"title": "X", "year": 2025,
               "link": "https://x2025.series.example/"}],
             {"X": ["series.example"]}),
            ([{"title": "X", "year": 2024,
               "link": "https://series.example/"},
              {"title": "X", "year": 2025,
               "link": "https://x2025.series.example/"}],
             None),
        ]
        for historical, configured in cases:
            with self.subTest(configured=bool(configured)):
                watchlist = [{"title": "X", "year": 2027, "record": {}}]
                policy = V.build_source_trust_policy(
                    watchlist, historical, configured
                )
                decision, why = V.classify_source_trust(
                    "https://x2027.series.example/cfp", "X", 2027, policy
                )
                self.assertIsNotNone(decision, why)
                self.assertEqual(decision.level, "trusted")
                self.assertIn("x2027.series.example",
                              policy.annual_by_identity[("X", 2027)])

    def test_parent_plus_child_distinct_titles_establishes_organizer(self):
        watchlist = [{"title": "EuroS&P", "year": 2027, "record": {}}]
        historical = [
            {"title": "S&P", "year": 2024,
             "link": "https://www.ieee-security.org/TC/SP2024/"},
            {"title": "EuroS&P", "year": 2025,
             "link": "https://eurosp2025.ieee-security.org/"},
        ]
        policy = V.build_source_trust_policy(watchlist, historical)
        self.assertIn("ieee-security.org", policy.organizer_hosts)
        decision, why = V.classify_source_trust(
            "https://eurosp2027.ieee-security.org/cfp",
            "EuroS&P", 2027, policy,
        )
        self.assertIsNotNone(decision, why)
        self.assertEqual(decision.level, "trusted")
        self.assertIn("eurosp2027.ieee-security.org",
                      policy.annual_by_identity[("EuroS&P", 2027)])

    def test_annual_templates_never_cross_multi_tenant_siblings(self):
        cases = [
            ("DSN", "dsn2025.github.io", "dsn2026.github.io"),
            ("EuroSec", "eurosec25.hotcrp.com", "eurosec26.hotcrp.com"),
            ("X", "x2025.pages.dev", "x2026.pages.dev"),
        ]
        for title, old_host, new_host in cases:
            with self.subTest(new_host=new_host):
                watchlist = [{"title": title, "year": 2026, "record": {}}]
                historical = [{"title": title, "year": 2025,
                               "link": f"https://{old_host}/"}]
                policy = V.build_source_trust_policy(watchlist, historical)
                decision, _ = V.classify_source_trust(
                    f"https://{new_host}/cfp", title, 2026, policy
                )
                self.assertIsNone(decision)
                self.assertNotIn((title, 2026), policy.annual_by_identity)

        self.assertIsNone(V._annualized_host(
            "dsn2025.github.io", 2025, 2026, {"github.io"}
        ))
        self.assertIsNone(V._annualized_host(
            "event2025.wordpress.com", 2025, 2026, {"wordpress.com"}
        ))

    def test_registrable_and_unproven_tenant_year_rewrites_are_not_strong(self):
        cases = [
            ("RAID", 2026, "raid2026.org", 2027, "raid2027.org"),
            ("Workshop", 2025, "event2025.wordpress.com", 2026,
             "event2026.wordpress.com"),
        ]
        for title, old_year, old_host, new_year, new_host in cases:
            with self.subTest(new_host=new_host):
                watchlist = [{"title": title, "year": new_year, "record": {}}]
                historical = [{"title": title, "year": old_year,
                               "link": f"https://{old_host}/"}]
                policy = V.build_source_trust_policy(watchlist, historical)
                decision, _ = V.classify_source_trust(
                    f"https://{new_host}/cfp", title, new_year, policy
                )
                self.assertIsNone(decision)
                self.assertNotIn((title, new_year), policy.annual_by_identity)

                nominated = dict(watchlist[0])
                nominated["upstream_link_candidates"] = [
                    {"source": "ccfddl", "link": f"https://{new_host}/cfp"},
                ]
                provisional = V.build_source_trust_policy(
                    [nominated], historical
                )
                decision, why = V.classify_source_trust(
                    f"https://{new_host}/cfp", title, new_year, provisional
                )
                self.assertIsNotNone(decision, why)
                self.assertEqual(decision.level, "provisional")

    def test_same_title_repetition_is_not_global_organizer_authority(self):
        watchlist = [{"title": "Other", "year": 2026, "record": {}}]
        historical = [
            {"title": "DIMVA", "year": 2024, "link": "https://dimva.org/a"},
            {"title": "DIMVA", "year": 2025, "link": "https://dimva.org/b"},
        ]
        policy = V.build_source_trust_policy(watchlist, historical)
        self.assertNotIn("dimva.org", policy.organizer_hosts)
        decision, _ = V.classify_source_trust(
            "https://dimva.org/other-2026", "Other", 2026, policy
        )
        self.assertIsNone(decision)

    def test_repeated_historical_organizer_host_is_cross_title_authority(self):
        url = "https://sigops.org/s/conferences/atc/2026/"
        watchlist = [{"title": "ATC", "year": 2026, "record": {}}]
        historical = [
            {"title": "SOSP", "year": 2024,
             "link": "https://sigops.org/s/conferences/sosp/2024/"},
            {"title": "HotOS", "year": 2025,
             "link": "https://sigops.org/s/conferences/hotos/2025/"},
        ]
        policy = V.build_source_trust_policy(watchlist, historical)
        self.assertIn("sigops.org", policy.organizer_hosts)
        page = ("<title>ATC 2026</title>"
                "<p>Paper Submission Deadline: February 10, 2026</p>")
        directory = fixture_dir({url: page})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        p = proposal(url, {"deadline": claim("2026-02-10 23:59", self.QUOTE)},
                     title="ATC")
        v = V.verify_proposal(
            p, V.Fetcher(offline=True, fixtures=directory), set(), ["ATC"],
            {"ATC": ["ATC"], "FSE": ["FSE"]},
            source_trust_policy=policy,
        )
        self.assertEqual(v["status"], "VERIFIED", v)
        self.assertEqual(v["source_trust"], "trusted")

    def test_organizer_authority_does_not_replace_page_identity(self):
        url = "https://sigops.org/s/conferences/atc/2026/"
        watchlist = [{"title": "ATC", "year": 2026, "record": {}}]
        historical = [
            {"title": "SOSP", "year": 2024, "link": "https://sigops.org/a"},
            {"title": "HotOS", "year": 2025, "link": "https://sigops.org/b"},
        ]
        policy = V.build_source_trust_policy(watchlist, historical)
        page = ("<title>FSE 2026 - Research Papers</title>"
                "<nav>ATC 2026</nav>"
                "<p>Paper Submission Deadline: February 10, 2026</p>")
        directory = fixture_dir({url: page})
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        p = proposal(url, {"deadline": claim("2026-02-10 23:59", self.QUOTE)},
                     title="ATC")
        v = V.verify_proposal(
            p, V.Fetcher(offline=True, fixtures=directory), set(), ["ATC"],
            {"ATC": ["ATC"], "FSE": ["FSE"]},
            source_trust_policy=policy,
        )
        self.assertEqual(v["status"], "REJECTED_SOURCE", v)
        self.assertIn("identifies conference 'FSE', not 'ATC'", v["reason"])

    def test_one_upstream_exact_host_is_provisional_and_fetch_is_confined(self):
        url = "https://new-official.example/cfp"
        watchlist = [{
            "title": "X", "year": 2026, "record": {},
            "upstream_link_candidates": [
                {"source": "ccfddl", "link": url},
            ],
        }]
        policy = V.build_source_trust_policy(watchlist, ())

        class RecordingFetcher(V.Fetcher):
            def __init__(self):
                super().__init__(offline=True)
                self.call = None

            def get(self, requested, allowed_hosts=None, *,
                    exact_redirect_hosts=False):
                self.call = (requested, set(allowed_hosts or ()),
                             exact_redirect_hosts)
                self.final_urls[requested] = requested
                return OfficialHostBinding.PAGE, None

        fetcher = RecordingFetcher()
        v = V.verify_proposal(
            self.p(url), fetcher, set(), ["X"], {"X": ["X"]},
            source_trust_policy=policy,
        )
        self.assertEqual(v["status"], "VERIFIED", v)
        self.assertEqual(v["source_trust"], "provisional")
        self.assertRegex(v["source_trust_basis"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(fetcher.call,
                         (url, {"new-official.example"}, True))

    def test_provisional_nomination_is_exact_and_model_only_host_is_rejected(self):
        nominated = "https://new-official.example/cfp"
        watchlist = [{
            "title": "X", "year": 2026,
            # A current record link is not authority either.
            "record": {"link": "https://model-only.example/cfp"},
            "upstream_link_candidates": [
                {"source": "ccfddl", "link": nominated},
            ],
        }]
        policy = V.build_source_trust_policy(watchlist, ())
        for url in ("https://sub.new-official.example/cfp",
                    "https://model-only.example/cfp"):
            with self.subTest(url=url):
                fetcher = self.fixture_fetcher(url)
                v = V.verify_proposal(
                    self.p(url), fetcher, set(), ["X"], {"X": ["X"]},
                    source_trust_policy=policy,
                )
                self.assertEqual(v["status"], "REJECTED_SOURCE", v)
                self.assertNotIn(url, fetcher.cache)

    def test_provisional_basis_is_stable_and_provenance_bound(self):
        first = V.provisional_source_basis(
            "X", 2026, "WWW.New-Official.Example.",
            ["secdl", "ccfddl", "secdl"],
        )
        reordered = V.provisional_source_basis(
            "X", 2026, "new-official.example", ["ccfddl", "secdl"],
        )
        changed = V.provisional_source_basis(
            "X", 2026, "new-official.example", ["ccfddl"],
        )
        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)

    def test_two_upstream_exact_host_is_strong_not_provisional(self):
        url = "https://new-official.example/cfp"
        watchlist = [{
            "title": "X", "year": 2026, "record": {},
            "upstream_link_candidates": [
                {"source": "ccfddl", "link": url},
                {"source": "secdl", "link": "https://new-official.example/dates"},
            ],
        }]
        policy = V.build_source_trust_policy(watchlist, ())
        decision, why = V.classify_source_trust(url, "X", 2026, policy)
        self.assertIsNotNone(decision, why)
        self.assertEqual(decision.level, "trusted")
        self.assertNotIn(("X", 2026), policy.provisional_by_identity)

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

    def test_production_main_emits_provisional_source_basis(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        url = "https://new-official.example/cfp"
        fixtures = fixture_dir({url: self.PAGE})
        self.addCleanup(shutil.rmtree, fixtures, ignore_errors=True)
        proposals_path = directory / "audit-proposals.json"
        watchlist_path = directory / "watchlist.json"
        out_path = directory / "audit-verdicts.json"
        proposals_path.write_text(json.dumps({"proposals": [self.p(url)]}),
                                  encoding="utf-8")
        watchlist_path.write_text(json.dumps([{
            "title": "X", "year": 2026, "record": {},
            "upstream_link_candidates": [
                {"source": "ccfddl", "link": url},
            ],
        }]), encoding="utf-8")
        argv = ["verify_citations.py", "--proposals", str(proposals_path),
                "--watchlist", str(watchlist_path), "--out", str(out_path),
                "--offline", "--fixtures", str(fixtures)]
        targets = [{"key": "X", "full_name": "Example Conference",
                    "aliases": ["X"]}]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(V.U, "load_existing", return_value={}), \
                mock.patch.object(V.U, "load_config", return_value=targets):
            code = V.main()

        self.assertEqual(code, 0)
        detail = json.loads(out_path.read_text(
            encoding="utf-8"))["verdicts"][0]["detail"]
        self.assertEqual(detail["source_trust"], "provisional")
        self.assertRegex(detail["source_trust_basis"],
                         r"^sha256:[0-9a-f]{64}$")


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
