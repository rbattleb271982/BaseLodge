# BaseLodge Consumer UI — Baseline Populated-State Supplement

## Scope

- Development environment only.
- `seed_screenshots.py` baseline fixture only.
- `seed_screenshots_expansion.py` was **not run**.
- Mobile screenshots only.
- No application code, templates, CSS, JavaScript, configuration, workflow, Git, or production data changes were made.
- No form submissions or other mutating screenshot interactions were performed.

## Development dataset after baseline

| Model | Count / result |
|---|---|
| Users | 9 total (1 pre-existing development user + 8 baseline fixture users) |
| Friend rows | 10 directed rows / 5 reciprocal friend relationships for the primary screenshot user |
| Trips | 15 total; 5 owned by the primary screenshot user |
| Trip participants | 1 legacy `ACCEPTED` row |
| Invitations | 2 pending friend requests |
| Availability | 0 |
| Trip planning posts | 0 |
| Activity notifications | 0 |

## Coverage and expansion assessment

| Requested state | Baseline result | Would expansion fill it? | Evidence |
|---|---|---|---|
| Home/feed activity | Available | Yes | Populated Home feed with 5 upcoming trips, 5 friends, friend-trip activity, and a pending friend request. |
| Multiple trips | Available | Yes | 5 primary-user trips plus populated Friends’ Trips. |
| Owner trip detail | Available, but participant not visible | No | Owner view captured. The baseline participant row uses legacy ACCEPTED status, which the current UI does not list as Going or Interested. Expansion also seeds ACCEPTED, so it would not fix this state. |
| Participant trip detail | Unavailable as active participant | No | The baseline ACCEPTED row is excluded by the active RSVP filter; the friend-trip UI shows Request to join. Expansion uses the same legacy status. |
| Trip planning content | Unavailable | No | No SkiTripPlanningPost rows. The expansion fixture does not seed planning posts. |
| Friends list and friend profile | Available | Yes | 5 connected friends, a pending inbound request, and populated friend profiles. |
| Mountain social activity | Unavailable | No reliable fill | Seeded friend trips did not surface on tested mountain detail pages. Expansion adds more users/trips but no mountain-social fixture record type. |
| Trip overlap results | Available | Yes | Explicit Whistler overlap between John and Mia. |
| Availability/open dates | Unavailable | Yes | 0 UserAvailability rows after baseline; expansion explicitly seeds availability windows. |
| Wishlist | Available | Yes | 2 wishlist mountains. |
| Distinct trip ideas view | Unavailable | Yes, expected | Baseline /trip-ideas redirects to Home; expansion adds availability and group-trip context intended to populate ideas. |
| Notifications/activity | Unavailable | Yes | 0 Activity rows after baseline; expansion explicitly seeds activity notifications. |

## Screenshot files

### 1. `02-home/home_feed-populated-baseline_mobile.png`
- **Area:** Home
- **Screen:** Home feed
- **State:** Five upcoming trips, five friends, and pending request
- **Route:** `/home`
- **Capture:** 390 px wide, full page
- **Description:** Populated Home feed from the baseline fixture with the availability prompt closed client-side so activity cards remain visible.

### 2. `03-trips/trips_friend-trip-request-to-join-baseline_mobile.png`
- **Area:** Trips
- **Screen:** Friend trip detail
- **State:** Friend trip with request-to-join CTA
- **Route:** `/friend-trip/9`
- **Capture:** 390 px wide, full page
- **Description:** Friend-owned Aspen trip viewed by John. The baseline legacy ACCEPTED row is not treated as an active participant by the current RSVP UI, so this screen presents Request to join.

### 3. `03-trips/trips_friends-trips-populated-baseline_mobile.png`
- **Area:** Trips
- **Screen:** Friends' Trips
- **State:** Friends' Trips tab with friend trips
- **Route:** `/my-trips?tab=friends`
- **Capture:** 390 px wide, full page
- **Description:** Friends' Trips tab showing the baseline fixture's connected-friend trips.

