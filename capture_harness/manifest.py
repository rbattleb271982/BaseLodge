"""The Phase 3 mobile capture matrix.

This module deliberately contains descriptions, not fixture data.  Logical IDs
are resolved by the isolated capture server when a run is performed.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

PERSONAS = ("empty", "light", "typical", "heavy", "extreme", "edge")
VIEWPORTS = {
    "mobile": {"width": 390, "height": 844},
    "narrow": {"width": 360, "height": 800},
}
FORBIDDEN = ("/admin", "/location-setup", "/planning-window", "/overlap-detail")
PERSONA_IDS = {f"persona-{p}" for p in PERSONAS}
DISCOVERED_ISSUES = (
    {
        "requested_state": "profile buddy-pass modal",
        "reason": (
            "The buddy-pass modal partial is not included by any active route "
            "template, so the state is not currently reachable without changing product UI."
        ),
    },
)
ROUTE_IDS = {
    "home", "trips", "trip", "mountains", "mountain", "friends", "friend",
    "wishlist", "visited", "availability", "open-ski", "profile", "equipment",
    "ski-days", "notifications", "season-snapshot", "auth", "onboarding",
    "create-trip", "invite", "push-settings", "error-404",
}
SEGMENTS = {
    "home": ("top", "ideas-happening", "lower-intelligence"),
    "trips": ("top-upcoming", "continuation", "history", "friends-trips", "season-snapshot"),
    "trip": ("hero", "people", "you", "stay-transport", "planning", "organizer-actions", "modal-invite"),
    "friends": ("top", "continuation", "suggestions", "filters-search"),
    "mountains": ("results", "filters"),
    "mountain": ("hero", "community"),
    "profile": ("top", "overlays-settings"),
}


def _row(area: str, screen: str, persona: str, state: str, route: str,
         segment: str, bindings: dict[str, str] | None = None,
         interaction: str = "none", wait: str = "document-ready",
         control: str | None = None, viewport: str = "mobile",
         rationale: str = "Covers a distinct supported mobile product state.") -> dict[str, Any]:
    bindings = bindings or {}
    ident = f"{screen}__{persona}__{state}__{viewport}__{segment}"
    return {
        "capture_id": ident, "id": ident, "product_area": area, "area": area,
        "screen": screen, "route_template": route, "route": route,
        "persona": persona, "state": state, "viewport": VIEWPORTS[viewport].copy(),
        "viewport_name": viewport, "segment": segment,
        "logical_route_bindings": bindings, "bindings": bindings,
        "preconditions": [f"persona:{persona}", "capture-runtime"],
        "interaction": interaction, "deterministic_wait_condition": wait,
        "state_control": control, "interception": control,
        "output_path": f"capture-output/screenshots/{area}/{ident}.png",
        "rationale": rationale,
    }


def build_manifest() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    def add(area, screen, persona, state, route, segment, **kw):
        rows.append(_row(area, screen, persona, state, route, segment, **kw))
    # Auth and onboarding
    for state, seg in (("default", "login"), ("validation-error", "login"),
                       ("forgot-password", "forgot-password"), ("invite-context", "invite")):
        add("auth", "auth", "edge", state,
            "/invite/{invite_id}" if state == "invite-context" else "/auth",
            seg,
            bindings={"invite_id": "capture-friend-invite"}
            if state == "invite-context" else {},
            wait="auth-form-visible")
    for state, seg in (("welcome", "welcome"), ("pass", "pass-selection"),
                       ("rider-type", "rider-type"), ("validation", "validation")):
        add("onboarding", "onboarding", "empty", state, "/setup-profile?step={step}", seg,
            bindings={"step": "onboarding-step"}, interaction="select deterministic option",
            wait="onboarding-step-visible")
    # Home (includes the high-density and narrow stress captures).
    home = [("empty","empty","empty"),("default","light","top"),("default","typical","top"),
            ("dense","heavy","top"),("ideas","heavy","ideas-happening"),
            ("happening","heavy","ideas-happening"),("ideas-happening","heavy","ideas-happening"),
            ("availability","heavy","lower-intelligence"),("profile-intelligence","heavy","lower-intelligence"),
            ("narrow-dense","heavy","ideas-happening"),("pending-invite","typical","top"),
            ("next-trip-participant","typical","top"),("extreme-wrap","extreme","top"),
            ("edge-error","edge","top")]
    for state, persona, seg in home:
        add("home", "home", persona, state, "/home", seg, viewport="narrow" if state == "narrow-dense" else "mobile",
            wait="home-content-visible")
    # Trips; Season Snapshot is an explicit populated surface.
    trips = [("empty","empty","top-upcoming"),("typical","typical","top-upcoming"),
             ("heavy-upcoming","heavy","top-upcoming"),("continuation","heavy","continuation"),
             ("history","heavy","history"),("friends-trips","heavy","friends-trips"),
             ("season-snapshot","heavy","season-snapshot"),("filter-sheet","heavy","top-upcoming"),
             ("no-filter-results","edge","top-upcoming"),("progressive-loading","edge","friends-trips"),
             ("error-retry","edge","friends-trips"),("narrow-15-trips","heavy","continuation"),
              ("three-invitations","heavy","top-upcoming"),("accept-choice","heavy","top-upcoming")]
    for state, persona, seg in trips:
        add("trips", "trips", persona, state, "/season-snapshot" if state == "season-snapshot" else "/my-trips", seg,
            viewport="narrow" if state == "narrow-15-trips" else "mobile",
            interaction="open Season Snapshot" if state == "season-snapshot" else "none",
            wait="trips-state-visible", control="transport-error" if state == "error-retry" else None)
    # Batch 2 Both ledger: the query route is part of the capture contract.
    both_captures = (
        ("both-normal", "typical", "mobile"),
        ("both-heavy", "heavy", "mobile"),
        ("both-multiple-overlaps", "heavy", "mobile"),
        ("both-standalone-opportunities", "heavy", "mobile"),
        ("both-no-relevant-friend-activity", "typical", "mobile"),
        ("both-heavy-narrow", "heavy", "narrow"),
        ("mine-regression", "heavy", "mobile"),
    )
    for state, persona, viewport in both_captures:
        route = "/my-trips?tab=both" if state != "mine-regression" else "/my-trips"
        add("trips", "trips", persona, state, route, "friends-trips",
            viewport=viewport, wait="trips-state-visible",
            rationale="Batch 2 approved compact Both/Mine ledger capture.")
    # Create trip.
    for state, interaction in (("empty-form","none"),("resort-results","search resort"),
                               ("dates-selected","select deterministic dates"),("validation-error","submit invalid form")):
        add("create-trip","create-trip","typical" if state != "validation-error" else "edge",state,
            "/add_trip", "form", interaction=interaction, wait="trip-form-visible")
    # Trip detail.
    td = [("organizer","heavy","hero"),("organizer-people","heavy","people"),("organizer-you","heavy","you"),
          ("going","heavy","people"),("interested","typical","people"),
          ("pending-invitee","edge","hero"),("private","heavy","hero"),("past-read-only","edge","hero"),
          ("empty-roster","light","people"),("dense-roster","heavy","people"),("planning-populated","heavy","planning"),
          ("invite-modal","heavy","modal-invite")]
    for state, persona, seg in td:
        trip_binding = {
            "organizer": "HT04",
            "organizer-people": "HT04",
            "organizer-you": "HT04",
            "going": "HT04",
            "interested": "TD_INTERESTED",
            "pending-invitee": "TD_PENDING",
            "private": "HT05",
            "past-read-only": "TD_PAST",
            "empty-roster": "TD_EMPTY",
            "dense-roster": "HT04",
            "planning-populated": "HT04",
            "invite-modal": "HT04",
        }[state]
        add("trip-detail","trip-detail",persona,state,"/trips/{trip_id}",seg,
            bindings={"trip_id": trip_binding},
            viewport="narrow" if state=="dense-roster" else "mobile",
            interaction="open invitation sheet" if state=="invite-modal" else "none",
            wait="trip-detail-visible")
    # Friends and friend read-only surfaces.
    friends = [("empty","empty","top"),("typical","typical","top"),("heavy-25-friends","heavy","top"),
               ("pagination","heavy","continuation"),("suggestions","typical","suggestions"),
               ("suggestions-loading","edge","suggestions"),("suggestions-error","edge","suggestions"),
               ("filters-search","heavy","filters-search"),("narrow-dense","heavy","continuation"),
               ("pending-requests","typical","top")]
    for state, persona, seg in friends:
        add("friends","friends",persona,state,"/friends",seg,
            viewport="narrow" if state=="narrow-dense" else "mobile",
            interaction="open Suggested tab" if "suggestions" in state else "none",
            wait="friends-state-visible",
            control="transport-error" if state=="suggestions-error" else ("hold-response" if state=="suggestions-loading" else None))
    for state, seg in (("complete","top"),("shared-context","top"),("high-overlap","top")):
        add("friend-profile","friend-profile","heavy",state,"/friends/{friend_id}",seg,
            bindings={"friend_id":"HF01"}, wait="friend-profile-visible")
    # Mountains and mountain detail; loading/error are separate rows.
    for state, persona, seg in (("default","typical","results"),("populated","heavy","results"),
                                ("search","typical","results"),("no-results","edge","results"),
                                ("filters","heavy","filters")):
        add("mountains","mountains",persona,state,"/mountains",seg,wait="mountain-results-visible")
    md = [("on-pass","heavy","hero"),("visited-wishlisted","heavy","hero"),
          ("social-success","heavy","community"),("social-empty","edge","community"),
          ("social-loading","edge","community"),("social-error","edge","community"),
          ("dense-narrow","heavy","community"),("off-pass","typical","hero")]
    for state, persona, seg in md:
        add("mountain-detail","mountain-detail",persona,state,"/mountain/{mountain_slug}",seg,
            bindings={"mountain_slug":"capture-aspen"}, viewport="narrow" if state=="dense-narrow" else "mobile",
            wait="mountain-social-state", control="transport-error" if state=="social-error" else ("hold-response" if state=="social-loading" else None))
    # Profile collections and settings.
    for state, persona, seg in (("empty","empty","top"),("complete","heavy","top"),
                                ("wishlist-overlay","heavy","overlays-settings"),
                                ("delete-account-modal","heavy","overlays-settings"),
                                ("settings","typical","overlays-settings")):
        add("profile","profile",persona,state,"/profile",seg,
            interaction="open delete-account modal" if state=="delete-account-modal" else "none",
            wait="profile-visible")
    for state, persona in (("empty","empty"),("maximum-15","heavy"),("friend-read-only","heavy")):
        add("wishlist","wishlist",persona,state,"/settings/wish-list" if state!="friend-read-only" else "/wishlist/{friend_id}",
            "list", bindings={"friend_id":"HF01"} if state=="friend-read-only" else {}, wait="wishlist-visible")
    for state, persona in (("empty","empty"),("friend-read-only","heavy")):
        add("visited","visited",persona,state,"/mountains-visited" if state=="empty" else "/mountains-visited/{friend_id}",
            "list", bindings={"friend_id":"HF01"} if state=="friend-read-only" else {}, wait="visited-visible")
    for state, persona in (("none","empty"),("multi-month","heavy"),("validation","edge")):
        add("availability","availability",persona,state,"/add-open-dates","calendar",wait="availability-visible")
    for state, persona in (("no-dates","empty"),("dense-card","heavy"),("export-error","edge")):
        add("open-ski","open-ski",persona,state,"/open-to-ski","card",
            wait="open-ski-visible", control="transport-error" if state=="export-error" else None)
    for state, persona in (("empty","empty"),("complete","heavy")):
        add("equipment","equipment",persona,state,"/settings/equipment","setup",wait="equipment-visible")
    for state, persona in (("empty","empty"),("populated","heavy")):
        add("ski-days","ski-days",persona,state,"/profile/ski-days","history",wait="ski-days-visible")
    for state, persona in (("empty","empty"),("dense-unread","heavy"),("typical","typical")):
        add("notifications","notifications",persona,state,"/notifications","list",wait="notifications-visible")
    # User-facing system outcomes, never JSON/API-only routes.
    for state, route in (("403","/profile/{user_id}"),("404","/capture-intentional-404"),("500","/capture-intentional-500"),
                          ("global-flash","/capture-global-flash"),("retry","/friends"),("invalid-invite","/invite/{invite_id}")):
        add("system","system","edge",state,route,"top",
            bindings={"invite_id":"invite-edge", "user_id":"1"} if "{invite_id}" in route or "{user_id}" in route else {},
            wait="error-state-visible", control="transport-error" if state=="500" else None)
    return rows


MANIFEST = build_manifest()


def validate_manifest(rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = MANIFEST if rows is None else rows
    if len(rows) != 114:
        raise ValueError(f"capture manifest must contain exactly 114 rows (got {len(rows)})")
    ids = [r["capture_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("capture IDs must be unique")
    for row in rows:
        if row["persona"] not in PERSONAS or row["viewport_name"] not in VIEWPORTS:
            raise ValueError(f"invalid persona or viewport in {row['capture_id']}")
        if row["viewport"] not in VIEWPORTS.values():
            raise ValueError(f"invalid viewport in {row['capture_id']}")
        if any(row["route_template"].startswith(path) for path in FORBIDDEN):
            raise ValueError(f"forbidden route in {row['capture_id']}")
        if re.search(r"\b(desktop|admin)\b", row["route_template"], re.I):
            raise ValueError(f"desktop/admin route in {row['capture_id']}")
        for key in re.findall(r"{([^}]+)}", row["route_template"]):
            if key not in row["logical_route_bindings"]:
                raise ValueError(f"unbound route key {key} in {row['capture_id']}")
    return rows


validate_manifest()