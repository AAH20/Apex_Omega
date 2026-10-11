# Unimplemented / phantom tests

These files were written against a module layout that **does not exist in this repo**.
Nothing under `src/` references any symbol they import, so they are not evidence of a
missing feature — they are tests for an API that was never built here.

They are quarantined (not deleted) so the intended API surface is preserved as a record,
and renamed to `phantom_*.py` so `python_files = ["test_*.py"]` no longer collects them.
`pytest --ignore=tests/_unimplemented` is also set in `pyproject.toml` as a second guard.

**Do not stub these.** A stub would turn a loud collection error into a green run that
tests nothing. Either implement the module for real, or rewrite the test against the
equivalent module that actually exists.

| Quarantined file | Imports (missing) | Real equivalent in this repo |
|---|---|---|
| `phantom_ekf.py` | `src.fusion.ekf` (`ExtendedKalmanFilter`, `BearingOnlyEKF`, `RangeBearingEKF`) | none — no `src/fusion/` package exists |
| `phantom_track.py` | `src.fusion.track` | none — no `src/fusion/` package exists |
| `phantom_f2t2ea.py` | `src.c2.f2t2ea` | none — no `src/c2/` package exists |
| `phantom_fix_integration.py` | `fix_parser` (via `sys.path.insert` to `src/fix_harness`) | `src/fix/` — `heartbeat.py`, `message_router.py`, `reject.py`, `resend.py`, `session/`, `session_store.py` |
| `phantom_risk.py` | `risk.risk_monitor`, `risk.risk_appetite`, `risk.risk_budgeting`, `risk.stress_testing`, `risk.liquidity_risk`, `risk.risk_attribution` | `src/risk/` — `audit.py`, `kill_switch.py`, `position_limit.py`, `pre_trade.py`, `stress.py` |

To restore one: implement the missing module (or rewrite the imports against the real
module), move the file back under `tests/`, and rename it to `test_*.py`.
