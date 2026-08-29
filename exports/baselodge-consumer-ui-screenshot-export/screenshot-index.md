# BaseLodge Consumer UI Screenshot Export

**Capture date:** August 28, 2026 (America/Denver)  
**Screenshots:** 48 PNG files  
**Scope:** Current consumer-facing BaseLodge experience only. Admin, analytics, operations, diagnostics, and internal tools are excluded.

## Capture context

- Captured from the running BaseLodge development server with its existing development data.
- Mobile captures use an emulated iPhone 13 viewport (390 × 664 CSS px, 3× device scale).
- Desktop captures use a 1440 × 1000 CSS px viewport.
- The current development database had one active consumer profile, no friends, and no trips. The resort catalog was available.
- No seed route was run, no form was submitted, and no application files were changed.
- Browser POST, PUT, PATCH, and DELETE requests were blocked during capture. Client-side selections shown in screenshots were not saved.
- Full-page capture was used only where it helped show a complete form, policy, or settings list. Other captures show the actual visible viewport.

## Folder map

- `01-auth-onboarding/` — login, signup, password recovery, and onboarding
- `02-home/` — Home/feed
- `03-trips/` — Trips, trip creation, availability, and overlap
- `04-mountains/` — mountain list and detail
- `05-friends-social/` — friends, connect, and invite sharing
- `06-profile-settings/` — profile, settings, notifications, gear, wishlist, and ski days
- `07-other-consumer-flows/` — invalid invite landings, feedback, privacy, and terms

## Screenshot index

