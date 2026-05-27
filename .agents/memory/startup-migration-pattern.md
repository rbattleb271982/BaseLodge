---
name: Startup migration pattern
description: How BaseLodge runs safe schema migrations at server startup — critical details to avoid breakage.
---

## Rule
Always use `db.text(...)` inside startup migration functions, never bare `text(...)`.

**Why:** `text` from sqlalchemy is not imported at the module top level in app.py. `db.text` is available because `db` (the SQLAlchemy instance) is always in scope. Using bare `text()` causes `NameError: name 'text' is not defined` silently at startup.

## Pattern
```python
def run_X_migration():
    try:
        with app.app_context():
            with db.engine.connect() as conn:
                trans = conn.begin()
                try:
                    conn.execute(db.text("CREATE TABLE IF NOT EXISTS ..."))
                    trans.commit()
                    print("X_migration: table ready.")
                except Exception as inner_e:
                    trans.rollback()
                    print(f"X_migration inner error (rolled back): {inner_e}")
                finally:
                    conn.close()
    except Exception as e:
        print(f"X_migration: skipped ({e})")

run_X_migration()
```

## How to apply
- Define function, then call it immediately on the next non-blank line.
- Always call immediately after definition — no intervening code.
- Place new migrations after `run_pass_system_expansion_migration()` at ~line 1750.