### 4. `03-trips/trips_overlap-results-whistler-baseline_mobile.png`
- **Area:** Trips
- **Screen:** Trip overlap
- **State:** Whistler overlap with one connected friend
- **Route:** `/overlap-detail?type=trip&friends=3&resort_id=656&start_date=2026-12-28&end_date=2027-01-02&mountain=Whistler%20Blackcomb`
- **Capture:** 390 px wide, full page
- **Description:** Explicit overlap result for the shared Whistler date window between John and Mia.

### 5. `03-trips/trips_trip-detail-owner-baseline_mobile.png`
- **Area:** Trips
- **Screen:** Trip detail
- **State:** Trip owner view; fixture participant not visibly surfaced
- **Route:** `/trips/9`
- **Capture:** 390 px wide, full page
- **Description:** Jordan owner view of the baseline Aspen trip. The fixture has an accepted participant row, but this current owner UI does not visibly list that legacy status.

### 6. `03-trips/trips_trip-list-populated-baseline_mobile.png`
- **Area:** Trips
- **Screen:** My Trips
- **State:** Five trips across planning and going statuses
- **Route:** `/my-trips`
- **Capture:** 390 px wide, full page
- **Description:** My Trips list with multiple upcoming trips from the baseline fixture.

### 7. `04-mountains/mountains_mountain-detail-vail-history-baseline_mobile.png`
- **Area:** Mountains
- **Screen:** Mountain detail
- **State:** Visited mountain with trip CTA
- **Route:** `/mountain/vail-us`
- **Capture:** 390 px wide, full page
- **Description:** Vail detail for the baseline user, showing visited status and trip actions. The baseline friend trips are not surfaced as social activity on this detail page.

### 8. `05-friends-social/friends_friend-profile-mia-baseline_mobile.png`
- **Area:** Friends and social
- **Screen:** Friend profile
- **State:** Connected friend profile
- **Route:** `/friends/3`
- **Capture:** 390 px wide, full page
- **Description:** Mia Chen friend profile with baseline profile and mountain context.

### 9. `05-friends-social/friends_friends-list-populated-baseline_mobile.png`
- **Area:** Friends and social
- **Screen:** Friends list
- **State:** Five friends and pending requests
- **Route:** `/friends`
- **Capture:** 390 px wide, full page
- **Description:** Friends page with multiple accepted connections and pending social states from the baseline fixture.

### 10. `06-profile-settings/profile_mountains-visited-populated-baseline_mobile.png`
- **Area:** Profile and settings
- **Screen:** Mountains visited
- **State:** Five visited mountains
- **Route:** `/mountains-visited`
- **Capture:** 390 × 664 CSS px viewport
- **Description:** Visited-mountains view positioned at the first selected baseline mountain.

### 11. `06-profile-settings/profile_profile-populated-baseline_mobile.png`
- **Area:** Profile and settings
- **Screen:** Profile
- **State:** Pass, trips, wishlist, and visited-mountain context
- **Route:** `/profile`
- **Capture:** 390 px wide, full page
- **Description:** Primary screenshot profile with populated baseline identity and mountain stats.

### 12. `06-profile-settings/profile_wishlist-populated-baseline_mobile.png`
- **Area:** Profile and settings
- **Screen:** Wishlist
- **State:** Two wishlist mountains
- **Route:** `/settings/wish-list`
- **Capture:** 390 × 664 CSS px viewport
- **Description:** Wishlist settings positioned at the first selected baseline mountain.

## Important evidence notes

- The included friend-trip screenshot documents the current `Request to join` rendering; it is not mislabeled as an accepted-participant state.
- The included owner trip detail documents the populated owner screen, but the legacy `ACCEPTED` participant is not visibly surfaced.
- The included Vail mountain detail documents populated visited-history state, not friend/social activity.
- The original 48-image export remains separate; this ZIP is only the populated-state supplement.
