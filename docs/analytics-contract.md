# BaseLodge analytics contract

BaseLodge is the source of truth. PostHog is a best-effort behavioral analytics
layer and must never block or determine product behavior.

## Identity

- Authenticated people use the decimal BaseLodge user ID as `distinct_id`.
- Browser anonymous IDs must pass the shared bounded anonymous-ID validation.
- Signup may alias a valid browser anonymous ID to the new user ID.
- Login must identify the existing user without creating another alias.
- Logout and account switches reset browser PostHog identity before another
  anonymous or authenticated session is tracked.
- No BaseLodge account is created solely for analytics.

## Events and properties

- Event and property names use `snake_case`.
- Existing production event names remain stable unless a separately reviewed
  compatibility transition is approved.
- Properties should be bounded booleans, counts, categorical values, stable
  catalog IDs, or other non-authoritative metadata.
- Authenticated identification includes the mutable boolean `is_internal`.
- Server and browser delivery wrappers remove prohibited property keys and
  obvious email-address values as defense in depth.

The current 21 production PostHog events are:

`app_loaded`, `auth_error`, `availability_added`,
`availability_share_cancelled`, `availability_share_failed`,
`availability_share_generated`, `availability_share_opened`,
`availability_share_started`, `availability_share_succeeded`,
`friend_connected`, `invite_generated`, `invite_share_intent`,
`login_completed`, `logout`, `onboarding_completed`,
`onboarding_step_completed`, `pass_added`, `signup_completed`,
`signup_started`, `trip_created`, and `wishlist_added`.

## Prohibited analytics data

Do not send email addresses, personal names, passwords, authentication/session
secrets, raw invitation or push tokens, private friend relationships, private
trip content, raw availability notes, residential addresses, or freeform user
content. BaseLodge application data remains authoritative and more detailed.

## Session replay

Session replay is fail-closed and disabled in `static/analytics.js`. A runtime
environment variable alone is not approval to enable it.

Enabling replay requires a separate privacy review and code change that proves:

- Authentication, Profile, Trips, Friends, and Admin routes are excluded.
- Inputs, text, images, and freeform content are masked or blocked by default.
- Sensitive modal, invitation, availability, and trip-planning content cannot
  enter replay payloads.
- Production remains disabled until that reviewed policy and its tests ship.

## Delivery and failure behavior

- Normal requests call PostHog capture/identify without `flush()`.
- The PostHog client uses its normal background batching.
- Gunicorn workers discard any client inherited after fork and perform one
  best-effort shutdown at orderly worker exit.
- Process `atexit` is a fallback for non-Gunicorn processes.
- Initialization, capture, identify, alias, reset, and shutdown failures must
  not change the underlying BaseLodge response or product state.