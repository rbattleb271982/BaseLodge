# BaseLodge Email CRM Product Spec

## 1) What this system is

BaseLodge’s email CRM is a lightweight transactional email + lifecycle layer built around the app’s user graph and event stream. It is not a marketing automation suite in the broad sense; it mainly supports:

- account recovery
- invite-related lifecycle messaging
- feedback routing to admins
- future user lifecycle/email segmentation

It is connected to the app through:

- `User` lifecycle fields
- `Event` records
- `EmailLog` records
- `InviteToken` and friendship/session state
- SendGrid for outbound mail

---

## 2) Core product goals

1. Help users recover access safely.
2. Support invite-driven growth and friend connection flows.
3. Provide a foundation for lifecycle email analytics.
4. Keep email behavior quiet, explicit, and privacy-safe.
5. Avoid exposing whether an email exists in the system.

---

## 3) Main connection model

### A. Identity connection
- User enters email in auth or forgot-password.
- App looks up the user by normalized email.
- Email is used as the primary identity bridge.

### B. Social connection
- Invite-token landing pages can lead to account creation/login.
- After auth, the app can connect a new user to the inviter with bidirectional `Friend` rows.

### C. Recovery connection
- Forgot-password creates a signed reset token from the user.
- User receives a direct reset link by email.
- Token is validated on reset.

### D. CRM / lifecycle connection
- `Event` captures important lifecycle actions.
- `EmailLog` captures send history and suppression-style tracking.
- `User` stores email preference flags.

---

## 4) Data model involved

### `User`
Relevant email/lifecycle fields include:
- `email`
- `created_at`
- `last_active_at`
- `lifecycle_stage`
- `onboarding_completed_at`
- `profile_completed_at`
- `first_connection_at`
- `first_trip_created_at`
- `is_seeded`
- `email_opt_in`
- `email_transactional`
- `email_social`
- `email_digest`
- `timezone`

### `Event`
Used for high-signal app events.
- `event_name`
- `user_id`
- `payload`
- `created_at`
- `environment`

### `EmailLog`
Tracks email sends and related suppression history.
- `user_id`
- `email_type`
- `source_event_id`
- `sent_at`
- `send_count`
- `environment`

### `InviteToken`
Used for invite-based onboarding and friend linking.
- `token`
- `inviter_id`
- `created_at`
- `expires_at`
- `used_at`

### `Friend`
Used for social connection graph.
- bidirectional rows are usually created together

### `Invitation`
Legacy/parallel invite record for trip-related invites.

---

## 5) Email CRM route map

## Auth and recovery

### `/auth`
- Login/signup page
- Entry point for account creation and sign-in
- If `session["invite_token"]` exists, the user may be connected to the inviter after login/signup

### `/forgot-password` `GET, POST`
- Recovery request page
- User enters email address
- If a matching user exists, a reset token is generated and emailed
- Response always says a reset link will be sent, even if no account exists

### `/reset-password` `GET, POST`
### `/reset-password/<token>` `GET, POST`
- Token-based password reset page
- Validates the signed user token
- Lets the user set a new password
- Logs the user in after successful reset

---

## 6) Invite/email growth routes

### `/invite/<token>`
- Invite landing page for recipients
- Stores token in session
- Shows inviter name and upcoming trip count
- Sends the user into auth flow

### `/invite`
- Sender-side invite hub
- Contains copy-link and SMS invite actions

### `/my-qr`
- Generates or serves QR code for the invite URL

### `/connect/<int:user_id>`
- Direct user connection route

### `/connect/<int:user_id>/add` `POST`
- Finalizes a direct connection

### `/invite/<int:user_id>`
- Invite a specific user directly

### `/api/friends/invite` `POST`
- API-based friend invite send endpoint

### `/api/friends/invite/<int:invitation_id>/accept` `POST`
- Accepts a friend invite

