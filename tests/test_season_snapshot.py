"""
Tests for GET /season-snapshot — BL-8: shareable winter profile card.

Covers:
  - Season inference helpers (get_ski_season_year, get_ski_season_label,
    get_ski_season_window)
  - Column distribution (distribute_columns_ss)
  - Route: auth guard, empty state, trip visibility, density tiers,
    pass display states, month labels, edge dates, guest trips,
    long names/destinations, season label, removed "This Winter"
"""
import re
import pytest
from datetime import date, timedelta

from app import app, get_ski_season_year, get_ski_season_label, get_ski_season_window, distribute_columns_ss
from models import db, GuestStatus
from tests.conftest import _make_user, _make_trip, _add_participant, _login


# ── Helpers ───────────────────────────────────────────────────────────────────

def _d(year, month, day=15):
    return date(year, month, day)


def _season_start_yr():
    """Return start year of the current ski season."""
    today = date.today()
    return today.year - 1 if today.month < 6 else today.year


def _in_season(month, day=15, offset_years=0):
    """Return a date within the current ski season.

    offset_years=0  → season start year
    offset_years=1  → season end year (for Jan–May months)
    """
    start_yr = _season_start_yr()
    return date(start_yr + offset_years, month, day)


# ── Season inference helpers ──────────────────────────────────────────────────

class TestSeasonInference:

    def test_aug_starts_new_season(self):
        assert get_ski_season_year(_d(2026, 8)) == (2026, 2027)

    def test_jan_is_in_earlier_season(self):
        assert get_ski_season_year(_d(2027, 1)) == (2026, 2027)

    def test_may_is_last_month_of_season(self):
        assert get_ski_season_year(_d(2027, 5)) == (2026, 2027)

    def test_jun_opens_next_season(self):
        assert get_ski_season_year(_d(2027, 6)) == (2027, 2028)

    def test_dec_is_in_start_year_season(self):
        assert get_ski_season_year(_d(2026, 12)) == (2026, 2027)

    def test_label_format_mid_season(self):
        assert get_ski_season_label(_d(2026, 11)) == "2026/27"

    def test_label_format_spring(self):
        assert get_ski_season_label(_d(2027, 3)) == "2026/27"

    def test_label_format_new_season_start(self):
        assert get_ski_season_label(_d(2027, 6)) == "2027/28"

    def test_window_start_boundary(self):
        start, end = get_ski_season_window(_d(2026, 11))
        assert start == date(2026, 6, 1)

    def test_window_end_boundary(self):
        start, end = get_ski_season_window(_d(2026, 11))
        assert end == date(2027, 5, 31)


# ── distribute_columns_ss ─────────────────────────────────────────────────────

class TestDistributeColumns:

    def test_single_column_passthrough(self):
        groups = [("JAN", ["Vail"]), ("FEB", ["Breckenridge"])]
        result = distribute_columns_ss(groups, 1)
        assert len(result) == 1
        assert result[0][0] == ("JAN", ["Vail"], False)
        assert result[0][1] == ("FEB", ["Breckenridge"], False)

    def test_empty_groups_returns_single_col(self):
        result = distribute_columns_ss([], 2)
        assert len(result) == 1
        assert result[0] == []

    def test_two_columns_no_split_needed(self):
        groups = [("NOV", ["A", "B"]), ("DEC", ["C", "D"])]
        result = distribute_columns_ss(groups, 2)
        assert len(result) == 2
        all_labels = [g[0] for col in result for g in col]
        assert "NOV" in all_labels
        assert "DEC" in all_labels

    def test_two_columns_total_trip_count(self):
        groups = [("NOV", ["A", "B"]), ("DEC", ["C", "D"])]
        result = distribute_columns_ss(groups, 2)
        total = sum(len(g[1]) for col in result for g in col)
        assert total == 4

    def test_continuation_flagged_when_month_splits(self):
        # 1 month with 4 trips → must split across 2 columns
        groups = [("JAN", ["A", "B", "C", "D"])]
        result = distribute_columns_ss(groups, 2)
        assert len(result) == 2
        has_continuation = any(g[2] for col in result for g in col)
        assert has_continuation

    def test_non_split_month_not_flagged(self):
        # Each month fits in one column — no continuations expected
        groups = [("NOV", ["A"]), ("DEC", ["B"]), ("JAN", ["C"])]
        result = distribute_columns_ss(groups, 3)
        non_continuation = [g for col in result for g in col if not g[2]]
        assert len(non_continuation) == 3

    def test_three_columns_returns_three_lists(self):
        groups = [("NOV", ["A"]), ("DEC", ["B"]), ("JAN", ["C"])]
        result = distribute_columns_ss(groups, 3)
        assert len(result) == 3

    def test_all_trips_preserved_across_columns(self):
        dests = [f"R{i}" for i in range(12)]
        groups = [("DEC", dests[:4]), ("JAN", dests[4:8]), ("FEB", dests[8:])]
        result = distribute_columns_ss(groups, 3)
        found = [d for col in result for g in col for d in g[1]]
        assert sorted(found) == sorted(dests)