| Filename | Product area | Screen | Requested route | Final route | Viewport | State | Description |
|---|---|---|---|---|---|---|---|
| `01-auth-onboarding/auth_login-default_desktop.png` | Authentication | Login | `/auth` | `/auth` | Desktop — 1440 × 1000 CSS px viewport | Default login form | Logged-out login screen at a wide desktop viewport. |
| `01-auth-onboarding/auth_login-default_mobile.png` | Authentication | Login | `/auth` | `/auth` | Mobile — 390 × 664 CSS px viewport | Default login form | Logged-out BaseLodge login screen at an iPhone-sized viewport. |
| `01-auth-onboarding/auth_password-recovery-default_mobile.png` | Authentication | Password recovery | `/forgot-password` | `/forgot-password` | Mobile — 390 × 664 CSS px viewport | Request reset link | Password recovery email-entry screen. |
| `01-auth-onboarding/auth_password-reset-invalid-link_mobile.png` | Authentication | Password reset | `/reset-password/not-a-valid-token` | `/auth` | Mobile — 390 × 664 CSS px viewport | Invalid or expired reset link | Password reset experience for an invalid token; no reset request was sent. |
| `01-auth-onboarding/auth_signup-default_desktop.png` | Authentication | Signup | `/signup` | `/signup` | Desktop — 1440 × 1000 CSS px viewport | Default signup form | Account creation form at a wide desktop viewport. |
| `01-auth-onboarding/auth_signup-default_mobile.png` | Authentication | Signup | `/signup` | `/signup` | Mobile — 390 × 664 CSS px viewport | Default signup form | Account creation form with password requirements and legal links. |
| `01-auth-onboarding/onboarding_identity-profile-step_desktop.png` | Onboarding | Identity and profile setup | `/onboarding` | `/onboarding` | Desktop — 1440 × 1000 CSS px viewport | Step 1 — rider type and skill | First onboarding step at desktop width. |
| `01-auth-onboarding/onboarding_identity-profile-step_mobile.png` | Onboarding | Identity and profile setup | `/onboarding` | `/onboarding` | Mobile — 390 × 664 CSS px viewport | Step 1 — rider type and skill | First onboarding step for rider identity and skill selection. |
| `01-auth-onboarding/onboarding_location-selection-step_mobile.png` | Onboarding | Location setup | `/onboarding` | `/onboarding` | Mobile — 390 × 664 CSS px viewport | Step 3 — location selection | Third onboarding step reached entirely client-side; no form submission occurred. |
| `01-auth-onboarding/onboarding_pass-selection-settings_mobile.png` | Onboarding and profile | Pass selection | `/select-pass` | `/select-pass` | Mobile — 390 px wide, full page | Existing-user pass selector | Standalone pass-selection screen used after onboarding. |
| `01-auth-onboarding/onboarding_pass-selection-step_mobile.png` | Onboarding | Pass selection | `/onboarding` | `/onboarding` | Mobile — 390 × 664 CSS px viewport | Step 2 — pass selection | Second onboarding step after selecting Skier and Advanced; no form submission occurred. |
| `02-home/home_feed-no-availability-empty_desktop.png` | Home | Home feed | `/home` | `/home` | Desktop — 1440 px wide, full page | No trips, friends, availability, or ideas | Home empty state showing the desktop max-width app shell and navigation. |
| `02-home/home_feed-no-availability-empty_mobile.png` | Home | Home feed | `/home` | `/home` | Mobile — 390 × 664 CSS px viewport | No trips, friends, availability, or ideas | Current Home experience for the only development user, including profile summary, zero-state stats, empty ideas, and bottom navigation. |
| `03-trips/trips_availability-calendar-empty_mobile.png` | Trips | Availability | `/add-open-dates` | `/add-open-dates` | Mobile — 390 px wide, full page | No saved dates | Availability calendar before any dates are selected or saved. |
| `03-trips/trips_availability-calendar-range-selected_mobile.png` | Trips | Availability | `/add-open-dates` | `/add-open-dates` | Mobile — 390 px wide, full page | Date range selected; not saved | Availability calendar with a range selected entirely client-side; no dates were saved. |
| `03-trips/trips_friends-trips-empty_mobile.png` | Trips | Friends' Trips | `/my-trips` | `/my-trips` | Mobile — 390 px wide, full page | Friends' Trips tab — empty | Friends' Trips tab with no connected friends or trips. |
| `03-trips/trips_overlap-empty_mobile.png` | Trips | Availability overlap | `/overlap-detail` | `/overlap-detail` | Mobile — 390 px wide, full page | No friend overlap data | Overlap-detail experience with no connected friend availability. |
| `03-trips/trips_trip-creation-default_desktop.png` | Trips | Trip creation | `/add_trip` | `/add_trip` | Desktop — 1440 px wide, full page | Default form | Trip creation form at desktop width. |
| `03-trips/trips_trip-creation-default_mobile.png` | Trips | Trip creation | `/add_trip` | `/add_trip` | Mobile — 390 px wide, full page | Default form | Trip creation form before a mountain or date is selected. |
| `03-trips/trips_trip-creation-mountain-and-dates-selected_mobile.png` | Trips | Trip creation | `/add_trip` | `/add_trip` | Mobile — 390 px wide, full page | Vail and date range selected; not submitted | Trip creation with an existing mountain and future date range selected entirely client-side; no trip was saved. |
| `03-trips/trips_trip-creation-mountain-selected_mobile.png` | Trips | Trip creation | `/add_trip` | `/add_trip` | Mobile — 390 px wide, full page | Vail selected; dates not submitted | Trip creation form after selecting Vail from the existing mountain catalog; no trip was saved. |
| `03-trips/trips_trip-list-empty_desktop.png` | Trips | My Trips | `/my-trips` | `/my-trips` | Desktop — 1440 px wide, full page | My Trips tab — empty | Empty Trips experience at desktop width. |
| `03-trips/trips_trip-list-empty_mobile.png` | Trips | My Trips | `/my-trips` | `/my-trips` | Mobile — 390 px wide, full page | My Trips tab — empty | Trips tab with no upcoming trips or invitations. |
| `04-mountains/mountains_mountain-detail-vail_desktop.png` | Mountains | Mountain detail | `/mountain/vail-us` | `/mountain/vail-us` | Desktop — 1440 px wide, full page | No social activity; no pass match | Vail detail page at desktop width. |
| `04-mountains/mountains_mountain-detail-vail_mobile.png` | Mountains | Mountain detail | `/mountain/vail-us` | `/mountain/vail-us` | Mobile — 390 px wide, full page | No social activity; no pass match | Vail mountain detail for a user with no pass, trips, wishlist entry, or friends going. |
| `04-mountains/mountains_mountain-list-default_desktop.png` | Mountains | Mountain list | `/mountains` | `/mountains` | Desktop — 1440 × 1000 CSS px viewport | Default catalog | Mountain catalog in the initial desktop viewport. |
| `04-mountains/mountains_mountain-list-default_mobile.png` | Mountains | Mountain list | `/mountains` | `/mountains` | Mobile — 390 × 664 CSS px viewport | Default catalog | Searchable mountain catalog with country, state, and pass filters in the initial mobile viewport. |
| `04-mountains/mountains_mountain-list-no-results_mobile.png` | Mountains | Mountain list | `/mountains` | `/mountains` | Mobile — 390 × 664 CSS px viewport | Search with no matches | Mountain catalog empty state produced by a client-side no-match search. |
| `05-friends-social/friends_connect-self_mobile.png` | Friends and social | Connect | `/connect/1` | `/connect/1` | Mobile — 390 × 664 CSS px viewport | Own connect link | Safe connect-link state when the current user opens their own profile link. |
| `05-friends-social/friends_friends-list-empty_desktop.png` | Friends and social | Friends list | `/friends` | `/friends` | Desktop — 1440 px wide, full page | No friends | Empty Friends experience at desktop width. |
| `05-friends-social/friends_friends-list-empty_mobile.png` | Friends and social | Friends list | `/friends` | `/friends` | Mobile — 390 px wide, full page | No friends | Friends area with no connections or pending social activity. |
| `05-friends-social/invite_friend-share-link-and-qr_mobile.png` | Friends and social | Invite a friend | `/invite` | `/invite` | Mobile — 390 × 664 CSS px viewport | Share link and QR code | Authenticated friend-invite screen with copy-link and QR sharing options. |
| `06-profile-settings/notifications_notifications-empty_mobile.png` | Notifications | Notifications | `/notifications` | `/notifications` | Mobile — 390 px wide, full page | No notifications | Notifications inbox with no items. |
| `06-profile-settings/profile_delete-account-confirmation_mobile.png` | Profile and settings | Delete account confirmation | `/profile` | `/profile` | Mobile — 390 × 664 CSS px viewport | Confirmation modal open | Delete-account confirmation modal opened client-side; no text was entered and no deletion was attempted. |
| `06-profile-settings/profile_equipment-empty_mobile.png` | Profile and settings | Equipment | `/settings/equipment` | `/settings/equipment` | Mobile — 390 px wide, full page | No saved gear | Equipment settings with no gear setup saved. |
| `06-profile-settings/profile_mountains-visited-empty_mobile.png` | Profile and settings | Mountains visited | `/settings/mountains-visited` | `/mountains-visited` | Mobile — 390 px wide, full page | No visited mountains | Mountain-visit settings with no selections. |
| `06-profile-settings/profile_profile-edit_mobile.png` | Profile and settings | Edit profile | `/edit_profile` | `/edit_profile` | Mobile — 390 px wide, full page | Existing values | Editable rider identity, skill, and location form; no values were submitted. |
| `06-profile-settings/profile_profile-summary_desktop.png` | Profile and settings | Profile | `/profile` | `/profile` | Desktop — 1440 px wide, full page | Existing profile; no pass or gear | Profile hub at desktop width. |
| `06-profile-settings/profile_profile-summary_mobile.png` | Profile and settings | Profile | `/profile` | `/profile` | Mobile — 390 px wide, full page | Existing profile; no pass or gear | Profile hub for the current development user, including identity, stats, settings rows, and account actions. |
| `06-profile-settings/profile_ski-days-empty_mobile.png` | Profile and settings | Ski days | `/profile/ski-days` | `/profile/ski-days` | Mobile — 390 px wide, full page | No logged ski days | Ski-day history screen with no logged days. |
| `06-profile-settings/profile_wishlist-empty_mobile.png` | Profile and settings | Wishlist | `/settings/wish-list` | `/settings/wish-list` | Mobile — 390 px wide, full page | No wishlist mountains | Wishlist settings with no saved mountain wishes. |
| `06-profile-settings/settings_change-password_mobile.png` | Profile and settings | Change password | `/settings/password` | `/change-password` | Mobile — 390 px wide, full page | Default form | Password-change form; nothing was submitted. |
| `06-profile-settings/settings_push-notifications_mobile.png` | Profile and settings | Push notifications | `/push-settings` | `/push-settings` | Mobile — 390 px wide, full page | Current browser status | Push notification settings as rendered outside the native app shell. |
| `07-other-consumer-flows/invite_friend-link-invalid_mobile.png` | Invite and connect | Friend invite landing | `/invite/not-a-valid-invite-token` | `/invite/not-a-valid-invite-token` | Mobile — 390 × 664 CSS px viewport | Invalid invite link | Logged-out friend-invite landing state for an invalid link. |
| `07-other-consumer-flows/invite_trip-link-invalid_mobile.png` | Invite and connect | Trip invite landing | `/trip-invite/not-a-valid-trip-token` | `/trip-invite/not-a-valid-trip-token` | Mobile — 390 × 664 CSS px viewport | Invalid trip invite link | Logged-out trip-invite landing state for an invalid link. |
| `07-other-consumer-flows/legal_privacy-policy_mobile.png` | Legal | Privacy policy | `/privacypolicy` | `/privacypolicy` | Mobile — 390 px wide, full page | Current policy | Public privacy-policy page. |
| `07-other-consumer-flows/legal_terms-and-conditions_mobile.png` | Legal | Terms and conditions | `/termsandconditions` | `/termsandconditions` | Mobile — 390 px wide, full page | Current terms | Public terms-and-conditions page. |
| `07-other-consumer-flows/other_feedback-form_mobile.png` | Other consumer flows | Feedback | `/feedback` | `/feedback` | Mobile — 390 px wide, full page | Default form | Consumer feedback form; nothing was submitted. |

