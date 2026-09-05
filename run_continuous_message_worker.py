"""Reserved VM entry point for the continuous messaging worker only."""

import json
import sys
import threading


def main():
    engine = None
    sessions = None
    previous_handlers = {}
    try:
        from services.message_worker_runtime import (
            create_worker_resources,
            install_signal_handlers,
            load_worker_settings,
            restore_signal_handlers,
            run_continuous,
        )

        settings = load_worker_settings()
        engine, sessions = create_worker_resources(settings)
        stop_event = threading.Event()
        previous_handlers = install_signal_handlers(stop_event)
        callbacks = None
        if settings.mode == "normal":
            from services.message_dispatch import (
                message_outbox_event_log_callback,
                message_outbox_provider_callback,
                message_outbox_safety_callback,
            )
            callbacks = (
                message_outbox_safety_callback,
                message_outbox_provider_callback,
                message_outbox_event_log_callback,
            )
        run_continuous(
            settings,
            sessions,
            stop_event=stop_event,
            delivery_callbacks=callbacks,
        )
        sessions.remove()
        return 0
    except Exception as exc:
        category = getattr(exc, "category", "worker_initialization_failed")
        print(json.dumps({"error": category}, sort_keys=True))
        return 1
    finally:
        if previous_handlers:
            restore_signal_handlers(previous_handlers)
        if sessions is not None:
            sessions.remove()
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())