    )

    if not candidate_rows:
        current_app.logger.warning(
            "[TestPush] target_user_id=%d no active iOS %s tokens found — nothing to send",
            target_user_id, target_env,
        )
        total_token_count = PushDeviceToken.query.filter_by(user_id=target_user_id).count()
        return jsonify({
            "success":       False,
            "final_success": False,
            "provider":      "apns",
            "platform":      "ios",
            "total_tokens_found":     0,
            "total_sent_successfully": 0,
            "total_failed":           0,
            "apns_env":      apns_env_info,
            "reason":        "no_active_tokens",
            "error":         f"No active iOS {target_env} token found for user {target_user_id}.",
            "instruction":   "Ask the user to open the BaseLodge app so their device registers a token.",
            "token_counts":  {"total": total_token_count, "active": 0},
            "target_user_id": target_user_id,
            "results_by_token": [],
        }), 200

    def _prefer_sandbox(row):
        if row.apns_environment == "sandbox":
            return True
        if row.apns_environment == "production":
            return False
        return None

    results_by_token = []
    total_ok  = 0
    total_bad = 0

    for row in candidate_rows:
        preview = _tok_preview(row.token)
        current_app.logger.warning(
            "[TestPush] sending → provider=apns token_id=%d user_id=%d env=%s token=%s",
            row.id, row.user_id, row.apns_environment, preview,
        )

        result = send_apns_push(
            row.token,
            title="BaseLodge",
            body="Test push from BaseLodge",
            prefer_sandbox=_prefer_sandbox(row),
        )

        final_success = result.get("final_success", result.get("success", False))

        if result.get("retry_attempted"):
            status_code = result.get("retry_status_code")
            error       = result.get("retry_error")
            apns_id     = result.get("retry_apns_id")
            env_used    = result.get("retry_environment")
        else:
            status_code = result.get("first_attempt_status_code")
            error       = result.get("first_attempt_error")
            apns_id     = result.get("first_attempt_apns_id")
            env_used    = result.get("first_attempt_environment")

        if final_success:
            total_ok += 1
            current_app.logger.warning(
                "[APNs TEST] token_id=%d user_id=%d status=success environment=%s response_status=%s",
                row.id, row.user_id, env_used, status_code,
            )
        else:
            total_bad += 1
            current_app.logger.warning(
                "[APNs TEST] token_id=%d user_id=%d status=failed environment=%s response_status=%s reason=%s",
                row.id, row.user_id, env_used, status_code, error or "unknown",
            )

        results_by_token.append({
            "user_id":          row.user_id,
            "token_id":         row.id,
            "token_preview":    preview,
            "platform":         "ios",
            "apns_environment": row.apns_environment,
            "success":          final_success,
            "status_code":      status_code,
            "error":            error,
            "apns_id":          apns_id,
            "env_corrected":    result.get("env_corrected", False),
        })

        # ── MessageEventLog: APNs test push outcome ──
        try:
            create_message_event(
                event_name=EventName.PUSH_TEST_SENT,
                category=Category.SYSTEM,
                actor_user_id=current_user.id,
                recipient_user_id=row.user_id,
                channel=Channel.PUSH,
                provider=Provider.APNS,
                payload_json={
                    "token_id": row.id,
                    "platform": "ios",
                    "source_route": "admin_test_push",
                },
                message_title="BaseLodge",
                message_body="Test push from BaseLodge",
                delivery_status=DeliveryStatus.SENT if final_success else DeliveryStatus.FAILED,
                error_message=error if not final_success else None,
            )
        except Exception as _mel_err:
            current_app.logger.warning("[MessageEvent] test_push (apns) log failed token_id=%d: %s", row.id, _mel_err)

    current_app.logger.warning(
        "[TestPush] done — provider=apns total=%d ok=%d failed=%d",
        len(candidate_rows), total_ok, total_bad,
    )

    overall_http = 200 if total_ok > 0 else 502
    return jsonify({
        "provider":               "apns",
        "platform":               "ios",
        "total_tokens_found":     len(candidate_rows),
        "total_sent_successfully": total_ok,
        "total_failed":           total_bad,
        "apns_env":               apns_env_info,
        "results_by_token":       results_by_token,
    }), overall_http


@app.route("/admin/test-push-all", methods=["GET"])
@login_required
@admin_required
def admin_test_push_all():
    """Send a test push to every active token belonging to the current admin user.

    Loops over all active PushDeviceToken rows for current_user, routing each
    through the correct provider:
      - platform='ios'     → APNs  (send_apns_push)
      - platform='android' → FCM   (send_fcm_push)
      - anything else      → skipped, counted as unsupported

    Title: BaseLodge
    Body:  Test push from BaseLodge

    Never logs full tokens or secrets.
    """
    def _tok_preview(t):
        return t[:8] + "\u2026" + t[-6:] if len(t) > 14 else t[:8] + "\u2026"

    # ── QA Override: send to Richard's tokens instead of current admin's ────────
    _qa_user_all = _get_qa_push_override_user()
    _push_all_user_id = _qa_user_all.id if _qa_user_all else current_user.id

    active_tokens = (
        PushDeviceToken.query
        .filter_by(user_id=_push_all_user_id, active=True)
        .order_by(PushDeviceToken.updated_at.desc())
        .all()
    )

    if _qa_user_all:
        current_app.logger.warning(
            "[TestPushAll] QA Override Active — routed test push to Richard "
            "(original user_id=%d → qa_user_id=%d email=%s active_tokens=%d)",
            current_user.id, _qa_user_all.id, _QA_PUSH_OVERRIDE_EMAIL, len(active_tokens),
        )
    else:
        current_app.logger.warning(
            "[TestPushAll] user_id=%d active_tokens=%d",
            current_user.id, len(active_tokens),
        )

    if not active_tokens:
        return jsonify({
            "route":                  "/admin/test-push-all",
            "user_id":                current_user.id,
            "total_active_tokens":    0,
            "ios_attempted":          0,
            "android_attempted":      0,
            "total_success":          0,
            "total_failed":           0,
            "unsupported_platforms":  0,
            "reason":                 "no_active_tokens",
            "results":                [],
        }), 200

    results        = []
    ios_count      = 0
    android_count  = 0
    success_count  = 0
    failed_count   = 0
    unsupported    = 0

    TEST_TITLE = "BaseLodge"
    TEST_BODY  = "Test push from BaseLodge"
    TEST_DATA  = {"source": "admin_test_push_all"}

    for row in active_tokens:
        preview = _tok_preview(row.token)

        if row.platform == "ios":
            ios_count += 1
            # Derive prefer_sandbox from stored apns_environment
            if row.apns_environment == "sandbox":
                prefer_sandbox = True
            elif row.apns_environment == "production":
                prefer_sandbox = False
            else:
                prefer_sandbox = None  # fall back to APNS_USE_SANDBOX env var

            current_app.logger.warning(
                "[TestPushAll] provider=apns platform=ios token_id=%d user_id=%d token=%s",
                row.id, row.user_id, preview,
            )
            result = send_apns_push(
                row.token,
                title=TEST_TITLE,
                body=TEST_BODY,
                prefer_sandbox=prefer_sandbox,
            )
            final_success = result.get("final_success", result.get("success", False))
            if result.get("retry_attempted"):
                error = result.get("retry_error")
            else:
                error = result.get("first_attempt_error")

            if final_success:
                success_count += 1
            else:
                failed_count += 1

            results.append({
                "token_id":         row.id,
                "platform":         "ios",
                "provider":         "apns",
                "token_preview":    preview,
                "apns_environment": row.apns_environment,
                "success":          final_success,
                "error":            error,
            })

            # ── MessageEventLog: APNs push-all outcome ──
            try:
                create_message_event(
                    event_name=EventName.PUSH_TEST_SENT,
                    category=Category.SYSTEM,
                    actor_user_id=current_user.id,
                    recipient_user_id=row.user_id,
                    channel=Channel.PUSH,
                    provider=Provider.APNS,
                    payload_json={
                        "token_id": row.id,
                        "platform": "ios",
                        "source_route": "admin_test_push_all",
                    },
                    message_title=TEST_TITLE,
                    message_body=TEST_BODY,
                    delivery_status=DeliveryStatus.SENT if final_success else DeliveryStatus.FAILED,
                    error_message=error if not final_success else None,
                )
            except Exception as _mel_err:
                current_app.logger.warning("[MessageEvent] test_push_all (ios) log failed token_id=%d: %s", row.id, _mel_err)

        elif row.platform == "android":
            android_count += 1
            current_app.logger.warning(
                "[TestPushAll] provider=fcm platform=android token_id=%d user_id=%d token=%s",
                row.id, row.user_id, preview,
            )
            result = send_fcm_push(
                row.token,
                title=TEST_TITLE,
                body=TEST_BODY,
                data=TEST_DATA,
            )
            success = result.get("success", False)
            if success:
                success_count += 1
            else:
                failed_count += 1

            results.append({
                "token_id":      row.id,
                "platform":      "android",
                "provider":      "fcm",
                "token_preview": preview,
                "success":       success,
                "message_id":    result.get("message_id"),
                "error":         result.get("error"),
            })

            # ── MessageEventLog: FCM push-all outcome ──
            try:
                create_message_event(
                    event_name=EventName.PUSH_TEST_SENT,
                    category=Category.SYSTEM,
                    actor_user_id=current_user.id,
                    recipient_user_id=row.user_id,
                    channel=Channel.PUSH,
                    provider=Provider.FCM,
                    payload_json={
                        "token_id": row.id,
                        "platform": "android",
                        "source_route": "admin_test_push_all",
                    },
                    message_title=TEST_TITLE,
                    message_body=TEST_BODY,
                    delivery_status=DeliveryStatus.SENT if success else DeliveryStatus.FAILED,
                    error_message=result.get("error") if not success else None,
                )
            except Exception as _mel_err:
                current_app.logger.warning("[MessageEvent] test_push_all (android) log failed token_id=%d: %s", row.id, _mel_err)

        else:
            unsupported += 1
            current_app.logger.warning(
                "[TestPushAll] unsupported platform=%s token_id=%d user_id=%d — skipped",
                row.platform, row.id, row.user_id,
            )
            results.append({
                "token_id":      row.id,
                "platform":      row.platform,
                "provider":      "none",
                "token_preview": preview,
                "success":       False,
                "error":         "unsupported_platform",
            })

    current_app.logger.warning(
        "[TestPushAll] done user_id=%d total=%d ios=%d android=%d success=%d failed=%d unsupported=%d",
        current_user.id, len(active_tokens),
        ios_count, android_count,
        success_count, failed_count, unsupported,
    )

    overall_http = 200 if (success_count > 0 or (ios_count + android_count == 0)) else 502
    return jsonify({
        "route":                 "/admin/test-push-all",
        "user_id":               current_user.id,
        "total_active_tokens":   len(active_tokens),
        "ios_attempted":         ios_count,
        "android_attempted":     android_count,
        "total_success":         success_count,
        "total_failed":          failed_count,
        "unsupported_platforms": unsupported,
        "results":               results,
    }), overall_http


@app.route("/admin/posthog-test", methods=["GET"])
@login_required
@admin_required
def admin_posthog_test():
    """Diagnostic: fire one posthog_server_test event and return capture/flush results."""
    import time as _time
    results = {}

    key = ph_analytics.POSTHOG_KEY
    host = ph_analytics.POSTHOG_HOST
    results["key_set"] = bool(key)
    results["key_prefix"] = (key[:8] + "…") if key else None
    results["host"] = host

    if not key:
        results["outcome"] = "FAIL — POSTHOG_KEY not set"
        return jsonify(results), 200

    try:
        from posthog import Posthog
        _test_client = Posthog(project_api_key=key, host=host)
        results["client_init"] = "OK"
    except Exception as exc:
        results["client_init"] = "FAIL"
        results["client_init_error"] = str(exc)
        results["outcome"] = "FAIL — client init error"
        return jsonify(results), 200

    distinct_id = str(current_user.id)
    event = "posthog_server_test"
    props = {
        "source": "admin_posthog_test",
        "user_id": current_user.id,
        "timestamp": _time.time(),
    }

    try:
        _test_client.capture(event, distinct_id=distinct_id, properties=props)
        results["capture"] = "OK"
    except Exception as exc:
        results["capture"] = "FAIL"
        results["capture_error"] = str(exc)
        results["outcome"] = "FAIL — capture error"
        return jsonify(results), 200

    try:
        _test_client.flush()
        results["flush"] = "OK"
        results["outcome"] = "SUCCESS"
    except Exception as exc:
        results["flush"] = "FAIL"
        results["flush_error"] = str(exc)
        results["outcome"] = "FAIL — flush error"

    app.logger.info("[POSTHOG_DIAG] %s", results)
    return jsonify(results), 200