# ── Route tests ───────────────────────────────────────────────────────────────

class TestSeasonSnapshotRoute:

    def _get(self, client):
        return client.get("/season-snapshot", follow_redirects=False)

    # ── Auth ──────────────────────────────────────────────────────────────────

    def test_requires_login(self, client):
        resp = self._get(client)
        assert resp.status_code in (302, 401)

    # ── Empty state ───────────────────────────────────────────────────────────

    def test_zero_trips_shows_empty_state(self, client):
        with app.app_context():
            u = _make_user("zero")
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert resp.status_code == 200
        assert b"Nothing planned yet" in resp.data

    def test_zero_trips_no_column_grid(self, client):
        with app.app_context():
            u = _make_user("zero2")
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        # The ss-columns div is only rendered when n_trips > 0
        assert b'class="ss-columns"' not in resp.data

    # ── 1 trip / 0 passes ─────────────────────────────────────────────────────

    def test_one_trip_zero_passes(self, client):
        with app.app_context():
            u = _make_user("one0p")
            u.pass_type = "no_pass"
            t = _make_trip(u, mountain="ZeroPassMtn",
                           start_date=_in_season(12), end_date=_in_season(12, 20))
            db.session.commit()
            uid = u.id; tname = t.mountain
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert resp.status_code == 200
        assert tname in html
        assert "NO PASS" in html
        assert 'data-density="1"' in html

    # ── 1 trip / 1 pass ───────────────────────────────────────────────────────

    def test_one_trip_one_pass_inline(self, client):
        with app.app_context():
            u = _make_user("one1p")
            u.pass_type = "epic"
            _make_trip(u, mountain="EpicMtn",
                       start_date=_in_season(12), end_date=_in_season(12, 20))
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert resp.status_code == 200
        # Epic should appear UPPERCASE inline in the meta row for 1-pass case
        assert "EPIC" in html
        assert "EpicMtn" in html

    # ── 3 trips ───────────────────────────────────────────────────────────────

    def test_three_trips_tier1(self, client):
        with app.app_context():
            u = _make_user("three")
            for i in range(3):
                _make_trip(u, mountain=f"Mountain{i}",
                           start_date=_in_season(11, 10 + i),
                           end_date=_in_season(11, 15 + i))
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert resp.status_code == 200
        assert 'data-density="1"' in html
        for i in range(3):
            assert f"Mountain{i}" in html

    # ── 5 trips ───────────────────────────────────────────────────────────────

    def test_five_trips_tier2(self, client):
        with app.app_context():
            u = _make_user("five")
            for i in range(5):
                _make_trip(u, mountain=f"Peak{i}",
                           start_date=_in_season(12, 2 + i),
                           end_date=_in_season(12, 7 + i))
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert 'data-density="2"' in html
        for i in range(5):
            assert f"Peak{i}" in html

    # ── 8 trips / 2 passes ────────────────────────────────────────────────────

    def test_eight_trips_two_passes_tier3(self, client):
        with app.app_context():
            u = _make_user("eight2p")
            u.pass_type = "epic,ikon"
            for i in range(8):
                _make_trip(u, mountain=f"Hill{i}",
                           start_date=_in_season(1, 5 + i, offset_years=1),
                           end_date=_in_season(1, 10 + i, offset_years=1))
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert 'data-density="3"' in html
        # 2 passes → separate pass row, not uppercase-inline
        assert "Epic" in html
        assert "Ikon" in html

    # ── 10 trips ──────────────────────────────────────────────────────────────

    def test_ten_trips_tier3(self, client):
        with app.app_context():
            u = _make_user("ten")
            for i in range(10):
                _make_trip(u, mountain=f"Top{i}",
                           start_date=_in_season(2, 1 + i, offset_years=1),
                           end_date=_in_season(2, 5 + i, offset_years=1))
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert 'data-density="3"' in resp.data.decode()

    # ── 15 trips / 3 passes ───────────────────────────────────────────────────

    def test_fifteen_trips_three_passes_tier4(self, client):
        with app.app_context():
            u = _make_user("fifteen3p")
            u.pass_type = "epic,ikon,indy"
            base = date(_season_start_yr(), 12, 1)
            for i in range(15):
                sd = base + timedelta(days=i)
                ed = sd + timedelta(days=4)
                _make_trip(u, mountain=f"Resort{i}", start_date=sd, end_date=ed)
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert 'data-density="4"' in html
        assert "Indy" in html

    # ── October trip (in season) ──────────────────────────────────────────────

    def test_october_trip_included(self, client):
        """October is within the season (season opens June 1)."""
        with app.app_context():
            u = _make_user("oct")
            _make_trip(u, mountain="OctoberMtn",
                       start_date=_in_season(10), end_date=_in_season(10, 20))
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert "OctoberMtn" in html
        assert "OCT" in html

    # ── May trip (in season) ──────────────────────────────────────────────────

    def test_may_trip_included(self, client):
        """May is the last month of the season (season closes May 31)."""
        with app.app_context():
            u = _make_user("may")
            _make_trip(u, mountain="MayMtn",
                       start_date=_in_season(5, offset_years=1),
                       end_date=_in_season(5, 20, offset_years=1))
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert "MayMtn" in html
        assert "MAY" in html

    # ── Past trip in current season ───────────────────────────────────────────

    def test_past_trip_in_season_included(self, client):
        """Trips whose end_date < today but start_date is in season must appear.

        This is the key BL-8 behaviour: we filter by start_date, not end_date.
        """
        today = date.today()
        season_start, _ = get_ski_season_window(today)
        trip_start = today - timedelta(days=6)
        trip_end = today - timedelta(days=1)
        if trip_start < season_start:
            pytest.skip("Trip date falls before season start; edge case near June 1")

        with app.app_context():
            u = _make_user("past")
            _make_trip(u, mountain="PastPeak", start_date=trip_start, end_date=trip_end)
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert b"PastPeak" in resp.data

    # ── Out-of-season trip excluded ───────────────────────────────────────────

    def test_out_of_season_trip_excluded(self, client):
        """A trip whose start_date is in the next season is not shown."""
        with app.app_context():
            u = _make_user("nextseason")
            # June of the next season's start year = first day of following season
            next_season_start_yr = _season_start_yr() + 1
            sd = date(next_season_start_yr, 6, 15)
            ed = date(next_season_start_yr, 6, 20)
            _make_trip(u, mountain="NextSeasonMtn", start_date=sd, end_date=ed)
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert b"NextSeasonMtn" not in resp.data
        assert b"Nothing planned yet" in resp.data

    # ── Accepted guest trip ───────────────────────────────────────────────────

    def test_accepted_guest_trip_included(self, client):
        """Accepted guest trips in the season appear on the guest's card."""
        with app.app_context():
            owner = _make_user("gowner")
            guest = _make_user("guest")
            t = _make_trip(owner, mountain="GuestMtn",
                           start_date=_in_season(1, offset_years=1),
                           end_date=_in_season(1, 20, offset_years=1))
            _add_participant(t, guest, status=GuestStatus.INTERESTED)
            db.session.commit()
            gid = guest.id
        _login(client, gid)
        resp = self._get(client)
        assert b"GuestMtn" in resp.data

    def test_cross_season_parent_uses_in_season_going_override(self, client):
        """A guest override is evaluated before the parent start is excluded."""
        season_start, _ = get_ski_season_window(date.today())
        with app.app_context():
            owner = _make_user("crossseason-owner")
            guest = _make_user("crossseason-guest")
            trip = _make_trip(
                owner,
                mountain="CrossSeasonGuestMtn",
                start_date=season_start - timedelta(days=2),
                end_date=season_start + timedelta(days=5),
            )
            participant = _add_participant(
                trip, guest, status=GuestStatus.GOING
            )
            participant.start_date = season_start + timedelta(days=1)
            participant.end_date = season_start + timedelta(days=3)
            db.session.commit()
            guest_id = guest.id

        _login(client, guest_id)
        html = self._get(client).data
        assert b"CrossSeasonGuestMtn" in html
        assert b"JUN" in html

    def test_in_season_parent_excludes_out_of_season_going_override(self, client):
        """A complete guest override outside the season controls inclusion."""
        season_start, season_end = get_ski_season_window(date.today())
        with app.app_context():
            owner = _make_user("outsideoverride-owner")
            guest = _make_user("outsideoverride-guest")
            trip = _make_trip(
                owner,
                mountain="OutsideOverrideMtn",
                start_date=season_start + timedelta(days=10),
                end_date=season_start + timedelta(days=15),
            )
            participant = _add_participant(
                trip, guest, status=GuestStatus.GOING
            )
            participant.start_date = season_end + timedelta(days=1)
            participant.end_date = season_end + timedelta(days=3)
            db.session.commit()
            guest_id = guest.id

        _login(client, guest_id)
        html = self._get(client).data
        assert b"OutsideOverrideMtn" not in html
        assert b"Nothing planned yet" in html

    @pytest.mark.parametrize(
        ("boundary_name", "expected_month"),
        [("start", b"JUN"), ("end", b"MAY")],
    )
    def test_going_override_start_includes_season_boundaries(
        self, client, boundary_name, expected_month
    ):
        """Effective starts on June 1 and May 31 are both included."""
        season_start, season_end = get_ski_season_window(date.today())
        boundary = season_start if boundary_name == "start" else season_end
        with app.app_context():
            owner = _make_user(f"boundary-{boundary_name}-owner")
            guest = _make_user(f"boundary-{boundary_name}-guest")
            trip = _make_trip(
                owner,
                mountain=f"Boundary{boundary_name.title()}Mtn",
                start_date=season_start - timedelta(days=2),
                end_date=season_start + timedelta(days=5),
            )
            participant = _add_participant(
                trip, guest, status=GuestStatus.GOING
            )
            participant.start_date = boundary
            participant.end_date = boundary + timedelta(days=1)
            db.session.commit()
            guest_id = guest.id

        _login(client, guest_id)
        html = self._get(client).data
        assert f"Boundary{boundary_name.title()}Mtn".encode() in html
        assert expected_month in html

    def test_going_guest_without_override_uses_parent_dates(self, client):
        """A Going guest without overrides retains parent-date behavior."""
        with app.app_context():
            owner = _make_user("nooverride-owner")
            guest = _make_user("nooverride-guest")
            trip = _make_trip(
                owner,
                mountain="NoOverrideMtn",
                start_date=_in_season(12),
                end_date=_in_season(12, 20),
            )
            _add_participant(trip, guest, status=GuestStatus.GOING)
            db.session.commit()
            guest_id = guest.id

        _login(client, guest_id)
        html = self._get(client).data
        assert b"NoOverrideMtn" in html
        assert b"DEC" in html

    def test_partial_going_override_falls_back_to_parent_dates(self, client):
        """One guest override date is ignored in favor of the parent range."""
        _, season_end = get_ski_season_window(date.today())
        with app.app_context():
            owner = _make_user("partialoverride-owner")
            guest = _make_user("partialoverride-guest")
            trip = _make_trip(
                owner,
                mountain="PartialOverrideMtn",
                start_date=_in_season(1, offset_years=1),
                end_date=_in_season(1, 20, offset_years=1),
            )
            participant = _add_participant(
                trip, guest, status=GuestStatus.GOING
            )
            participant.start_date = season_end + timedelta(days=1)
            db.session.commit()
            guest_id = guest.id

        _login(client, guest_id)
        html = self._get(client).data
        assert b"PartialOverrideMtn" in html
        assert b"JAN" in html

    def test_interested_guest_with_stale_overrides_uses_parent_dates(self, client):
        """Non-Going participants retain the organizer's trip dates."""
        _, season_end = get_ski_season_window(date.today())
        with app.app_context():
            owner = _make_user("interestedoverride-owner")
            guest = _make_user("interestedoverride-guest")
            trip = _make_trip(
                owner,
                mountain="InterestedOverrideMtn",
                start_date=_in_season(2, offset_years=1),
                end_date=_in_season(2, 20, offset_years=1),
            )
            participant = _add_participant(
                trip, guest, status=GuestStatus.INTERESTED
            )
            participant.start_date = season_end + timedelta(days=1)
            participant.end_date = season_end + timedelta(days=3)
            db.session.commit()
            guest_id = guest.id

        _login(client, guest_id)
        html = self._get(client).data
        assert b"InterestedOverrideMtn" in html
        assert b"FEB" in html

    def test_guest_trip_not_duplicated_for_owner(self, client):
        """A trip the owner has already accepted as a participant is not duplicated."""
        with app.app_context():
            owner = _make_user("gowner2")
            t = _make_trip(owner, mountain="OwnerMtn",
                           start_date=_in_season(12),
                           end_date=_in_season(12, 20))
            db.session.commit()
            uid = owner.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert html.count("OwnerMtn") == 1

    # ── Long first name ───────────────────────────────────────────────────────

    def test_long_first_name_renders(self, client):
        """Long first names render in full — no truncation."""
        with app.app_context():
            u = _make_user("longname")
            u.first_name = "Bartholomew-Alejandro"
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert b"Bartholomew-Alejandro" in resp.data

    # ── Long destination ──────────────────────────────────────────────────────

    def test_long_destination_renders(self, client):
        """Long destination names render in full — no truncation."""
        with app.app_context():
            u = _make_user("longdest")
            _make_trip(u, mountain="Whistler Blackcomb Mountain Resort",
                       start_date=_in_season(2, offset_years=1),
                       end_date=_in_season(2, 20, offset_years=1))
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert b"Whistler Blackcomb Mountain Resort" in resp.data

    # ── Multiple trips in same month ──────────────────────────────────────────

    def test_multiple_trips_same_month(self, client):
        """Multiple trips in the same month share one month label."""
        with app.app_context():
            u = _make_user("samemonth")
            _make_trip(u, mountain="AlphaResort",
                       start_date=_in_season(1, 5, offset_years=1),
                       end_date=_in_season(1, 8, offset_years=1))
            _make_trip(u, mountain="BetaResort",
                       start_date=_in_season(1, 20, offset_years=1),
                       end_date=_in_season(1, 23, offset_years=1))
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert "AlphaResort" in html
        assert "BetaResort" in html
        assert "JAN" in html

    # ── Season label ──────────────────────────────────────────────────────────

    def test_season_label_in_header(self, client):
        """A YYYY/YY season label appears in the card title."""
        with app.app_context():
            u = _make_user("label")
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert re.search(rb'\d{4}/\d{2}', resp.data), "Season label not found"

    # ── Removed "This Winter" element ────────────────────────────────────────

    def test_no_this_winter_element(self, client):
        """The old 'This Winter' attribution label is removed from the card."""
        with app.app_context():
            u = _make_user("nothis")
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert b"This Winter" not in resp.data

    # ── Tagline preserved ─────────────────────────────────────────────────────

    def test_tagline_preserved(self, client):
        """The .ss-tagline editorial text outside the card is unchanged."""
        with app.app_context():
            u = _make_user("tagline")
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert b"snapshot of your winter" in resp.data

    # ── 'in BaseLodge' brand ─────────────────────────────────────────────────

    def test_in_baselodge_brand_present(self, client):
        """'in BaseLodge' brand line is rendered in the header."""
        with app.app_context():
            u = _make_user("brand")
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        assert b"in BaseLodge" in resp.data

    # ── Fixed 4:5 aspect ratio marker ────────────────────────────────────────

    def test_card_has_fixed_aspect_ratio(self, client):
        """The card element carries the 4:5 aspect-ratio constraint."""
        with app.app_context():
            u = _make_user("ratio")
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert "aspect-ratio: 4 / 5" in html

    # ── 21+ trips ultra-compact ───────────────────────────────────────────────

    def test_twentytwo_trips_tier5_ultra_compact(self, client):
        with app.app_context():
            u = _make_user("ultra")
            base = date(_season_start_yr(), 11, 1)
            for i in range(22):
                sd = base + timedelta(days=i * 2)
                ed = sd + timedelta(days=1)
                _make_trip(u, mountain=f"UltraMtn{i}", start_date=sd, end_date=ed)
            db.session.commit()
            uid = u.id
        _login(client, uid)
        resp = self._get(client)
        html = resp.data.decode()
        assert 'data-density="5"' in html
        assert "UltraMtn0" in html
        assert "UltraMtn21" in html