## Important screens or states not captured

- **Populated Home/feed:** unavailable because the development profile had no trips, friends, availability dates, or saved trip ideas.
- **Trip detail and trip planning:** unavailable because there were no existing trips. Creating a trip solely for screenshots would have changed development data.
- **Owner versus participant, public versus private, invitation status, and trip confirmation states:** unavailable because there were no trips, participants, or trip invitations.
- **Friend profile and social overlap states:** unavailable because there were no friend connections or friend availability records.
- **Valid trip-invite landing:** unavailable because no existing trip invite token was present. An invalid-link landing is included instead.
- **Standalone location setup:** the existing profile already had a home location, so that route redirected to Home. The location step was captured inside onboarding without submitting it.
- **Signup completion, password-reset success, saved edit confirmations, and other success states:** not captured because reaching them would require creating or changing data or sending email.
- **App download route:** the route redirected outside the BaseLodge product to an external distribution destination, so it was excluded from the BaseLodge UI library.
- **Distinct consumer 404 page:** unknown logged-out paths redirect to login, so there was no separate visual state to include.

## Route aliases visible in the export

- `/settings` redirects to the consolidated `/profile` hub; the Profile captures therefore document the main settings entry point.
- `/settings/mountains-visited` redirects to `/mountains-visited`.
- `/settings/password` redirects to `/change-password`.
- An invalid `/reset-password/<token>` request redirects to `/auth` with an error banner.

No design critique, recommendations, aesthetic evaluation, or redesign guidance is included in this export.