@app.route("/admin/backfill-posthog", methods=["GET"])
@login_required
@admin_required
def admin_backfill_posthog():
    """Backfill PostHog person properties for all users.

    Uses client.set() only — never capture(). No events, no timeline impact.
    Idempotent: safe to run multiple times.

    Query params:
      ?dry_run=1   Build property dicts and return them without sending anything.
    """
    dry_run = request.args.get("dry_run", "0") == "1"

    # ── 1. Bulk-fetch supporting data (no N+1 inside the user loop) ──────────

    # Sets of user_ids for boolean flags
    trip_owner_ids = {
        r[0] for r in db.session.execute(
            db.text("SELECT DISTINCT user_id FROM ski_trip")
        )
    }
    trip_guest_ids = {
        r[0] for r in db.session.execute(
            db.text("SELECT DISTINCT user_id FROM ski_trip_participant WHERE status IN ('interested', 'going')")
        )
    }
    friend_ids = {
        r[0] for r in db.session.execute(
            db.text("SELECT DISTINCT user_id FROM friend")
        )
    }
    generic_invite_ids = {
        r[0] for r in db.session.execute(
            db.text("SELECT DISTINCT inviter_id FROM invite_token")
        )
    }
    trip_invite_ids = {
        r[0] for r in db.session.execute(
            db.text("SELECT DISTINCT inviter_user_id FROM trip_invite_token")
        )
    }

    # Integer counts per user
    friend_counts = {
        r[0]: r[1] for r in db.session.execute(
            db.text("SELECT user_id, COUNT(*) FROM friend GROUP BY user_id")
        )
    }
    trip_counts = {
        r[0]: r[1] for r in db.session.execute(
            db.text("SELECT user_id, COUNT(*) FROM ski_trip GROUP BY user_id")
        )
    }

    all_users = User.query.order_by(User.id).all()

    backfill_date = datetime.utcnow().strftime("%Y-%m-%d")

    # ── 2. Build one property dict per user ──────────────────────────────────

    user_props = []
    for u in all_users:
        uid = u.id
        wl = u.wish_list_resorts or []
        rt = u.rider_types
        if isinstance(rt, list):
            rider_label = ",".join(rt) if rt else "unknown"
        else:
            rider_label = str(rt) if rt else "unknown"

        props = {
            # Activation flags
            "has_completed_signup":     True,
            "has_completed_onboarding": u.lifecycle_stage == "active",
            "has_pass":                 _ph_is_real_pass(u.pass_type),
            "has_availability":         bool(u.open_dates),
            "has_wishlist":             bool(wl),
            "has_trip":                 (uid in trip_owner_ids or uid in trip_guest_ids),
            "has_friend_connection":    uid in friend_ids,
            "has_generated_invite":     (uid in generic_invite_ids or uid in trip_invite_ids),
            # Segmentation helpers (non-PII)
            "lifecycle_stage":          u.lifecycle_stage or "new",
            "pass_type":                (u.pass_type or "none").lower(),
            "rider_type":               rider_label,
            "friend_count":             friend_counts.get(uid, 0),
            "trip_count":               trip_counts.get(uid, 0),
            "wishlist_count":           len(wl),
            "is_internal":              ph_analytics.is_internal(u.email or ""),
            # Backfill sentinel
            "activation_backfilled":    True,
            "activation_backfilled_at": backfill_date,
        }
        user_props.append((uid, props))

    summary = {
        "total_users":  len(user_props),
        "dry_run":      dry_run,
        "sent":         False,
        "flush_ok":     None,
        "flush_error":  None,
        "errors":       [],
        "sample":       [{"user_id": uid, "props": p} for uid, p in user_props[:3]],
    }

    if dry_run:
        app.logger.info("[POSTHOG_BACKFILL] dry_run — %d users, no data sent", len(user_props))
        return jsonify(summary), 200

    # ── 3. Send: one client.set() per user, one flush at the end ─────────────

    client = ph_analytics._get_client()
    if not client:
        summary["errors"].append("PostHog client unavailable — POSTHOG_KEY not set")
        return jsonify(summary), 200

    set_errors = []
    for uid, props in user_props:
        try:
            client.set(distinct_id=str(uid), properties=props)
        except Exception as exc:
            set_errors.append({"user_id": uid, "error": str(exc)})
            app.logger.warning("[POSTHOG_BACKFILL] set failed user_id=%s error=%s", uid, exc)

    try:
        client.flush()
        summary["flush_ok"] = True
        summary["sent"] = True
        app.logger.info(
            "[POSTHOG_BACKFILL] complete — %d users sent, %d errors, flush OK",
            len(user_props), len(set_errors),
        )
    except Exception as exc:
        summary["flush_ok"] = False
        summary["flush_error"] = str(exc)
        app.logger.warning("[POSTHOG_BACKFILL] flush FAILED: %s", exc)

    summary["errors"] = set_errors
    return jsonify(summary), 200


@app.route("/admin/test-push-broadcast", methods=["GET"])
@login_required
@admin_required
def admin_test_push_broadcast():
    """Send a test push to every active token in the database across all users.

    Optional query params:
      ?title=...   override notification title  (default: "BaseLodge")
      ?body=...    override notification body   (default: "Test push from BaseLodge")

    Routes each token through the correct provider:
      platform='ios'     → APNs  (send_apns_push)
      platform='android' → FCM   (send_fcm_push)
      anything else      → skipped, counted as unsupported

    Never logs full tokens or secrets.
    """
    def _tok_preview(t):
        return t[:8] + "\u2026" + t[-6:] if len(t) > 14 else t[:8] + "\u2026"

    title = (request.args.get("title") or "BaseLodge").strip()
    body  = (request.args.get("body")  or "Test push from BaseLodge").strip()

    active_tokens = (
        PushDeviceToken.query
        .filter_by(active=True)
        .order_by(PushDeviceToken.updated_at.desc())
        .all()
    )

    # ── QA Override: narrow broadcast to Richard's tokens only ────────────────
    _qa_user_bc = _get_qa_push_override_user()
    if _qa_user_bc:
        _bc_before = len(active_tokens)
        active_tokens = [t for t in active_tokens if t.user_id == _qa_user_bc.id]
        current_app.logger.warning(
            "[TestPushBroadcast] QA Override Active — routed test push to Richard "
            "(qa_user_id=%d email=%s tokens_before=%d tokens_after=%d)",
            _qa_user_bc.id, _QA_PUSH_OVERRIDE_EMAIL, _bc_before, len(active_tokens),
        )

    unique_users = len({row.user_id for row in active_tokens})

    current_app.logger.warning(
        "[TestPushBroadcast] admin_user_id=%d total_active_tokens=%d unique_users=%d "
        "title=%r body=%r",
        current_user.id, len(active_tokens), unique_users, title[:60], body[:120],
    )

    if not active_tokens:
        return jsonify({
            "route":                 "/admin/test-push-broadcast",
            "admin_user_id":         current_user.id,
            "title_used":            title,
            "body_used":             body,
            "total_active_tokens":   0,
            "unique_users_targeted": 0,
            "ios_attempted":         0,
            "android_attempted":     0,
            "total_success":         0,
            "total_failed":          0,
            "unsupported_platforms": 0,
            "reason":                "no_active_tokens",
            "results":               [],
        }), 200

    results       = []
    ios_count     = 0
    android_count = 0
    success_count = 0
    failed_count  = 0
    unsupported   = 0

    TEST_DATA = {"source": "admin_test_push_broadcast"}

    for row in active_tokens:
        preview = _tok_preview(row.token)

        if row.platform == "ios":
            ios_count += 1
            if row.apns_environment == "sandbox":
                prefer_sandbox = True
            elif row.apns_environment == "production":
                prefer_sandbox = False
            else:
                prefer_sandbox = None

            current_app.logger.warning(
                "[TestPushBroadcast] provider=apns platform=ios "
                "token_id=%d user_id=%d token=%s",
                row.id, row.user_id, preview,
            )
            result       = send_apns_push(row.token, title=title, body=body,
                                          prefer_sandbox=prefer_sandbox)
            final_success = result.get("final_success", result.get("success", False))
            error         = (result.get("retry_error") if result.get("retry_attempted")
                             else result.get("first_attempt_error"))
            if final_success:
                success_count += 1
            else:
                failed_count += 1
            results.append({
                "token_id":         row.id,
                "user_id":          row.user_id,
                "platform":         "ios",
                "provider":         "apns",
                "token_preview":    preview,
                "apns_environment": row.apns_environment,
                "success":          final_success,
                "error":            error,
            })

            # ── MessageEventLog: APNs broadcast outcome ──
            try:
                create_message_event(
                    event_name=EventName.PUSH_BROADCAST_SENT,
                    category=Category.SYSTEM,
                    actor_user_id=current_user.id,
                    recipient_user_id=row.user_id,
                    channel=Channel.PUSH,
                    provider=Provider.APNS,
                    payload_json={
                        "token_id": row.id,
                        "platform": "ios",
                        "source_route": "admin_test_push_broadcast",
                    },
                    message_title=title,
                    message_body=body,
                    delivery_status=DeliveryStatus.SENT if final_success else DeliveryStatus.FAILED,
                    error_message=error if not final_success else None,
                )
            except Exception as _mel_err:
                current_app.logger.warning("[MessageEvent] push_broadcast (ios) log failed token_id=%d: %s", row.id, _mel_err)

        elif row.platform == "android":
            android_count += 1
            current_app.logger.warning(
                "[TestPushBroadcast] provider=fcm platform=android "
                "token_id=%d user_id=%d token=%s",
                row.id, row.user_id, preview,
            )
            result  = send_fcm_push(row.token, title=title, body=body, data=TEST_DATA)
            success = result.get("success", False)
            if success:
                success_count += 1
            else:
                failed_count += 1
            results.append({
                "token_id":      row.id,
                "user_id":       row.user_id,
                "platform":      "android",
                "provider":      "fcm",
                "token_preview": preview,
                "success":       success,
                "message_id":    result.get("message_id"),
                "error":         result.get("error"),
            })

            # ── MessageEventLog: FCM broadcast outcome ──
            try:
                create_message_event(
                    event_name=EventName.PUSH_BROADCAST_SENT,
                    category=Category.SYSTEM,
                    actor_user_id=current_user.id,
                    recipient_user_id=row.user_id,
                    channel=Channel.PUSH,
                    provider=Provider.FCM,
                    payload_json={
                        "token_id": row.id,
                        "platform": "android",
                        "source_route": "admin_test_push_broadcast",
                    },
                    message_title=title,
                    message_body=body,
                    delivery_status=DeliveryStatus.SENT if success else DeliveryStatus.FAILED,
                    error_message=result.get("error") if not success else None,
                )
            except Exception as _mel_err:
                current_app.logger.warning("[MessageEvent] push_broadcast (android) log failed token_id=%d: %s", row.id, _mel_err)

        else:
            unsupported += 1
            current_app.logger.warning(
                "[TestPushBroadcast] unsupported platform=%s token_id=%d user_id=%d — skipped",
                row.platform, row.id, row.user_id,
            )
            results.append({
                "token_id":      row.id,
                "user_id":       row.user_id,
                "platform":      row.platform,
                "provider":      "none",
                "token_preview": preview,
                "success":       False,
                "error":         "unsupported_platform",
            })

    current_app.logger.warning(
        "[TestPushBroadcast] done admin_user_id=%d total=%d ios=%d android=%d "
        "success=%d failed=%d unsupported=%d",
        current_user.id, len(active_tokens),
        ios_count, android_count,
        success_count, failed_count, unsupported,
    )

    overall_http = 200 if (success_count > 0 or (ios_count + android_count == 0)) else 502
    return jsonify({
        "route":                 "/admin/test-push-broadcast",
        "admin_user_id":         current_user.id,
        "title_used":            title,
        "body_used":             body,
        "total_active_tokens":   len(active_tokens),
        "unique_users_targeted": unique_users,
        "ios_attempted":         ios_count,
        "android_attempted":     android_count,
        "total_success":         success_count,
        "total_failed":          failed_count,
        "unsupported_platforms": unsupported,
        "results":               results,
    }), overall_http


