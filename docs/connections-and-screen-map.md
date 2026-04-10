# BaseLodge Connections and Screen Map

## 1) Connection types in the app

### A. Friendship connections
These are the core social links between users.

- **Friend rows**
  - Stored in `Friend`
  - Directional records: `user_id -> friend_id`
  - The app commonly creates **bidirectional pairs** so both users can see each other
  - Used by `/friends`, `/friends/<id>`, `/profile/<id>`, overlap logic, and friend-based trip visibility

- **Trip invite permission on friendships**
  - `Friend.trip_invites_allowed`
  - Lets one friend invite another to trips
  - Used by trip-invite eligibility and friend trip flows

### B. Trip connections
These represent a user’s involvement with a trip.

- **Owner trip record**
  - `SkiTrip.user_id` = owner
  - This is the canonical trip ownership link

- **Trip participants**
  - Stored in `SkiTripParticipant`
  - Used for invited, accepted, and owner roles on shared ski trips
  - `status` values include `INVITED`, `ACCEPTED`, `DECLINED`
  - `role` values include `OWNER` and `GUEST`

- **Legacy trip invite record**
  - Stored in `Invitation`
  - Used for older invite flows and some trip invite routes
  - Carries sender, receiver, trip, invite type, and status

- **Group trip guests**
  - Stored in `TripGuest`
  - Used for `GroupTrip` only
  - Separate from `SkiTripParticipant`

### C. Invite-token connections
These support onboarding and friend connection flows.

- **Invite token**
  - Stored in `InviteToken`
  - Represents a reusable landing path for invite-based onboarding
  - The token landing route can connect a pending inviter to the new user

### D. Activity / signal connections
These are derived social signals rather than direct relationships.

- **Trip overlap activities**
  - Emitted when friends have overlapping trips
  - Uses either `resort_id` or legacy `mountain` matching

- **Availability overlap activities**
  - Emitted when friends share open dates

- **Trip invite activities**
  - Emitted for invite received / accepted / declined

- **Friend-join-trip activities**
  - Emitted when a friend joins a trip

---

## 2) Screen map: which screens connect to which

## Auth / onboarding

### `/` → landing or redirect
- Entry point
- Typically routes into auth or home depending on session

### `/auth`
- Login / sign-up entry screen
- Can lead to onboarding or home

### `/invite/<token>`
- Invite-token landing screen
- Connects to onboarding / account creation / inviter linking
- Can be the start of a new friendship connection

### `/setup-profile`
- Profile completion screen
- Leads onward to core app screens once profile is complete

### `/identity-setup`
- Identity/profile basics setup
- Part of onboarding chain

### `/location-setup`
- Location/home-state setup
- Also part of onboarding chain

---

## Core home / trip discovery

### `/home`
- Central dashboard
- Links into:
  - trip details
  - invited trips
  - friend trips
  - overlap signals
  - trip creation
  - profile setup prompts

### `/my-trips`
- User’s personal trip list
- Connects to `/trips/<id>` and edit routes

### `/trip-ideas`
- Trip suggestion / planning inspiration screen
- Can connect to trip creation and friend selection

### `/planning`
- Planning dashboard
- Links into trip windows, overlaps, and trip ideas

### `/planning/window/<start_date>/<end_date>`
- Planning window detail screen
- Connects to overlapping trip/friend suggestions

### `/overlap-detail`
- Detailed overlap view
- Connects users to social coordination around shared dates/resorts

---

## Trip screens

### `/create-trip`
- Trip creation UI
- Connects to add-trip and trip detail flows

### `/add_trip`
- Main trip creation/edit form
- Can create public trips and invite-enabled trips

### `/trips/<trip_id>`
- Main trip detail screen
- Connects to:
  - invite flow
  - participant settings
  - invite response
  - delete/edit
  - trip-sharing controls

### `/trips/<trip_id>/invite`
- Trip invite composition / send screen
- Connects to friend selection and invite submission

### `/trips/<trip_id>/respond`
- Invite response handler
- Used when invitee accepts/declines a trip invite

### `/trips/<trip_id>/edit`
- Edit trip screen

### `/trips/<trip_id>/delete`
- Delete trip action

### `/trips/<trip_id>/invite/cancel`
- Cancel sent invite action

### `/trips/requests/<request_id>/respond`
- Join-request response handler

### `/trips/requests/<request_id>/cancel`
- Cancel join request handler

### `/trips/<trip_id>/request-join`
- Request to join a trip

### `/friend-trip/<trip_id>`
- Friend trip detail view
- Used for viewing a friend’s public trip in a friend context

### `/trips/<trip_id>/invite` POST
- Sends invites to selected friends

### `/trips/<trip_id>/invite` GET
- Invite screen for a specific trip

---

