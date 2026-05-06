"""
test_push_lifecycle.py — APNs push token lifecycle tests.

Each test creates its own PushDeviceToken rows using a distinct fake token
value and cleans them up in tearDown. Tests do not rely on existing DB state.

Coverage:
  1. /admin/test-push returns no_active_tokens (HTTP 200) and does not call APNs
  2. /admin/list-tokens returns token diagnostics without sending APNs notifications
  3. /api/push/register-token refresh path reactivates an existing inactive token
  4. /api/push/register-token does not create duplicate rows for the same token
"""
import json
import unittest
import uuid

import app as app_module
from app import app
from models import db, PushDeviceToken

ADMIN_USER_ID = 2


def _fake_token():
    """64-char uppercase hex string — valid APNs token format for testing."""
    return (uuid.uuid4().hex + uuid.uuid4().hex).upper()


class PushTokenLifecycleTests(unittest.TestCase):

    def setUp(self):
        self._created_tokens = []

    def tearDown(self):
        with app.app_context():
            for tok in self._created_tokens:
                PushDeviceToken.query.filter_by(token=tok).delete()
            db.session.commit()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _insert_token(self, user_id, token, active, apns_env="production"):
        """Insert a test PushDeviceToken row and register it for teardown."""
        with app.app_context():
            row = PushDeviceToken(
                user_id=user_id,
                token=token,
                platform="ios",
                apns_environment=apns_env,
                active=active,
            )
            db.session.add(row)
            db.session.commit()
        self._created_tokens.append(token)

    def _admin_client(self):
        c = app.test_client()
        with c.session_transaction() as sess:
            sess["_user_id"] = str(ADMIN_USER_ID)
            sess["_fresh"] = True
        return c

    def _user_client(self, user_id):
        c = app.test_client()
        with c.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True
        return c

    def _deactivate_all(self, user_id):
        """Deactivate all iOS tokens for user; return list of IDs to restore."""
        with app.app_context():
            rows = PushDeviceToken.query.filter_by(
                user_id=user_id, platform="ios", active=True
            ).all()
            ids = [r.id for r in rows]
            for r in rows:
                r.active = False
            db.session.commit()
        return ids

    def _restore_active(self, ids):
        """Re-activate the rows previously deactivated by _deactivate_all."""
        if not ids:
            return
        with app.app_context():
            for row_id in ids:
                row = db.session.get(PushDeviceToken, row_id)
                if row:
                    row.active = True
            db.session.commit()

    # ── Test 1: no_active_tokens returns early without calling APNs ───────────

    def test_no_active_tokens_returns_early_without_apns_call(self):
        """test-push returns no_active_tokens (HTTP 200) and skips APNs."""
        tok = _fake_token()
        self._insert_token(ADMIN_USER_ID, tok, active=False)

        deactivated_ids = self._deactivate_all(ADMIN_USER_ID)
        apns_called = []
        orig_send = app_module.send_apns_push
        app_module.send_apns_push = lambda *a, **kw: apns_called.append(1) or {}

        try:
            c = self._admin_client()
            resp = c.get(f"/admin/test-push?user_id={ADMIN_USER_ID}")
            data = json.loads(resp.data)

            self.assertEqual(resp.status_code, 200, msg=resp.data)
            self.assertFalse(data.get("success"),
                             "success must be False when no active tokens")
            self.assertFalse(data.get("final_success"),
                             "final_success must be False when no active tokens")
            self.assertEqual(data.get("reason"), "no_active_tokens",
                             f"Expected reason=no_active_tokens, got: {data.get('reason')}")
            self.assertIn("error", data,
                          "Response must include an error message")
            self.assertIn("instruction", data,
                          "Response must include an instruction for the user")
            self.assertFalse(apns_called,
                             "send_apns_push must NOT be called when active=0")
            self.assertIn("token_counts", data,
                          "token_counts must be present in the response")
            self.assertEqual(data["token_counts"]["active"], 0,
                             "token_counts.active must be 0")
        finally:
            app_module.send_apns_push = orig_send
            self._restore_active(deactivated_ids)

    # ── Test 2: list-tokens returns diagnostics without sending ───────────────

    def test_list_tokens_returns_diagnostics_without_apns_call(self):
        """/admin/list-tokens returns token list and never calls APNs."""
        tok = _fake_token()
        self._insert_token(ADMIN_USER_ID, tok, active=True, apns_env="production")

        apns_called = []
        orig_send = app_module.send_apns_push
        app_module.send_apns_push = lambda *a, **kw: apns_called.append(1) or {}

        try:
            c = self._admin_client()
            resp = c.get(f"/admin/list-tokens?user_id={ADMIN_USER_ID}")
            data = json.loads(resp.data)

            self.assertEqual(resp.status_code, 200, msg=resp.data)
            self.assertTrue(data.get("success"),
                            "success must be True for list-tokens")
            self.assertIn("tokens", data,
                          "Response must contain a 'tokens' list")
            self.assertFalse(apns_called,
                             "list-tokens must never call send_apns_push")

            previews = [t["token_preview"] for t in data["tokens"]]
            full_tokens = [t.get("token") for t in data["tokens"]]

            self.assertTrue(
                all("…" in p for p in previews),
                "Every token_preview must contain the ellipsis character"
            )
            self.assertTrue(
                all(ft is None for ft in full_tokens),
                "Full token values must never be exposed in list-tokens response"
            )
            self.assertTrue(
                all(tok not in p for p in previews),
                "Full token string must not appear in any token_preview"
            )

            fields = {"id", "user_id", "platform", "active",
                      "apns_environment", "token_preview", "created_at", "updated_at"}
            for t in data["tokens"]:
                for field in fields:
                    self.assertIn(field, t,
                                  f"Token entry missing required field: {field}")
        finally:
            app_module.send_apns_push = orig_send

    # ── Test 3: refresh reactivates an inactive token ─────────────────────────

    def test_register_token_refresh_reactivates_inactive_token(self):
        """Refreshing an existing inactive token via register-token sets active=True."""
        tok = _fake_token()
        self._insert_token(ADMIN_USER_ID, tok, active=False, apns_env="production")

        c = self._user_client(ADMIN_USER_ID)
        resp = c.post(
            "/api/push/register-token",
            json={"token": tok, "platform": "ios", "apns_environment": "production"},
            content_type="application/json",
        )
        data = json.loads(resp.data)

        self.assertEqual(resp.status_code, 200, msg=resp.data)
        self.assertTrue(data.get("success"), "success must be True after refresh")
        self.assertEqual(data.get("action"), "refreshed",
                         f"Expected action=refreshed, got: {data.get('action')}")

        with app.app_context():
            row = PushDeviceToken.query.filter_by(
                user_id=ADMIN_USER_ID, token=tok
            ).first()
            self.assertIsNotNone(row, "Token row must exist in DB after refresh")
            self.assertTrue(row.active,
                            "Token must be active=True after refresh call")

    # ── Test 4: no duplicate rows for same (user_id, token) ──────────────────

    def test_register_token_no_duplicate_rows(self):
        """Registering the same token multiple times never creates duplicate rows."""
        tok = _fake_token()
        self._created_tokens.append(tok)

        c = self._user_client(ADMIN_USER_ID)
        for i in range(3):
            resp = c.post(
                "/api/push/register-token",
                json={"token": tok, "platform": "ios", "apns_environment": "production"},
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200,
                             f"Registration {i+1} failed: {resp.data}")

        with app.app_context():
            count = PushDeviceToken.query.filter_by(
                user_id=ADMIN_USER_ID, token=tok
            ).count()
            self.assertEqual(count, 1,
                             f"Expected exactly 1 row, found {count} — duplicate rows created")


if __name__ == "__main__":
    unittest.main(verbosity=2)