@app.route("/admin/list-tokens", methods=["GET"])
@login_required
@admin_required
def admin_list_tokens():
    """Admin read-only diagnostic: list all push device tokens for a user.

    Never sends APNs notifications. Safe to call at any time.

    GET /admin/list-tokens
    GET /admin/list-tokens?user_id=6
    """
    try:
        target_user_id = int(request.args.get("user_id", 2))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "user_id must be an integer"}), 400

    def _tok_preview(t):
        return t[:8] + "…" + t[-6:] if len(t) > 14 else t[:8] + "…"

    rows = (
        PushDeviceToken.query
        .filter_by(user_id=target_user_id)
        .order_by(PushDeviceToken.updated_at.desc())
        .all()
    )

    active_count   = sum(1 for r in rows if r.active)
    inactive_count = len(rows) - active_count

    return jsonify({
        "success": True,
        "target_user_id": target_user_id,
        "token_counts": {
            "total": len(rows),
            "active": active_count,
            "inactive": inactive_count,
        },
        "tokens": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "platform": r.platform,
                "active": r.active,
                "apns_environment": r.apns_environment,
                "token_preview": _tok_preview(r.token),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
    }), 200


@app.route("/admin/push-token-dedup", methods=["GET"])
@login_required
@admin_required
def admin_push_token_dedup():
    """One-time admin cleanup: deactivate all but the most-recently-updated
    active PushDeviceToken per user/platform pair.

    Safe to run repeatedly — idempotent after first clean run.
    Never deletes rows. Never calls OneSignal or any push provider.

    GET /admin/push-token-dedup
    """
    # Gather all active tokens, grouped by (user_id, platform)
    all_active = (
        PushDeviceToken.query
        .filter_by(active=True)
        .order_by(PushDeviceToken.user_id, PushDeviceToken.platform,
                  PushDeviceToken.updated_at.desc())
        .all()
    )

    # Group by (user_id, platform) — first row in each group is the keeper
    from collections import defaultdict
    groups = defaultdict(list)
    for row in all_active:
        groups[(row.user_id, row.platform)].append(row)

    users_affected    = 0
    tokens_deactivated = 0
    details            = []

    try:
        for (uid, plat), rows in groups.items():
            if len(rows) <= 1:
                continue
            keeper     = rows[0]   # most recently updated active token
            to_deactivate = rows[1:]
            deactivated_ids = []
            for row in to_deactivate:
                row.active = False
                deactivated_ids.append(row.id)
                current_app.logger.warning(
                    "[PushTokenDedup] Deactivated stale token id=%s user=%s platform=%s",
                    row.id, uid, plat,
                )
            users_affected    += 1
            tokens_deactivated += len(deactivated_ids)
            details.append({
                "user_id":             uid,
                "platform":            plat,
                "kept_token_id":       keeper.id,
                "deactivated_token_ids": deactivated_ids,
            })

        db.session.commit()
        current_app.logger.warning(
            "[PushTokenDedup] complete — users_affected=%d tokens_deactivated=%d",
            users_affected, tokens_deactivated,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("[PushTokenDedup] failed — rolled back")
        return jsonify({"success": False, "error": "Server error during dedup"}), 500

    return jsonify({
        "success":           True,
        "users_affected":    users_affected,
        "tokens_deactivated": tokens_deactivated,
        "details":           details,
    }), 200


@app.route("/admin/push-token-audit", methods=["GET"])
@login_required
@admin_required
def admin_push_token_audit():
    """Audit active PushDeviceToken counts per user/platform.

    Flags any user/platform pair with more than 1 active token.
    Read-only — no writes, no push sends.

    GET /admin/push-token-audit
    GET /admin/push-token-audit?user_id=2   (filter to one user)
    """
    try:
        target_user_id = request.args.get("user_id")
        if target_user_id is not None:
            target_user_id = int(target_user_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "user_id must be an integer"}), 400

    query = PushDeviceToken.query.filter_by(active=True)
    if target_user_id is not None:
        query = query.filter_by(user_id=target_user_id)
    active_rows = query.order_by(
        PushDeviceToken.user_id, PushDeviceToken.platform,
        PushDeviceToken.updated_at.desc()
    ).all()

    from collections import defaultdict
    groups = defaultdict(list)
    for row in active_rows:
        groups[(row.user_id, row.platform)].append(row)

    audit_rows  = []
    total_clean = 0
    total_dirty = 0

    def _tok_preview(t):
        return t[:8] + "\u2026" + t[-6:] if len(t) > 14 else t[:8] + "\u2026"

    for (uid, plat), rows in sorted(groups.items()):
        count  = len(rows)
        status = "OK" if count == 1 else "DUPLICATE_ACTIVE_TOKENS"
        if count == 1:
            total_clean += 1
        else:
            total_dirty += 1
        audit_rows.append({
            "user_id":      uid,
            "platform":     plat,
            "active_count": count,
            "status":       status,
            "tokens": [
                {
                    "id":               r.id,
                    "token_preview":    _tok_preview(r.token),
                    "apns_environment": r.apns_environment,
                    "updated_at":       r.updated_at.isoformat() if r.updated_at else None,
                    "created_at":       r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        })

    # Sort: dirty (DUPLICATE) first, then by user_id
    audit_rows.sort(key=lambda x: (0 if x["status"] == "DUPLICATE_ACTIVE_TOKENS" else 1, x["user_id"]))

    return jsonify({
        "success":            True,
        "filter_user_id":     target_user_id,
        "summary": {
            "total_user_platform_pairs": len(audit_rows),
            "clean":     total_clean,
            "duplicate": total_dirty,
    
    return jsonify({"success": True, "message": f"{slot.value} equipment deleted"})


@app.route("/profile/equipment", methods=["POST"])
@login_required
def save_equipment():
    """Save or update equipment setup (Primary/Secondary)."""
    validate_csrf_request()
    data = request.get_json()
    
    slot_name = data.get("slot", "").upper()  # "PRIMARY" or "SECONDARY"
    discipline_name = data.get("discipline", "").upper()  # "SKIER" or "SNOWBOARDER"
    brand = data.get("brand", "").strip()
    length_cm = data.get("length_cm")
    width_mm = data.get("width_mm")
    
    # Validate
    if not brand or slot_name not in ["PRIMARY", "SECONDARY"] or discipline_name not in ["SKIER", "SNOWBOARDER"]:
        return jsonify({"success": False, "error": "Invalid input"}), 400
    
    # Convert to enums
    try:
        slot = EquipmentSlot[slot_name]
        discipline = EquipmentDiscipline[discipline_name]
    except KeyError:
        return jsonify({"success": False, "error": "Invalid slot or discipline"}), 400
    
    # Explicit permission check: only owner can edit
    equipment = EquipmentSetup.query.filter_by(user_id=current_user.id, slot=slot).first()
    if equipment and equipment.user_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    # Find or create equipment
    if not equipment:
        equipment = EquipmentSetup(user_id=current_user.id, slot=slot)
    
    equipment.discipline = discipline
    equipment.brand = brand
    equipment.length_cm = int(length_cm) if length_cm else None
    equipment.width_mm = int(width_mm) if width_mm else None
    
    db.session.add(equipment)
    db.session.commit()
    
    return jsonify({"success": True, "message": f"{slot.value} equipment saved"})


@app.route("/group-trip/<int:trip_id>/transportation", methods=["POST"])
@login_required
def update_group_trip_transportation(trip_id):
    """Update transportation status (host-only)."""
    validate_csrf_request()
    trip = GroupTrip.query.get_or_404(trip_id)
    
    if trip.host_id != current_user.id:
        return jsonify({"success": False, "error": "Only host can update"}), 403
    
    data = request.get_json()
    status_name = data.get("transportation_status", "").upper()
    
    if status_name == "":
        trip.transportation_status = None
    elif status_name in ["HAVE_TRANSPORT", "NEED_TRANSPORT", "NOT_SURE"]:
        try:
            trip.transportation_status = TransportationStatus[status_name]
        except KeyError:
            return jsonify({"success": False, "error": "Invalid status"}), 400
    else:
        return jsonify({"success": False, "error": "Invalid status"}), 400
    
    db.session.commit()
    return jsonify({"success": True})


# ============================================================================
# CANONICAL PASS BRAND MAPPINGS (for backfill)
# ============================================================================

EPIC_RESORT_NAMES = {
    "Heavenly Mountain Resort", "Kirkwood Mountain Resort", "Northstar California Resort",
    "Vail Mountain", "Beaver Creek", "Breckenridge Ski Resort", "Keystone Resort",
    "Crested Butte Mountain Resort", "Mt. Brighton", "Afton Alps", "Hidden Valley Ski Resort",
    "Attitash Mountain Resort", "Wildcat Mountain", "Hunter Mountain", "Boston Mills",
    "Brandywine", "Mad River Mountain", "Jack Frost Big Boulder", "Roundtop Mountain Resort",
    "Whitetail Resort", "Liberty Mountain Resort", "Park City Mountain", "Mount Snow",
    "Okemo Mountain Resort", "Stowe Mountain Resort", "Stevens Pass", "Wilmot Mountain"
}

INDY_RESORT_NAMES = {
    "Bear Valley", "China Peak", "Dodge Ridge", "Sunlight Mountain Resort",
    "Powderhorn Mountain Resort", "Ski Cooper", "Brundage Mountain", "Tamarack Resort",
    "Lookout Pass", "Saddleback Mountain", "Marquette Mountain", "Blacktail Mountain",
    "Lost Trail Powder Mountain", "Red Lodge Mountain", "Cannon Mountain", "Ski Santa Fe",
    "Titus Mountain", "Willamette Pass", "Blue Knob All Seasons Resort", "Beaver Mountain",
    "Eagle Point Resort", "Bolton Valley", "Magic Mountain", "White Pass", "Snow King Mountain"
}

MOUNTAIN_COLLECTIVE_RESORT_NAMES = {
    "Aspen Snowmass", "Alta Ski Area", "Snowbird", "Jackson Hole Mountain Resort",
    "Sun Valley", "Sugarbush Resort", "Taos Ski Valley"
}


@app.cli.command("backfill-pass-brands")
@click.option("--force", is_flag=True, help="Force re-run even if already populated")
def backfill_pass_brands(force):
    """Backfill pass_brands column for all resorts. Idempotent by default."""
    created = 0
    updated = 0
    skipped = 0
    null_count = 0

    with app.app_context():
        resorts = Resort.query.all()

        for resort in resorts:
            # Skip if already populated and not forcing
            if resort.pass_brands and not force:
                skipped += 1
                continue

            original_pass_brands = resort.pass_brands
            new_pass_brands = None

            # Priority 1: Mountain Collective (Ikon overlap)
            if resort.name in MOUNTAIN_COLLECTIVE_RESORT_NAMES:
                new_pass_brands = "Ikon,MountainCollective"
                resort.brand = "Ikon"

            # Priority 2: Epic
            elif resort.name in EPIC_RESORT_NAMES:
                new_pass_brands = "Epic"
                resort.brand = "Epic"

            # Priority 3: Indy
            elif resort.name in INDY_RESORT_NAMES:
                new_pass_brands = "Indy"
                resort.brand = "Indy"

            # Priority 4: Existing Ikon (default)
            elif resort.brand == "Ikon":
                new_pass_brands = "Ikon"

            # Fallback: Use existing brand
            else:
                new_pass_brands = resort.brand or "Other"

            # Update if changed
            if new_pass_brands != original_pass_brands:
                resort.pass_brands = new_pass_brands
                db.session.commit()
                if original_pass_brands is None:
                    created += 1
                    print(f"  ✨ CREATED: {resort.name} ({resort.state}) → {new_pass_brands}")
                else:
                    updated += 1
                    print(f"  ✏️  UPDATED: {resort.name} ({resort.state}) → {new_pass_brands} (was: {original_pass_brands})")
            else:
                skipped += 1

        # Verify no nulls
        null_check = Resort.query.filter(Resort.pass_brands.is_(None)).count()

        print("\n" + "=" * 70)
        print("BACKFILL SUMMARY")
        print("=" * 70)
        print(f"Total resorts: {len(resorts)}")
        print(f"Pass brands created: {created}")
        print(f"Pass brands updated: {updated}")
        print(f"Pass brands skipped: {skipped}")
        print(f"Resorts with NULL pass_brands: {null_check}")
        print()

        # Distribution by pass
        epic_count = Resort.query.filter(Resort.pass_brands.contains("Epic")).count()
        ikon_count = Resort.query.filter(Resort.pass_brands.contains("Ikon")).count()
        indy_count = Resort.query.filter(Resort.pass_brands.contains("Indy")).count()
        mountain_collective_count = Resort.query.filter(Resort.pass_brands.contains("MountainCollective")).count()

        print("Distribution:")
        print(f"  - Epic: {epic_count}")
        print(f"  - Ikon: {ikon_count}")
        print(f"  - Indy: {indy_count}")
        print(f"  - MountainCollective: {mountain_collective_count}")
        print()

        # Sample resorts
        print("Sample Results (before/after):")
        samples = [
            ("Park City Mountain", "Epic"),
            ("Bolton Valley", "Indy"),
            ("Aspen Snowmass", "Ikon,MountainCollective"),
            ("Jackson Hole Mountain Resort", "Ikon,MountainCollective"),
        ]
        for name, expected_brands in samples:
            resort = Resort.query.filter_by(name=name).first()
            if resort:
                status = "✓" if resort.pass_brands == expected_brands else "✗"
                print(f"  {status} {name}: {resort.pass_brands} (expected: {expected_brands})")
            else:
                print(f"  ✗ {name}: NOT FOUND")

        print()
        print("✅ Backfill complete!")
        print("=" * 70)


# ============================================================================
# DEMO DATA SEEDING (FULL WORLD)
# ============================================================================

SKIER_BRANDS = SKI_BRANDS
SNOWBOARDER_BRANDS = SNOWBOARD_BRANDS
PASS_OPTIONS_SEEDING = ["Epic", "Ikon", "MountainCollective", "Indy", "PowderAlliance", "Freedom", "SkiCalifornia", "Other", "None"]

FIRST_NAMES = ["Alex", "Jordan", "Sam", "Casey", "Riley", "Morgan", "Jamie", "Taylor", "Jesse", "Charlie", "Skylar", "Quinn", "Dakota", "Avery", "Blake", "Parker", "Rowan", "Drew", "Phoenix", "River", "Jade", "Connor", "Reese", "Emerson", "Sage", "Justice", "Scout", "Lex", "Hayden", "Aspen", "Storm", "Finley", "Devyn", "Canyon", "Sierra", "Teton", "Range", "Peak", "Boulder", "Summit", "Ridge", "Trail", "Alpine", "Powder", "Mogul", "Gnar", "Shred", "Carve", "Slate", "Blake", "Bailey", "Cameron"]

LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson"]

TRIP_TITLES = ["powder day mission", "spring corn runs", "lake tahoe adventure", "utah powder week", "colorado peaks", "backcountry tour", "resort lap day", "mogul practice", "tree skiing", "alpine exploration"]


@app.cli.command("seed-full-demo-world")
def seed_full_demo_world():
    """Seed comprehensive demo data for end-to-end testing."""
    print("🌍 SEEDING FULL DEMO WORLD...")
    print("=" * 70)
    
    with app.app_context():
        # ====== FIXED USERS ======
        richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        if not richard:
            richard = User(
                first_name="Richard", last_name="Battle-Baxter",
                email="richardbattlebaxter@gmail.com",
                primary_rider_type="Skier",
                pass_type="Epic", skill_level="Advanced",
                home_state="Colorado", birth_year=1985
            )
            richard.set_password("12345678")
            db.session.add(richard)
            print("✨ Created: Richard Battle-Baxter")
        else:
            print("⊘ Skipped: Richard (already exists)")
        
        jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        if not jonathan:
            jonathan = User(
                first_name="Jonathan", last_name="Schmitz",
                email="jonathanmschmitz@gmail.com",
                primary_rider_type="Skier",
                pass_type="Ikon,MountainCollective", skill_level="Advanced",
                home_state="Utah", birth_year=1990
            )
            jonathan.set_password("12345678")
            db.session.add(jonathan)
            print("✨ Created: Jonathan Schmitz")
        else:
            print("⊘ Skipped: Jonathan (already exists)")
        
        db.session.commit()
        
        # ====== DUMMY USERS (50) ======
        dummy_users = []
        for i in range(50):
            email = f"user{i+1}@baselodge.local"
            if User.query.filter_by(email=email).first():
                print(f"⊘ Skipped: {email} (already exists)")
                dummy_users.append(User.query.filter_by(email=email).first())
                continue
            
            primary_rt = random.choice(["Skier", "Snowboarder"])
            user = User(
                first_name=random.choice(FIRST_NAMES),
                last_name=random.choice(LAST_NAMES),
                email=email,
                primary_rider_type=primary_rt,
                skill_level=random.choice(["Beginner", "Intermediate", "Advanced", "Expert"]),
                home_state=random.choice(["Colorado", "Utah", "California", "Wyoming", "Montana", "Idaho", "Washington"]),
                birth_year=random.randint(1970, 2005)
            )
            
            # 70% single pass, 30% multi-pass
            if random.random() < 0.7:
                user.pass_type = random.choice(["Epic", "Ikon", "Indy", "Other"])
            else:
                user.pass_type = ",".join(sorted(set(random.sample(PASS_OPTIONS_SEEDING[:-2], 2))))
            
            user.set_password("12345678")
            db.session.add(user)
            dummy_users.append(user)
        
        db.session.commit()
        print(f"✨ Created: {len(dummy_users)} dummy users")
        
        # ====== EQUIPMENT ======
        all_users = [richard, jonathan] + dummy_users
        equipment_count = 0
        for user in all_users:
            if EquipmentSetup.query.filter_by(user_id=user.id, is_primary=True).first():
                continue

            user_rt = user.primary_rider_type or user.rider_type or "Skier"
            discipline = EquipmentDiscipline.SKIER if user_rt == "Skier" else EquipmentDiscipline.SNOWBOARDER
            brands = SKIER_BRANDS if user_rt == "Skier" else SNOWBOARDER_BRANDS

            primary = EquipmentSetup(
                user_id=user.id,
                slot=EquipmentSlot.PRIMARY,
                is_primary=True,
                discipline=discipline,
                brand=random.choice(brands),
                length_cm=random.randint(160, 190) if user_rt == "Skier" else random.randint(150, 165),
                width_mm=random.randint(80, 105) if user_rt == "Skier" else None,
                created_at=datetime.utcnow()
            )
            db.session.add(primary)
            equipment_count += 1

            if random.random() < 0.5:
                secondary = EquipmentSetup(
                    user_id=user.id,
                    slot=EquipmentSlot.SECONDARY,
                    is_primary=False,
                    discipline=discipline,
                    brand=random.choice(brands),
                    length_cm=random.randint(160, 190) if user_rt == "Skier" else random.randint(150, 165),
                    width_mm=random.randint(80, 105) if user_rt == "Skier" else None,
                    created_at=datetime.utcnow()
                )
                db.session.add(secondary)
                equipment_count += 1
        
        db.session.commit()
        print(f"✨ Created: {equipment_count} equipment setups")
        
        # ====== SKI TRIPS ======
        resorts = Resort.query.all()
        trip_count = 0
        today = date.today()
        for user in all_users:
            existing_trips = SkiTrip.query.filter_by(user_id=user.id).count()
            if existing_trips >= 4:
                continue
            
            for _ in range(4 - existing_trips):
                start = today + timedelta(days=random.randint(5, 120))
                end = start + timedelta(days=random.randint(1, 5))
                
                trip = SkiTrip(
                    user_id=user.id,
                    resort_id=random.choice(resorts).id,
                    start_date=start,
                    end_date=end,
                    pass_type=random.choice(user.pass_type.split(",")),
                    is_public=True
                )
                db.session.add(trip)
                trip_count += 1
        
        db.session.commit()
        print(f"✨ Created: {trip_count} ski trips")
        
        # ====== FRIEND CONNECTIONS ======
        friend_count = 0
        for user in dummy_users:
            if Friend.query.filter_by(user_id=user.id, friend_id=richard.id).first():
                continue
            
            f1 = Friend(user_id=user.id, friend_id=richard.id)
            f2 = Friend(user_id=richard.id, friend_id=user.id)
            db.session.add_all([f1, f2])
            friend_count += 2
            
            if not Friend.query.filter_by(user_id=user.id, friend_id=jonathan.id).first():
                f3 = Friend(user_id=user.id, friend_id=jonathan.id)
                f4 = Friend(user_id=jonathan.id, friend_id=user.id)
                db.session.add_all([f3, f4])
                friend_count += 2
        
        db.session.commit()
        print(f"✨ Created: {friend_count} friend connections")
        
        # ====== GROUP TRIPS ======
        grouptrip_count = 0
        tripguest_count = 0
        for i in range(5):
            host = richard if i % 2 == 0 else jonathan
            title = f"{random.choice(['March', 'April', 'May'])} {random.choice(TRIP_TITLES)}"
            start = today + timedelta(days=random.randint(10, 60))
            end = start + timedelta(days=random.randint(2, 5))
            
            trip = GroupTrip(
                host_id=host.id,
                title=title,
                start_date=start,
                end_date=end
            )
            db.session.add(trip)
            db.session.flush()
            
            # Add host as accepted guest
            host_guest = TripGuest(trip_id=trip.id, user_id=host.id, status=GuestStatus.ACCEPTED)
            db.session.add(host_guest)
            tripguest_count += 1
            
            # Add jonathan/richard
            other_host = jonathan if host == richard else richard
            other_guest = TripGuest(trip_id=trip.id, user_id=other_host.id, status=GuestStatus.ACCEPTED)
            db.session.add(other_guest)
            tripguest_count += 1
            
            # Add 5-10 random dummy users
            selected_guests = random.sample(dummy_users, min(random.randint(5, 10), len(dummy_users)))
            for guest_user in selected_guests:
                guest = TripGuest(trip_id=trip.id, user_id=guest_user.id, status=GuestStatus.ACCEPTED)
                db.session.add(guest)
                tripguest_count += 1
            
            grouptrip_count += 1
        
        db.session.commit()
        print(f"✨ Created: {grouptrip_count} group trips, {tripguest_count} trip guests")
        
        # ====== OPEN DATES ======
        open_dates_count = 0
        for user in all_users:
            if user.open_dates:
                continue
            
            num_ranges = random.randint(6, 10) if user in [richard, jonathan] else random.randint(3, 6)
            open_dates = []
            for _ in range(num_ranges):
                start = today + timedelta(days=random.randint(5, 180))
                for j in range(random.randint(1, 4)):
                    date_str = (start + timedelta(days=j)).strftime("%Y-%m-%d")
                    if date_str not in open_dates:
                        open_dates.append(date_str)
            
            user.open_dates = sorted(open_dates)
            open_dates_count += len(open_dates)
        
        db.session.commit()
        print(f"✨ Created: {open_dates_count} open dates")
        
        # ====== VERIFICATION ======
        print("\n" + "=" * 70)
        print("VERIFICATION REPORT")
        print("=" * 70)
        print(f"Total users: {User.query.count()}")
        print(f"  - Fixed: 2 (Richard, Jonathan)")
        print(f"  - Dummy: {len(dummy_users)}")
        print(f"Total SkiTrips: {SkiTrip.query.count()}")
        print(f"Total GroupTrips: {GroupTrip.query.count()}")
        print(f"Total TripGuests: {TripGuest.query.count()}")
        print(f"Total EquipmentSetup: {EquipmentSetup.query.count()}")
        print(f"Total Friend connections: {Friend.query.count()}")
        
        # Sample data
        print(f"\nSample Users:")
        for user in random.sample(all_users, min(5, len(all_users))):
            trips = SkiTrip.query.filter_by(user_id=user.id).count()
            equipment = EquipmentSetup.query.filter_by(user_id=user.id).count()
            open_dates = len(user.open_dates) if user.open_dates else 0
            friends_richard = 1 if Friend.query.filter_by(user_id=user.id, friend_id=richard.id).first() else 0
            friends_jonathan = 1 if Friend.query.filter_by(user_id=user.id, friend_id=jonathan.id).first() else 0
            
            print(f"  {user.email}: passes={user.pass_type}, trips={trips}, equipment={equipment}, open_dates={open_dates}, connected_to_richard={friends_richard}, connected_to_jonathan={friends_jonathan}")
        
        print("\n✅ SEEDING COMPLETE!")
        print("=" * 70)


# ============================================================================
# REPAIR DEMO DATA
# ============================================================================

@app.cli.command("repair-demo-data")
def repair_demo_data():
    """Repair seeded demo data: fix passwords and friend connections."""
    print("🔧 REPAIRING DEMO DATA...")
    print("=" * 70)
    
    with app.app_context():
        # ====== FIX PASSWORDS ======
        password_fixes = 0
        
        richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        if richard:
            richard.set_password("12345678")
            db.session.add(richard)
            password_fixes += 1
            print("✨ Reset password: Richard Battle-Baxter")
        
        jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        if jonathan:
            jonathan.set_password("12345678")
            db.session.add(jonathan)
            password_fixes += 1
            print("✨ Reset password: Jonathan Schmitz")
        
        db.session.commit()
        
        # ====== FIX FRIEND CONNECTIONS ======
        friend_fixes = 0
        
        # Get all dummy users
        dummy_users = User.query.filter(
            User.email.like("user%@baselodge.local")
        ).all()
        
        print(f"\nProcessing {len(dummy_users)} dummy users...")
        
        for user in dummy_users:
            # Connect to Richard
            if richard:
                existing_1 = Friend.query.filter_by(user_id=user.id, friend_id=richard.id).first()
                existing_2 = Friend.query.filter_by(user_id=richard.id, friend_id=user.id).first()
                
                if not existing_1:
                    f1 = Friend(user_id=user.id, friend_id=richard.id)
                    db.session.add(f1)
                    friend_fixes += 1
                
                if not existing_2:
                    f2 = Friend(user_id=richard.id, friend_id=user.id)
                    db.session.add(f2)
                    friend_fixes += 1
            
            # Connect to Jonathan
            if jonathan:
                existing_3 = Friend.query.filter_by(user_id=user.id, friend_id=jonathan.id).first()
                existing_4 = Friend.query.filter_by(user_id=jonathan.id, friend_id=user.id).first()
                
                if not existing_3:
                    f3 = Friend(user_id=user.id, friend_id=jonathan.id)
                    db.session.add(f3)
                    friend_fixes += 1
                
                if not existing_4:
                    f4 = Friend(user_id=jonathan.id, friend_id=user.id)
                    db.session.add(f4)
                    friend_fixes += 1
        
        db.session.commit()
        print(f"✨ Added/verified: {friend_fixes} friend connections")
        
        # ====== VERIFICATION ======
        print("\n" + "=" * 70)
        print("VERIFICATION REPORT")
        print("=" * 70)
        
        # Check passwords
        test_richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        test_jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        
        print(f"\nPassword Status:")
        if test_richard and test_richard.check_password("12345678"):
            print(f"  ✓ Richard can log in with 12345678")
        else:
            print(f"  ✗ Richard password FAILED")
        
        if test_jonathan and test_jonathan.check_password("12345678"):
            print(f"  ✓ Jonathan can log in with 12345678")
        else:
            print(f"  ✗ Jonathan password FAILED")
        
        # Check friend connections
        print(f"\nFriend Connection Status:")
        total_dummy = len(dummy_users)
        richard_connections = Friend.query.filter_by(friend_id=richard.id).count() if richard else 0
        jonathan_connections = Friend.query.filter_by(friend_id=jonathan.id).count() if jonathan else 0
        
        print(f"  Dummy users connected to Richard: {richard_connections}/{total_dummy}")
        print(f"  Dummy users connected to Jonathan: {jonathan_connections}/{total_dummy}")
        
        # Sample verification
        print(f"\nSample User Connections:")
        for user in random.sample(dummy_users, min(3, len(dummy_users))):
            friends_richard = 1 if Friend.query.filter_by(user_id=user.id, friend_id=richard.id).first() else 0
            friends_jonathan = 1 if Friend.query.filter_by(user_id=user.id, friend_id=jonathan.id).first() else 0
            
            print(f"  {user.email}: richard_friend={friends_richard}, jonathan_friend={friends_jonathan}")
        
        print("\n✅ REPAIR COMPLETE!")
        print("=" * 70)


@app.cli.command("fix-seeded-users")
def fix_seeded_users():
    """Fix seeded users: reset passwords and ensure friend connections."""
    from werkzeug.security import generate_password_hash
    
    print("🔐 FIXING SEEDED USERS...")
    print("=" * 70)
    
    TARGET_USERS = [
        {
            "email": "richardbattlebaxter@gmail.com",
            "first_name": "Richard",
            "last_name": "Battle-Baxter",
            "password": "12345678"
        },
        {
            "email": "jonathanmschmitz@gmail.com",
            "first_name": "Jonathan",
            "last_name": "Schmitz",
            "password": "12345678"
        }
    ]

    users = {}

    # Step 1: Create or update target users with correct passwords
    print("\n📝 STEP 1: Creating/Updating Target Users")
    for u in TARGET_USERS:
        user = User.query.filter(
            db.func.lower(User.email) == u["email"].lower()
        ).first()

        if not user:
            user = User(
                email=u["email"],
                first_name=u["first_name"],
                last_name=u["last_name"],
                password_hash=generate_password_hash(u["password"])
            )
            db.session.add(user)
            print(f"  ✨ CREATED user {u['email']}")
        else:
            user.password_hash = generate_password_hash(u["password"])
            print(f"  ✏️  RESET password for {u['email']}")

        users[u["email"]] = user

    db.session.commit()

    # Step 2: Fix friend connections
    print("\n🤝 STEP 2: Fixing Friend Connections")
    richard = users["richardbattlebaxter@gmail.com"]
    jonathan = users["jonathanmschmitz@gmail.com"]

    all_users = User.query.all()
    connections_added = 0

    for user in all_users:
        if user.id in (richard.id, jonathan.id):
            continue

        for core in (richard, jonathan):
            exists = Friend.query.filter_by(
                user_id=core.id,
                friend_id=user.id
            ).first()

            if not exists:
                db.session.add(Friend(user_id=core.id, friend_id=user.id))
                db.session.add(Friend(user_id=user.id, friend_id=core.id))
                connections_added += 2

    db.session.commit()
    print(f"  ✨ Added {connections_added} friend connections")

    # Step 3: Fix pass_type cleanup (convert "both" to "epic" for seeded users)
    print("\n🎿 STEP 3: Cleaning up pass_type values")
    seeded_users_with_both = User.query.filter(
        User.is_seeded == True,
        (User.pass_type.ilike('%both%') | (User.pass_type == 'both'))
    ).all()
    
    both_count = 0
    for user in seeded_users_with_both:
        if user.pass_type and 'both' in user.pass_type.lower():
            user.pass_type = user.pass_type.replace('Both', 'Epic').replace('both', 'Epic')
            both_count += 1
    
    if both_count > 0:
        db.session.commit()
        print(f"  ✨ Converted {both_count} seeded users from 'both' to 'epic'")
    else:
        print(f"  ✓ No seeded users with pass_type='both' found")

    # Step 4: Verification
    print("\n" + "=" * 70)
    print("✅ VERIFICATION")
    print("=" * 70)
    
    richard_friends = Friend.query.filter_by(user_id=richard.id).count()
    jonathan_friends = Friend.query.filter_by(user_id=jonathan.id).count()
    
    print(f"Richard friends: {richard_friends}")
    print(f"Jonathan friends: {jonathan_friends}")
    
    # Test password
    richard_pwd_ok = richard.check_password("12345678")
    jonathan_pwd_ok = jonathan.check_password("12345678")
    
    print(f"Richard password check: {richard_pwd_ok}")
    print(f"Jonathan password check: {jonathan_pwd_ok}")
    
    # Check for any remaining "both" values
    users_with_both = User.query.filter(
        User.pass_type.ilike('%both%') | (User.pass_type == 'both')
    ).count()
    print(f"Users with pass_type containing 'both': {users_with_both}")
    
    print("\n✅ FIX COMPLETE!")
    print("=" * 70)


@app.route("/admin/version", methods=["GET"])
@login_required
@admin_required
def admin_version():
    """Simple version check endpoint to verify production deployment."""
    import re
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    db_source = "unknown"
    if db_uri:
        if "supabase" in db_uri.lower():
            db_source = "supabase"
        elif "sqlite" in db_uri.lower():
            db_source = "sqlite"
        else:
            db_source = "external-db"
    return jsonify({
        "app_version": "2026-05-01-ui-sync-check",
        "server_timestamp": datetime.utcnow().isoformat() + "Z",
        "flask_env": os.environ.get("FLASK_ENV", "unknown"),
        "database_url_source": db_source,
        "note": "Used to confirm which version production/TestFlight is loading",
        "status": "ok",
        "endpoints_available": [
            "/admin/version",
            "/admin/backfill-country-codes",
            "/admin/resorts-audit",
            "/admin/init-db",
            "/admin/sync-from-canonical"
        ]
    })


@app.route("/admin/debug-users", methods=["GET"])
@login_required
@admin_required
def debug_users():
    """Inspect production database: user count, first 20 users, and DB URI in use."""
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "not set")
    # Mask password from URI for safe display
    import re
    safe_uri = re.sub(r'(:)[^:@]+(@)', r'\1***\2', db_uri)
    users = User.query.order_by(User.id).limit(20).all()
    total = User.query.count()
    return jsonify({
        "database_uri": safe_uri,
        "total_user_count": total,
        "first_20_users": [
            {
                "id": u.id,
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
            }
            for u in users
        ]
    })


@app.route("/admin/db-status", methods=["GET"])
@login_required
@admin_required
def admin_db_status():
    """
    Read-only diagnostic: confirms which database engine is active, whether
    SQLite fallback is in use, and reports counts for all core tables.
    No writes. Safe to call in production at any time.
    """
    import re

    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "not set")
    safe_uri = re.sub(r'(:)[^:@]+(@)', r'\1***\2', db_uri)

    engine_type = (
        "postgresql" if "postgresql" in db_uri or "postgres" in db_uri
        else "sqlite" if "sqlite" in db_uri
        else "unknown"
    )
    is_sqlite_fallback = "sqlite" in db_uri

    raw_env_url = os.environ.get("SUPABASE_DATABASE_URL", "")
    env_url_present = bool(raw_env_url)
    env_url_scheme = raw_env_url.split("://")[0] if "://" in raw_env_url else "not set"
    env_url_host = raw_env_url.split("@")[-1] if "@" in raw_env_url else "no @ found"

    try:
        counts = {
            "users":                  User.query.count(),
            "ski_trips":              SkiTrip.query.count(),
            "ski_trip_participants":  SkiTripParticipant.query.count(),
            "friends":                Friend.query.count(),
            "invitations":            Invitation.query.count(),
            "invite_tokens":          InviteToken.query.count(),
            "group_trips":            GroupTrip.query.count(),
            "trip_guests":            TripGuest.query.count(),
        }
        counts_ok = True
        counts_error = None
    except Exception as e:
        counts = {}
        counts_ok = False
        counts_error = str(e)

    return jsonify({
        "db_engine":             engine_type,
        "active_uri_masked":     safe_uri,
        "is_sqlite_fallback":    is_sqlite_fallback,
        "is_production_flag":    is_production,
        "supabase_env_var": {
            "present":           env_url_present,
            "scheme":            env_url_scheme,
            "host_masked":       env_url_host,
        },
        "table_counts":          counts,
        "table_counts_ok":       counts_ok,
        "table_counts_error":    counts_error,
        "assessed_at":           datetime.utcnow().isoformat() + "Z",
        "note": (
            "SQLITE FALLBACK ACTIVE — users may be writing to a local file, not Supabase"
            if is_sqlite_fallback else
            "Supabase PostgreSQL active — no SQLite fallback"
        ),
    })


@app.route("/admin/export-live-data", methods=["GET"])
@login_required
@admin_required
def export_live_data():
    """Read-only full data rescue export. Returns all critical user-linked table rows as JSON."""
    import enum as _enum

    def _val(v):
        """Serialize a column value to a JSON-safe primitive."""
        if v is None:
            return None
        if isinstance(v, _enum.Enum):
            return v.value
        if hasattr(v, 'isoformat'):
            return v.isoformat()
        return v

    def _row(obj, exclude=None):
        exclude = set(exclude or [])
        return {
            c.name: _val(getattr(obj, c.name))
            for c in obj.__table__.columns
            if c.name not in exclude
        }

    users           = User.query.order_by(User.id).all()
    trips           = SkiTrip.query.order_by(SkiTrip.id).all()
    friends         = Friend.query.order_by(Friend.id).all()
    participants    = SkiTripParticipant.query.order_by(SkiTripParticipant.id).all()
    invitations     = Invitation.query.order_by(Invitation.id).all()
    invite_tokens   = InviteToken.query.order_by(InviteToken.id).all()
    group_trips     = GroupTrip.query.order_by(GroupTrip.id).all()
    trip_guests     = TripGuest.query.order_by(TripGuest.id).all()

    return jsonify({
        "exported_at": datetime.utcnow().isoformat(),
        "database_uri": re.sub(r'(:)[^:@]+(@)', r'\1***\2',
                               app.config.get("SQLALCHEMY_DATABASE_URI", "not set")),
        "counts": {
            "users":            len(users),
            "ski_trips":        len(trips),
            "friends":          len(friends),
            "ski_trip_participants": len(participants),
            "invitations":      len(invitations),
            "invite_tokens":    len(invite_tokens),
            "group_trips":      len(group_trips),
            "trip_guests":      len(trip_guests),
        },
        "users":            [_row(u, exclude=["password_hash"]) for u in users],
        "ski_trips":        [_row(t) for t in trips],
        "friends":          [_row(f) for f in friends],
        "ski_trip_participants": [_row(p) for p in participants],
        "invitations":      [_row(i) for i in invitations],
        "invite_tokens":    [_row(t) for t in invite_tokens],
        "group_trips":      [_row(g) for g in group_trips],
        "trip_guests":      [_row(g) for g in trip_guests],
    })


@app.route("/admin/resorts-audit", methods=["GET"])
@login_required
@admin_required
def resorts_audit():
    """Read-only endpoint to fetch all resorts for audit comparison."""
    resorts = Resort.query.all()
    return jsonify({
        "total": len(resorts),
        "resorts": [
            {
                "name": r.name,
                "state_code": r.state_code or r.state,
                "country_code": r.country_code or r.country,
                "pass_brands": r.pass_brands or r.brand
            }
            for r in resorts
        ]
    })


@app.route("/admin/backfill-country-codes", methods=["GET", "POST"])
@login_required
@admin_required
def backfill_country_codes():
    """
    Backfill country_code and state_code for resorts based on state field.
    v2 - Updated 2025-12-25
    
    Usage: GET https://yourapp.replit.dev/admin/backfill-country-codes
    
    This is idempotent - safe to call multiple times.
    """
    if request.method == "POST":
        validate_csrf_request()
    US_STATES = {
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
/MAU undercount possible)',
            'MEL invite metrics cover May 2026 only — historical data not available',
            'Viral coefficient (K-factor) intentionally omitted — cannot be reliably computed from current schema',
        ],
    }

    return render_template(
        "admin_growth_intel.html",
        active_tab            = 'growth_intel',
        now                   = now_str,
        total                 = total,
        kpis                  = kpis,
        new_l7                = new_l7,
        new_l30               = new_l30,
        new_l90               = new_l90,
        null_created          = null_created,
        cohort_list           = cohort_list,
        unique_pairs          = unique_pairs,
        connected_users       = connected_users,
        avg_friends_all       = avg_friends_all,
        avg_friends_connected = avg_friends_connected,
        friend_monthly_list   = friend_monthly_list,
        friend_dist           = friend_dist,
        most_connected_name   = most_connected_name,
        most_connected_ct     = mc_ct,
        inv_total             = inv_total,
        inv_used              = inv_used,
        trip_inv_total        = trip_inv_total,
        trip_inv_used         = trip_inv_used,
        mel_trip_created      = mel_trip_created,
        mel_trip_accepted     = mel_trip_accepted,
        mel_fr_created        = mel_fr_created,
        mel_fr_accepted       = mel_fr_accepted,
        part_accepted         = part_accepted,
        part_total            = part_total,
        fly_invite            = fly_invite,
        fly_signup            = fly_signup,
        fly_friend            = fly_friend_users,
        fly_trip              = fly_trip_users,
        wau                   = wau,
        mau                   = mau,
        null_last_active      = null_last_active,
        referred              = referred,
        insight               = insight,
        status                = status,
    )


@app.route("/admin/crm-intel")
@login_required
@admin_required
def admin_crm_intel():
    """CRM & Lifecycle Intelligence v1 — reachability, segments, audiences, power users."""
    import json as _json
    from datetime import datetime as _dt, timedelta
    from collections import defaultdict

    now_str = _admin_now().strftime("%b %d, %Y at %H:%M %Z")
    now = _dt.utcnow()

    def pct(n, d):
        return round(n / d * 100) if d else 0

    _no_pass = {'no_pass', 'no_pass_yet', 'none', ''}

    def _real_pass(pt):
        for s in (pt or '').split(','):
            if s.strip().lower() not in _no_pass:
                return True
        return False

    def _nonempty(val):
        if val is None:
            return False
        if isinstance(val, list):
            return len(val) > 0
        if isinstance(val, str):
            try:
                p = _json.loads(val)
                return isinstance(p, list) and len(p) > 0
            except Exception:
                return False
        return False

    # ── Q1: all users (all CRM fields) ───────────────────────────────────
    user_rows = db.session.execute(db.text(
        'SELECT id, lifecycle_stage, pass_type, open_dates, wish_list_resorts, '
        'last_active_at, created_at, invited_by_user_id, push_notifications_enabled '
        'FROM "user"'
    )).fetchall()
    total = len(user_rows)

    # ── Q2: push device tokens (active) ──────────────────────────────────
    push_rows = db.session.execute(db.text(
        "SELECT user_id, active FROM push_device_token"
    )).fetchall()
    push_active_ids = {r[0] for r in push_rows if r[1]}

    # MEL push delivery stats
    mel_push = db.session.execute(db.text(
        "SELECT "
        "  COUNT(*) FILTER (WHERE delivery_status='sent'),  "
        "  COUNT(*) FILTER (WHERE delivery_status='failed') "
        "FROM message_event_log WHERE channel='push'"
    )).fetchone()
    mel_sent   = mel_push[0] or 0
    mel_failed = mel_push[1] or 0
    push_fail_rate = pct(mel_failed, mel_sent + mel_failed) if (mel_sent + mel_failed) else 0

    # ── Q3: friend counts per user ────────────────────────────────────────
    friend_counts = {r[0]: r[1] for r in db.session.execute(db.text(
        "SELECT user_id, COUNT(*) FROM friend GROUP BY user_id"
    ))}
    friend_ids = set(friend_counts.keys())

    # ── Q4: trip ownership + participation ───────────────────────────────
    trip_owner_ids = {r[0] for r in db.session.execute(
        db.text("SELECT DISTINCT user_id FROM ski_trip")
    )}
    trip_part_ids = {r[0] for r in db.session.execute(
        db.text("SELECT DISTINCT user_id FROM ski_trip_participant WHERE status IN ('interested', 'going')")
    )}
    has_trip_ids = trip_owner_ids | trip_part_ids

    trip_counts_map = {r[0]: r[1] for r in db.session.execute(
        db.text("SELECT user_id, COUNT(*) FROM ski_trip GROUP BY user_id")
    )}

    # ── Q5: invite generators + counts ───────────────────────────────────
    invite_counts_map = {r[0]: r[1] for r in db.session.execute(
        db.text("SELECT inviter_id, COUNT(*) FROM invite_token GROUP BY inviter_id")
    )}
    trip_invite_counts = {r[0]: r[1] for r in db.session.execute(
        db.text("SELECT inviter_user_id, COUNT(*) FROM trip_invite_token GROUP BY inviter_user_id")
    )}
    for uid, ct in trip_invite_counts.items():
        invite_counts_map[uid] = invite_counts_map.get(uid, 0) + ct
    invite_ids = set(invite_counts_map.keys())

    # ── Derive per-user signal sets ───────────────────────────────────────
    pass_ids     = set()
    avail_ids    = set()
    wishlist_ids = set()
    all_ids      = set()
    lc_map       = {}

    for r in user_rows:
        uid, ls = r[0], r[1]
        all_ids.add(uid)
        lc_map[uid] = ls or 'new'
        if _real_pass(r[2]):   pass_ids.add(uid)
        if _nonempty(r[3]):    avail_ids.add(uid)
        if _nonempty(r[4]):    wishlist_ids.add(uid)

    # Engagement score per user (max 5)
    def _score(uid):
        return sum([uid in pass_ids, uid in avail_ids, uid in wishlist_ids,
                    uid in has_trip_ids, uid in friend_ids])

    # Segment counts
    seg = {'new': 0, 'onboarding': 0, 'activated': 0, 'engaged': 0, 'power': 0, 'untracked': 0}
    untracked_ids = set()
    for r in user_rows:
        uid, ls, la = r[0], r[1] or 'new', r[5]
        if la is None:
            untracked_ids.add(uid)
        sc = _score(uid)
        if ls == 'active':
            if sc >= 4:   seg['power']     += 1
            elif sc >= 2: seg['engaged']   += 1
            else:         seg['activated'] += 1
        elif ls == 'onboarding':
            seg['onboarding'] += 1
        else:
            seg['new'] += 1
    seg['untracked'] = len(untracked_ids)

    n_activated = seg['activated']
    n_engaged   = seg['engaged']
    n_power     = seg['power']
    n_push_active = len(push_active_ids)
    n_no_push     = total - n_push_active

    # Lifecycle × reachability
    active_ids_lc     = {r[0] for r in user_rows if (r[1] or 'new') == 'active'}
    new_ids_lc        = {r[0] for r in user_rows if (r[1] or 'new') == 'new'}
    onboard_ids_lc    = {r[0] for r in user_rows if (r[1] or 'new') == 'onboarding'}

    active_push  = len(active_ids_lc & push_active_ids)
    new_push     = len(new_ids_lc & push_active_ids)
    onboard_push = len(onboard_ids_lc & push_active_ids)

    # ── Section 0: CRM KPIs ──────────────────────────────────────────────
    kpis = [
        {'label': 'Reachable Users',    'value': n_push_active,
         'sub': f'{pct(n_push_active, total)}% have active push'},
        {'label': 'Unreachable Users',  'value': n_no_push,
         'sub': 'no active device token'},
        {'label': 'Activated Users',    'value': seg['activated'] + seg['engaged'] + seg['power'],
         'sub': 'lifecycle = active',   'highlight': True},
        {'label': 'Engaged Users',      'value': n_engaged,
         'sub': '2–3 milestones',       'conf': 'yellow'},
        {'label': 'Power Users',        'value': n_power,
         'sub': '4–5 milestones',       'conf': 'yellow'},
        {'label': 'Untracked',          'value': seg['untracked'],
         'sub': 'no session history'},
        {'label': 'Pass Users',         'value': len(pass_ids),
         'sub': f'{pct(len(pass_ids), total)}% of all users'},
        {'label': 'Connected Users',    'value': len(friend_ids),
         'sub': f'{pct(len(friend_ids), total)}% of all users'},
        {'label': 'Push Failure Rate',  'value': f'{push_fail_rate}%',
         'sub': f'{mel_failed} failed / {mel_sent+mel_failed} (May 2026)', 'conf': 'yellow',
         'alert': push_fail_rate >= 20},
    ]

    # ── Section 2: Lifecycle segments ────────────────────────────────────
    lifecycle_segments = [
        {'label': 'New',        'n': seg['new'],        'pct': pct(seg['new'], total),
         'criteria': 'lifecycle_stage = new', 'conf': 'green'},
        {'label': 'Onboarding', 'n': seg['onboarding'], 'pct': pct(seg['onboarding'], total),
         'criteria': 'lifecycle_stage = onboarding', 'conf': 'green'},
        {'label': 'Activated',  'n': seg['activated'],  'pct': pct(seg['activated'], total),
         'criteria': 'active, 0–1 milestones', 'conf': 'yellow'},
        {'label': 'Engaged',    'n': seg['engaged'],    'pct': pct(seg['engaged'], total),
         'criteria': 'active, 2–3 milestones', 'conf': 'yellow'},
        {'label': 'Power',      'n': seg['power'],      'pct': pct(seg['power'], total),
         'criteria': 'active, 4–5 milestones', 'conf': 'yellow'},
        {'label': 'Untracked',  'n': seg['untracked'],  'pct': pct(seg['untracked'], total),
         'criteria': 'last_active_at IS NULL', 'conf': 'yellow'},
    ]

    # ── Section 3: CRM Audiences ──────────────────────────────────────────
    aud_pass_no_avail       = len(pass_ids - avail_ids)
    aud_connected_no_trip   = len(friend_ids - has_trip_ids)
    aud_reachable_no_trip   = len(push_active_ids - has_trip_ids)
    aud_reachable_no_pass   = len(push_active_ids - pass_ids)
    aud_wishlist_no_trip    = len(wishlist_ids - has_trip_ids)
    aud_invite_no_friend    = len(invite_ids - friend_ids)
    aud_activated_no_friend = len(active_ids_lc - friend_ids)
    aud_trip_no_friend      = len(has_trip_ids - friend_ids)

    crm_audiences = [
        # High priority
        {'label': 'Pass, No Availability',      'size': aud_pass_no_avail,
         'priority': 'high',
         'opp': 'Pass holders who haven\'t set open dates — convert planners'},
        {'label': 'Connected, No Trip',          'size': aud_connected_no_trip,
         'priority': 'high',
         'opp': 'Have friends but no trip — social nudge to plan together'},
        {'label': 'Reachable, No Trip',          'size': aud_reachable_no_trip,
         'priority': 'high',
         'opp': 'Push-reachable users who have never planned'},
        # Medium priority
        {'label': 'Reachable, No Pass',          'size': aud_reachable_no_pass,
         'priority': 'medium',
         'opp': 'Push-reachable users missing a pass — pass selection nudge'},
        {'label': 'Wishlist, No Trip',           'size': aud_wishlist_no_trip,
         'priority': 'medium',
         'opp': 'Have intent (wishlist) but no planned trip'},
        {'label': 'Invite Generated, No Friend', 'size': aud_invite_no_friend,
         'priority': 'medium',
         'opp': 'Sent invites but no friend connection made yet'},
        # Low priority
        {'label': 'Activated, No Friends',       'size': aud_activated_no_friend,
         'priority': 'low',
         'opp': 'Active users who are isolated — friend discovery nudge'},
        {'label': 'Trip, No Friends',            'size': aud_trip_no_friend,
         'priority': 'low',
         'opp': 'Planning solo — potential for social conversion'},
    ]
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    crm_audiences.sort(key=lambda x: (priority_order[x['priority']], -x['size']))

    # ── Section 4: Dormancy ───────────────────────────────────────────────
    l30_cutoff = now - timedelta(days=30)
    l60_cutoff = now - timedelta(days=60)
    recently_inactive_30 = sum(
        1 for r in user_rows
        if r[5] is not None and r[5] < l30_cutoff
    )
    recently_inactive_60 = sum(
        1 for r in user_rows
        if r[5] is not None and r[5] < l60_cutoff
    )
    dormancy = {
        'untracked':          seg['untracked'],
        'recently_inactive_30': recently_inactive_30,
        'recently_inactive_60': recently_inactive_60,
    }

    # ── Section 5: Power users ────────────────────────────────────────────
    scored_users = []
    for uid in all_ids:
        fc = friend_counts.get(uid, 0)
        tc = trip_counts_map.get(uid, 0)
        ic = invite_counts_map.get(uid, 0)
        # Composite: normalise each to max, sum ranks
        scored_users.append({'uid': uid, 'friends': fc, 'trips': tc, 'invites': ic,
                              'composite': fc + tc + ic})
    scored_users.sort(key=lambda x: -x['composite'])

    # Fetch names for top 5
    top5_ids = [u['uid'] for u in scored_users[:5]]
    name_map = {}
    if top5_ids:
        name_rows = db.session.execute(
            db.text('SELECT id, first_name, last_name FROM "user" WHERE id = ANY(:ids)'),
            {'ids': top5_ids}
        ).fetchall()
        name_map = {r[0]: f"{r[1]} {r[2]}" for r in name_rows}

    power_users = []
    for rank, u in enumerate(scored_users[:5], 1):
        power_users.append({
            'rank':     rank,
            'name':     name_map.get(u['uid'], f"User {u['uid']}"),
            'friends':  u['friends'],
            'trips':    u['trips'],
            'invites':  u['invites'],
            'score':    u['composite'],
        })

    # ── Section 6: Dynamic Insight ────────────────────────────────────────
    # Ordered preference: largest actionable gap
    if aud_pass_no_avail >= 10:
        insight = (f"{aud_pass_no_avail} users have a pass but no availability set "
                   f"— the biggest planning gap.")
    elif aud_connected_no_trip >= 10:
        insight = (f"{aud_connected_no_trip} connected users haven't planned a trip together yet.")
    elif aud_reachable_no_trip >= 5:
        insight = (f"{aud_reachable_no_trip} push-reachable users have never planned a trip.")
    else:
        insight = f"{pct(len(friend_ids), total)}% of users are connected with friends."

    # ── Section 7: Status ────────────────────────────────────────────────
    status = {
        'crm_audited': 18, 'crm_green': 10, 'crm_yellow': 6, 'crm_red': 2,
        'ret_audited': 10, 'ret_green':  1, 'ret_yellow': 7, 'ret_red': 2,
        'confidence': 'Growing',
        'caveats': [
            'push_notifications_enabled defaults to true for all users — not a reliable opt-in signal',
            'login_count has not been backfilled — 30 of 36 users show 0 logins',
            'Dormancy signals limited by NULL last_active_at (9 untracked accounts)',
            'Retention Intelligence dashboard intentionally deferred — signals too noisy at current scale',
        ],
    }

    return render_template(
        "admin_crm_intel.html",
        active_tab         = 'crm_intel',
        now                = now_str,
        total              = total,
        kpis               = kpis,
        n_push_active      = n_push_active,
        n_no_push          = n_no_push,
        active_push        = active_push,
        new_push           = new_push,
        onboard_push       = onboard_push,
        n_active_lc        = len(active_ids_lc),
        n_new_lc           = len(new_ids_lc),
        n_onboard_lc       = len(onboard_ids_lc),
        mel_sent           = mel_sent,
        mel_failed         = mel_failed,
        push_fail_rate     = push_fail_rate,
        lifecycle_segments = lifecycle_segments,
        crm_audiences      = crm_audiences,
        dormancy           = dormancy,
        power_users        = power_users,
        insight            = insight,
        status             = status,
    )


# ══════════════════════════════════════════════════════════════════════════
# Admin — Active Today API + User Detail
# ══════════════════════════════════════════════════════════════════════════

@app.route("/admin/api/active-today-users")
@login_required
@admin_required
def admin_api_active_today_users():
    """JSON list of users active today — exact same predicate as Founder Pulse Active count."""
    today_start = _admin_today_start_utc()
    users = User.query.filter(User.last_active_at >= today_start)\
                      .order_by(User.last_active_at.desc()).all()
    result = []
    for u in users:
        first = (u.first_name or "").strip()
        last  = (u.last_name  or "").strip()
        name  = f"{first} {last}".strip() or "Unknown User"
        result.append({
            "id":                u.id,
            "name":              name,
            "state":             u.home_state or "",
            "last_active_at_iso": u.last_active_at.isoformat() if u.last_active_at else None,
        })
    return jsonify(result)


@app.route("/admin/api/new-users-today")
@login_required
@admin_required
def admin_api_new_users_today():
    """JSON list of users who signed up today — same Denver midnight as Founder Pulse."""
    today_start = _admin_today_start_utc()
    users = User.query.filter(User.created_at >= today_start)\
                      .order_by(User.created_at.desc()).all()
    result = []
    for u in users:
        result.append({
            "user_id":    u.id,
            "first_name": (u.first_name or "").strip(),
            "last_name":  (u.last_name  or "").strip(),
            "email":      u.email or "",
            "state":      u.home_state or "",
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })
    return jsonify(result)


@app.route("/admin/test-founder-app-open-push", methods=["POST"])
@login_required
@admin_required
def admin_test_founder_app_open_push():
    """Simulate the app-open founder push for a given user_id.

    POST /admin/test-founder-app-open-push?user_id=42

    Returns JSON describing every gate check so you can see exactly why
    a push would or would not send — without touching session throttle state.
    """
    validate_csrf_request()
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return jsonify({"error": "user_id query param required (e.g. ?user_id=42)"}), 400

    # ── Gate 1: feature flag ──────────────────────────────────────────────────
    enabled = os.environ.get("FOUNDER_APP_OPEN_PUSH_ENABLED", "").lower() == "true"
    if not enabled:
        return jsonify({
            "sent": False,
            "reason": "feature_disabled",
            "fix": "Set FOUNDER_APP_OPEN_PUSH_ENABLED=true in Secrets / environment variables",
        })

    # ── Gate 2: user exists ───────────────────────────────────────────────────
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"sent": False, "reason": "user_not_found", "user_id": user_id}), 404

    # ── Gate 3: not seeded ────────────────────────────────────────────────────
    if getattr(user, "is_seeded", False):
        return jsonify({"sent": False, "reason": "seeded_user", "user_id": user_id})

    # ── Gate 4: not a founder/admin ───────────────────────────────────────────
    admin_emails = {
        e.strip().lower()
        for e in os.environ.get("ALLOWED_ADMIN_EMAILS", "").split(",")
        if e.strip()
    }
    if user.email.lower() in admin_emails:
        return jsonify({
            "sent": False,
            "reason": "founder_user",
            "email": user.email,
            "note": "This is the founder account — it is intentionally excluded",
        })

    # ── Gate 5: founder (richard) has a push token ────────────────────────────
    richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
    if not richard:
        return jsonify({"sent": False, "reason": "no_founder_account"})

    # ── All gates passed — fire synchronously so we get the result inline ─────
    try:
        from services.push_providers import send_onesignal_push as _os_push

        first = (user.first_name or "").strip()
        last  = (user.last_name  or "").strip()
        name  = (first + " " + last).strip()
        state = (user.home_state or "").strip()

        if name and state:
            body = f"{name} opened the app · {state}"
        elif name:
            body = f"{name} opened the app"
        else:
            body = "Someone opened BaseLodge"

        result = _os_push([richard.id], "BaseLodge Opened", body)
        app.logger.warning(
            "[founder_app_open_push] TEST user_id=%d sent=%s skipped=%s error=%s body=%r",
            user_id, result.get("success"), result.get("skipped"), result.get("error"), body,
        )
        return jsonify({
            "sent":              result.get("success", False),
            "skipped":           result.get("skipped"),
            "skipped_reason":    result.get("skipped_reason"),
            "push_error":        result.get("error"),
            "push_body":         body,
            "richard_id":        richard.id,
            "user_id":           user_id,
            "note":              "Session throttle NOT updated — safe to call multiple times for QA",
        })
    except Exception as exc:
        app.logger.exception("[founder_app_open_push] TEST error: %s", exc)
        return jsonify({"sent": False, "reason": "exception", "error": str(exc)}), 500


