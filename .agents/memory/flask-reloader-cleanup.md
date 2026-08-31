---
name: Flask debug reloader cleanup
description: Temporary Flask debug runs can leave a reloader child process behind after the parent is stopped.
---

When diagnosing a Flask workflow that reports port 5000 is already in use, check for a leftover `python app.py` debug-reloader child from a temporary smoke server before attributing the failure to application startup or the database.

**Why:** Flask debug mode forks/restarts a child process, and stopping the shell task that launched the parent may not remove that child. The managed workflow then fails immediately with `Address already in use`.

**How to apply:** Inspect the process owner and command first, terminate only the known temporary Flask process, verify port 5000 is clear, and then continue diagnosis without changing application or database state.