### `/api/friends/<int:friend_id>/set-trip-invites` `POST`
- Controls whether a friend can send trip invites

---

## 7) How forgot-password works in detail

### Request flow
1. User visits `/forgot-password`.
2. User submits email.
3. App normalizes email to lowercase.
4. App looks up `User` by case-insensitive email match.
5. If user exists:
   - calls `user.get_reset_token()`
   - builds reset URL: `BASE_URL/reset-password/<token>`
   - sends email through SendGrid
6. Whether or not the user exists, the response message is the same.

### Email content
Subject:
- `Reset your BaseLodge password`

Body:
- `Please use the following link to reset your password: <reset_url>`
- `This link will expire in 30 minutes.`

### Security behavior
- The app does **not** reveal if the account exists.
- The reset route requires a valid token.
- Invalid or expired tokens redirect back to auth with an error.

---

## 8) Forgot-password UI copy

### `/forgot-password`
- Title: **Forgot Password**
- Body: **Enter your email address and we'll send you a link to reset your password.**
- Submit button: **Send Reset Link**
- Footer link: **Back to Log In**

### `/reset-password/<token>`
- Title: **Reset Password**
- Body: **Please enter your new password below.**
- Fields:
  - New Password
  - Confirm New Password
- Submit button: **Reset Password**

### Error states
- Invalid or expired token: **This reset link is invalid or has expired.**
- Empty password: **Password cannot be empty.**
- Short password: **Password must be at least 8 characters.**
- Mismatch: **Passwords do not match.**
- Success: **Your password has been reset.**

---

## 9) Invite landing UI copy

### `/invite/<token>`
- Title: **You’re invited to BaseLodge**
- OG description: **Plan ski trips with friends.**
- Body: **Wants to connect on BaseLodge to see when you're both heading to the mountains.**
- CTA primary: **Create account to connect**
- CTA secondary: **Already have an account? Log in**

### Expired state
- Title: **Invite expired**
- Body: **Ask your friend to send you a new one — it only takes a second.**
- CTA: **Go to Login**

---

## 10) Email/social relationship logic

### Invite-token auth bridge
- Inviter shares `/invite/<token>`.
- Recipient lands on invite page.
- Token is stored in session.
- After signup/login, `_connect_pending_inviter(user)` creates bidirectional `Friend` rows.
- Invite token is marked used.
- Session token is cleared.

### Legacy invite bridge
- If `session["pending_inviter_id"]` exists, the app can still create the friendship.

### Direct friend invite logic
- `Friend` rows are the canonical social graph.
- `Invitation` exists as a separate invite record for trip flows and legacy compatibility.

---

## 11) CRM / email operational behavior

### Outbound email provider
- **SendGrid** is used for password reset mail.
- Admin feedback emails also use SendGrid.

### Admin feedback email path
- `/feedback` can send admin email if `ADMIN_FEEDBACK_EMAIL` is configured.
- This is a support/ops channel, not a user CRM channel.

### Preference flags
The app has room for lifecycle/email segmentation through user fields:
- opt-in
- transactional
- social
- digest

Currently these fields exist as the data layer for future routing.

---

## 12) Recommended CRM flows

### Transactional
- password reset
- invite recovery / resend invite
- important account notices

### Social
- invite received
- friend connection established
- trip invite sent
- trip invite accepted/declined

### Lifecycle
- profile completion nudges
- onboarding completion
- first trip creation
- first connection creation

---

## 13) Key product rules

- Never reveal whether an email exists during forgot-password.
- Invite links should be single-use at the token level.
- Friend links should remain bidirectional.
- Reset links should be short-lived and tokenized.
- CRM emails should be driven by events and user state, not ad hoc messaging.

---

## 14) Summary

BaseLodge’s email CRM is a hybrid of:
- password recovery
- invite-driven acquisition
- friend-graph connectivity
- lifecycle instrumentation

The live user-facing email system is currently centered on SendGrid plus the app’s invite/reset flows.