@app.route("/admin/test-founder-signup-push", methods=["POST"])
@login_required
@admin_required
def admin_test_founder_signup_push():
    """TEST-ONLY — sends a hardcoded founder signup alert to richardbattlebaxter@gmail.com.
    Remove or disable after QA passes.
    """
    validate_csrf_request()
    try:
        from services.push_providers import send_onesignal_push as _os_push
        richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        if not richard:
            return jsonify({"success": False, "error": "richard account not found"}), 404

        title = "New BaseLodge User 🎿"
        body  = "Alex Smith just signed up (NJ)\nConnected to James Morgan"
        result = _os_push([richard.id], title, body)
        if result.get("success"):
            return jsonify({"success": True,
                            "skipped": result.get("skipped"),
                            "skipped_reason": result.get("skipped_reason"),
                            "provider_message_id": result.get("provider_message_id")})
        return jsonify({"success": False, "error": result.get("error")}), 500
    except Exception as exc:
        app.logger.exception("[TestFounderPush] unexpected error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/admin/users/<int:user_id>")
@login_required
@admin_required
def admin_user_detail(user_id):
    """Admin-only drilldown page for a single user."""
    from datetime import datetime as _dt
    from sqlalchemy import or_ as _or

    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    today_start = _admin_today_start_utc()
    now_utc     = _dt.utcnow()

    is_active_today = bool(user.last_active_at and user.last_active_at >= today_start)

    trips_created = SkiTrip.query.filter_by(user_id=user_id)\
                                 .order_by(SkiTrip.start_date.desc().nullslast())\
                                 .limit(5).all()
    trips_created_count = SkiTrip.query.filter_by(user_id=user_id).count()

    trips_joined_count = SkiTripParticipant.query.filter(
        SkiTripParticipant.user_id == user_id,
        SkiTripParticipant.active_status_filter(),
    ).count()

    friend_count = Friend.query.filter(
        _or(Friend.user_id == user_id, Friend.friend_id == user_id)
    ).count()

    activity_days = db.session.execute(db.text(
        'SELECT COUNT(DISTINCT DATE(created_at)) FROM activity WHERE actor_user_id = :uid'
    ), {"uid": user_id}).scalar() or 0

    activity_label_map = {
        "trip_created":                        "Created Trip",
        "trip_updated":                        "Updated Trip",
        "friend_joined_trip":                  "Friend Joined Trip",
        "trip_invite_received":                "Received Trip Invite",
        "trip_invite_accepted":                "Accepted Trip Invite",
        "trip_invite_declined":                "Declined Trip Invite",
        "connection_accepted":                 "Made a New Friend",
        "trip_overlap":                        "Trip Overlap Found",
        "friend_trip_overlaps_availability":   "Availability Match",
        "carpool_offered":                     "Carpool Offered",
        "join_request_received":               "Received Join Request",
        "join_request_accepted":               "Join Request Accepted",
        "join_request_declined":               "Join Request Declined",
        "trip_location_changed":               "Changed Trip Location",
        "trip_pass_changed":                   "Updated Trip Pass",
    }

    act_rows = Activity.query.filter_by(actor_user_id=user_id)\
                             .order_by(Activity.created_at.desc()).limit(40).all()
    mpv_rows = MountainPageView.query.filter_by(user_id=user_id)\
                                     .order_by(MountainPageView.viewed_at.desc()).limit(40).all()

    combined = []
    for a in act_rows:
        raw = a.type.value if hasattr(a.type, "value") else str(a.type)
        label = activity_label_map.get(raw, raw.replace("_", " ").title())
        combined.append({"label": label, "ts": a.created_at})
    for v in mpv_rows:
        resort_name = (v.resort.name if v.resort else None) or "a mountain"
        combined.append({"label": f"Viewed {resort_name}", "ts": v.viewed_at})

    combined.sort(key=lambda x: x["ts"] or _dt.min, reverse=True)
    recent_activity = combined[:20]

    pass_raw = (user.pass_type or "").strip().lower()
    if not pass_raw or pass_raw in ("no_pass", "no_pass_yet", "none"):
        pass_display = "No pass on file"
    else:
        pass_display = user.pass_type

    state_full = STATE_NAMES.get(user.home_state or "", user.home_state or "")

    def _count_json_list(field):
        if not field:
            return 0
        try:
            parsed = json.loads(field) if isinstance(field, str) else field
            return len(parsed) if isinstance(parsed, list) else 0
        except Exception:
            return 0

    wish_count    = _count_json_list(user.wish_list_resorts)
    visited_count = _count_json_list(user.visited_resort_ids)

    def _fmt_trip_dates(trip):
        try:
            if trip.start_date and trip.end_date:
                sm = trip.start_date.strftime("%b %-d")
                em = trip.end_date.strftime("%-d") if trip.start_date.month == trip.end_date.month \
                     else trip.end_date.strftime("%b %-d")
                return f"{sm}–{em}"
            elif trip.start_date:
                return trip.start_date.strftime("%b %-d")
        except Exception:
            pass
        return ""

    trip_display = []
    for t in trips_created:
        resort_name = t.mountain or (t.resort.name if t.resort else None) or "Unknown"
        trip_display.append({
            "name":  resort_name,
            "dates": _fmt_trip_dates(t),
        })

    now_str = _admin_now().strftime("%b %d, %Y at %H:%M %Z")

    return render_template(
        "admin_user_detail.html",
        active_tab          = "dashboard",
        user                = user,
        is_active_today     = is_active_today,
        state_full          = state_full,
        pass_display        = pass_display,
        trips_created_count = trips_created_count,
        trips_joined_count  = trips_joined_count,
        friend_count        = friend_count,
        activity_days       = activity_days,
        recent_activity     = recent_activity,
        wish_count          = wish_count,
        visited_count       = visited_count,
        trip_display        = trip_display,
        now_str             = now_str,
        now_utc             = now_utc,
    )