## Friends / social screens

### `/friends`
- Main friends hub
- Links to:
  - friend profiles
  - friend trips
  - shared overlap signals
  - open-date overlap hints

### `/friends/<friend_id>`
- Friend detail page
- Shows friend-specific data, trips, and connection state

### `/friend_profile/<id>`
- Canonical friend profile screen
- Older route-style alias exists via legacy profile path

### `/profile/<user_id>`
- Public or semi-public user profile view
- Often used for social browsing

### `/profile`
- Logged-in user profile hub
- Links into settings and profile edit screens

### `/connect/<user_id>`
- Direct user-to-user connect screen
- Starts a connection flow

### `/connect/<user_id>/add` POST
- Finalizes the connection

### `/invite`
- Generic invite screen
- Used for generating/sharing invite access

### `/my-qr`
- QR code screen
- Connects to the invite-token flow

### `/invite/<user_id>`
- Invite a specific user directly

### `/connect-from-trip/<user_id>` POST
- Connect someone from a trip context

### `/api/friends/invite`
- API endpoint for sending friend invites

### `/api/friends/invite/<invitation_id>/accept`
- Accepts a friend invitation

### `/api/friends/<friend_id>`
- Friend profile data API

### `/api/friends/<friend_id>/set-trip-invites`
- Enables/disables trip invite permission for that friend

### `/api/friends/<friend_id>` DELETE
- Removes a friendship

---

## Profile / settings screens

### `/settings`
- Settings hub
- Connects to profile, equipment, password, wish-list, and mountain settings

### `/settings/profile`
- Edit profile screen

### `/settings/equipment`
- Gear setup screen

### `/settings/equipment/save`
- Saves gear setup

### `/settings/equipment/delete`
- Deletes gear setup

### `/settings/equipment-status`
- Updates equipment status

### `/settings/mountains-visited`
- Mountains visited screen

### `/settings/password`
- Password change screen

### `/settings/wish-list`
- Wish-list management screen

### `/settings/wish-list/save`
- Saves wish-list changes

### `/edit_profile`
- Legacy profile edit route

### `/change-password`
- Password change route

### `/add-open-dates`
- Open-date entry screen

### `/mountains-visited`
- Mountains visited editor

---

## Group trip screens

### `/group-trip/<trip_id>`
- Group trip view
- Displays host, guests, and coordination details

### `/group-trip/<trip_id>/invite`
- Invite guests to a group trip

### `/group-trip/<trip_id>/accept`
- Accept a group-trip invite

### `/group-trip/<trip_id>/leave`
- Leave group trip

### `/group-trip/<trip_id>/remove-guest/<guest_id>`
- Host removes a guest

### `/group-trip/<trip_id>/transportation`
- Update transportation status for a group trip

### `/api/group-trip/create`
- Creates a group trip

---

## Admin / maintenance screens

### `/admin/init-db`
- Initializes seed data
- Protected admin route

### `/admin/resorts`
- Resort admin hub

### `/admin/resorts/export-excel`
- Export resorts

### `/admin/resorts/import-excel`
- Import resorts

### `/admin/resorts/duplicates`
- Duplicate resort finder

### `/admin/backfill-*` routes
- Maintenance / migration helpers
- Mostly production hardening and data cleanup

### `/admin/sync-from-canonical`
- Canonical resort sync route

---

## 3) Canonical connection chains

### Friendship chain
`invite / connect / token` → user account created or linked → `Friend` rows created → `/friends` and `/friends/<id>` show the connection

### Trip invite chain
`/add_trip` or `/trips/<id>` → choose friend → invite action → `SkiTripParticipant` or `Invitation` record created → inviteee sees pending trip on `/home` and can respond from trip detail

### Group trip chain
`/group-trip/create` → group trip view → invite guests → guest accepts or leaves

### Overlap chain
User trip or open dates → friend trips or friend open dates → overlap signals → `/friends`, `/home`, and `/overlap-detail`

---

## 4) Important notes

- The app contains **both canonical and legacy routes** in several places.
- Friendships are usually **stored in both directions**.
- Trip visibility depends on `is_public` and participant state.
- Invite behavior is split across:
  - friend invites
  - trip invites
  - group-trip invites
  - invite tokens
- Some screens are mostly wrappers around API posts; the UI and the backend route together form the actual flow.

---

## 5) Suggested glossary

- **Connect**: create a friendship or relationship link
- **Friend**: a directional row in `Friend`, usually paired bidirectionally
- **Invite**: a pending request to join a trip or establish a connection
- **Participant**: a person linked to a ski trip via `SkiTripParticipant`
- **Guest**: a participant who is not the owner
- **Overlap**: shared date/location signal between users
- **Trip idea**: a suggested future trip based on preferences or social context