# ============================================================================
# ADMIN — USER LOOKUP (auth diagnostic by email)
# ============================================================================

@app.route("/admin/user-lookup")
@login_required
@admin_required
def admin_user_lookup():
    """
    Safe auth diagnostic: look up a user by email and return key account fields.
    Never exposes password hashes or secrets.

    GET /admin/user-lookup?email=someone@example.com
    """
    email = request.args.get("email", "").lower().strip()
    if not email:
        return jsonify({"error": "Provide ?email= query parameter"}), 400

    user = User.query.filter(sa.func.lower(User.email) == email).first()
    if not user:
        return jsonify({"found": False, "email_queried": email}), 404

    return jsonify({
        "found": True,
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "auth_provider": user.auth_provider,
        "has_password": bool(user.password_hash),
        "is_verified": user.is_verified,
        "is_seeded": user.is_seeded,
        "lifecycle_stage": user.lifecycle_stage,
        "login_count": user.login_count,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_active_at": user.last_active_at.isoformat() if user.last_active_at else None,
        "password_changed_at": user.password_changed_at.isoformat() if user.password_changed_at else None,
        "admin_detail_url": url_for("admin_user_detail", user_id=user.id, _external=False),
    })


# ============================================================================
# ADMIN — APP STORE PERFORMANCE
# ============================================================================

@app.route("/admin/app-store")
@login_required
@admin_required
def admin_app_store():
    """App Store Performance — reads from AppStoreMetric table only.
    No live calls to Apple or Google at page-render time."""
    from models import AppStoreMetric
    from datetime import date, timedelta
    from collections import defaultdict

    today     = date.today()
    yesterday = today - timedelta(days=1)
    l7_start  = today - timedelta(days=7)
    l30_start = today - timedelta(days=30)

    rows = (
        AppStoreMetric.query
        .filter(AppStoreMetric.report_date >= l30_start)
        .order_by(AppStoreMetric.report_date.desc())
        .all()
    )

    def _rows_for(platform):
        return [r for r in rows if r.platform == platform]

    def _dl_sum(platform_rows):
        vals = [r.downloads for r in platform_rows if r.downloads is not None]
        return sum(vals) if vals else None

    def _latest_rating(platform_rows):
        for r in platform_rows:
            if r.rating is not None:
                return r.rating
        return None

    def _latest_reviews(platform_rows):
        for r in platform_rows:
            if r.review_count is not None:
                return r.review_count
        return None

    def _dl_yesterday(platform_rows):
        for r in platform_rows:
            if r.report_date == yesterday and r.downloads is not None:
                return r.downloads
        return None

    def _dl_l7(platform_rows):
        vals = [r.downloads for r in platform_rows
                if r.report_date >= l7_start and r.downloads is not None]
        return sum(vals) if vals else None

    def _sparkline_series(platform_rows):
        """Return 30-element daily download list for sparkline (oldest → newest)."""
        by_date = {r.report_date: (r.downloads or 0) for r in platform_rows
                   if r.downloads is not None}
        series = []
        for delta in range(29, -1, -1):
            d = today - timedelta(days=delta)
            series.append(by_date.get(d, 0))
        return series

    def _crash_rate_avg(platform_rows):
        vals = [r.crashes for r in platform_rows if r.crashes is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    ios_rows     = _rows_for("ios")
    android_rows = _rows_for("android")

    ios_kpis = dict(
        dl_yesterday = _dl_yesterday(ios_rows),
        dl_l7        = _dl_l7(ios_rows),
        dl_l30       = _dl_sum(ios_rows),
        rating       = _latest_rating(ios_rows),
        review_count = _latest_reviews(ios_rows),
        crash_rate   = _crash_rate_avg(ios_rows),
        spark        = _sparkline_series(ios_rows),
    )
    android_kpis = dict(
        dl_yesterday = _dl_yesterday(android_rows),
        dl_l7        = _dl_l7(android_rows),
        dl_l30       = _dl_sum(android_rows),
        rating       = _latest_rating(android_rows),
        review_count = _latest_reviews(android_rows),
        crash_rate   = _crash_rate_avg(android_rows),
        spark        = _sparkline_series(android_rows),
    )

    total_dl_l30 = (
        (ios_kpis["dl_l30"] or 0) + (android_kpis["dl_l30"] or 0)
        if ios_kpis["dl_l30"] is not None or android_kpis["dl_l30"] is not None
        else None
    )

    ios_configured     = all(os.environ.get(k) for k in (
        "ASC_KEY_P8", "ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_VENDOR_NO"))
    android_configured = all(os.environ.get(k) for k in (
        "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "GOOGLE_PLAY_PACKAGE_NAME"))

    has_data      = bool(rows)
    last_refreshed = (
        max((r.fetched_at for r in rows), default=None)
        if rows else None
    )
    last_refreshed_str = (
        last_refreshed.strftime("%b %d, %Y at %H:%M UTC") if last_refreshed else "Never"
    )

    return render_template(
        "admin_app_store.html",
        active_tab          = "app_store",
        now                 = _fmt_admin_now(),
        ios_kpis            = ios_kpis,
        android_kpis        = android_kpis,
        total_dl_l30        = total_dl_l30,
        has_data            = has_data,
        ios_configured      = ios_configured,
        android_configured  = android_configured,
        last_refreshed_str  = last_refreshed_str,
    )


@app.route("/admin/app-store/refresh", methods=["POST"])
@login_required
@admin_required
def admin_app_store_refresh():
    """Pull the latest metrics from Apple / Google and upsert into AppStoreMetric.

    - Checks for credentials before attempting each platform.
    - Fails gracefully per-platform; one failure does not abort the other.
    - Returns a flash message + redirect back to /admin/app-store.
    - Idempotent: re-running overwrites (upserts) the same (platform, date) rows.
    """
    validate_csrf_request()
    from models import AppStoreMetric
    from datetime import datetime as _dt

    messages = []
    errors   = []

    # ── iOS / App Store Connect ───────────────────────────────────────────────
    ios_configured = all(os.environ.get(k) for k in (
        "ASC_KEY_P8", "ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_VENDOR_NO"))

    if ios_configured:
        try:
            from services.app_store_client import fetch_daily_downloads, fetch_app_rating

            dl_rows = fetch_daily_downloads(days_back=30)
            rating  = fetch_app_rating()

            upserted = 0
            for row in dl_rows:
                existing = AppStoreMetric.query.filter_by(
                    platform="ios", report_date=row["report_date"]
                ).first()
                if existing:
                    existing.downloads  = row["downloads"]
                    existing.fetched_at = _dt.utcnow()
                else:
                    db.session.add(AppStoreMetric(
                        platform    = "ios",
                        report_date = row["report_date"],
                        downloads   = row["downloads"],
                        fetched_at  = _dt.utcnow(),
                    ))
                upserted += 1

            if rating:
                latest = AppStoreMetric.query.filter_by(platform="ios").order_by(
                    AppStoreMetric.report_date.desc()
                ).first()
                if latest:
                    latest.rating       = rating["rating"]
                    latest.review_count = rating["review_count"]
                    latest.fetched_at   = _dt.utcnow()

            db.session.commit()
            messages.append(f"iOS: {upserted} day(s) upserted.")
        except Exception as exc:
            db.session.rollback()
            errors.append(f"iOS fetch failed: {exc}")
    else:
        messages.append("iOS: skipped (ASC credentials not configured).")

    # ── Android / Google Play ─────────────────────────────────────────────────
    android_configured = all(os.environ.get(k) for k in (
        "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "GOOGLE_PLAY_PACKAGE_NAME"))

    if android_configured:
        try:
            from services.play_store_client import fetch_daily_installs, fetch_daily_crashes

            install_rows = fetch_daily_installs(days_back=30)
            crash_rows   = fetch_daily_crashes(days_back=30)

            crash_by_date = {r["report_date"]: r["crashes"] for r in crash_rows}

            upserted = 0
            for row in install_rows:
                existing = AppStoreMetric.query.filter_by(
                    platform="android", report_date=row["report_date"]
                ).first()
                crashes_val = crash_by_date.get(row["report_date"])
                if existing:
                    existing.downloads  = row["downloads"]
                    existing.crashes    = crashes_val
                    existing.fetched_at = _dt.utcnow()
                else:
                    db.session.add(AppStoreMetric(
                        platform    = "android",
                        report_date = row["report_date"],
                        downloads   = row["downloads"],
                        crashes     = crashes_val,
                        fetched_at  = _dt.utcnow(),
                    ))
                upserted += 1

            db.session.commit()
            messages.append(f"Android: {upserted} day(s) upserted.")
        except Exception as exc:
            db.session.rollback()
            errors.append(f"Android fetch failed: {exc}")
    else:
        messages.append("Android: skipped (Play credentials not configured).")

    # ── Flash result ─────────────────────────────────────────────────────────
    if errors:
        flash("Refresh completed with errors — " + " | ".join(messages + errors), "error")
    else:
        flash("Refresh complete — " + " | ".join(messages), "success")

    return redirect(url_for("admin_app_store"))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=database_configuration.debug_enabled,
        use_reloader=database_configuration.debug_enabled,
    )
