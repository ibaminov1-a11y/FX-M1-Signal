# R7.3 Windows startup and installer audit

Baseline: R7.2 `f3a6ba35dc551f2ae8ac1ad8025b4e19c1d52cd0`. Audit date: 2026-10-05.

## Reproduced defects and repairs

| Observed failure before repair | R7.3 behavior and regression |
| --- | --- |
| The updater replaced Colorama before checking the running-process lock or active campaigns. Both regressions changed real fixture files before rejecting the update. | One runtime lock covers campaign checks, environment preparation, dependency repair, program replacement and postflight. `test_running_bridge_blocks_before_dependency_mutation`, `test_live_campaign_blocks_before_dependency_mutation`, `test_postflight_failure_restores_program_while_install_lock_is_held`. |
| Missing `.venv` made postflight silently succeed. Fresh installations copied a program without provisioning Flask/MT5. | A fresh target gets a private environment and missing dependencies; a missing/broken existing interpreter blocks replacement. Wrong architecture receives a specific error. Tests cover absent/broken Python, 32-bit Python, new environment creation, failed dependency downloads and retry. |
| The installer copied additional files inside a checksummed directory without verifying them. | Exact file-set verification applies to both program and bundled dependency payloads. Invalid dependencies are rejected before creating an environment; a missing R7.3 startup helper is rejected before repairs. |
| Errors after program copy, including failure to write rollback metadata, could leave the new program installed despite failure. | Program backup restoration covers copy, metadata and postflight failures. Original trading state is never replaced. |
| The launcher had no durable preflight result, lost the server exit status after `pause`, and had no local connection diagnosis. | A stdlib helper reports sanitized import status, retains exit codes and appends a rotating startup log. `--diagnose` reads local network/process facts without opening the database or token, or calling a trading endpoint. Native CMD coverage uses a Unicode/spaced/`!` path. |
| Documentation named nonexistent `INSTALL_R7.cmd` and contradicted the removal of `_vendor`. | R7.3 documentation names exact install/rollback commands, explains existing/new environments and lists safe diagnostic commands and log locations. |

The initial four regressions failed against unchanged R7.2. Additional failures were observed before their corresponding fixes. The tests exercise real files, locks, SQLite snapshots, processes and socket listeners; external interpreter/pip subprocesses are simulated only for platform/error branches that cannot run on Linux. No broker credentials are used and no orders are sent.

## Verification and native release gate

Focused tests live in `tests/event_core/test_r73_installer.py`; existing lock/WAL/rollback coverage remains in `test_r7_installer.py`. Packaging rejects absent Windows R7.3 evidence and absent/malformed PNG evidence in `test_r73_packaging.py`.

An intermediate integrated Linux discovery passed **406 tests in 24.565 seconds**, with only the native CMD test skipped. Subsequent focused tests additionally verified full-disk rollback metadata recovery, early dependency rejection and packaging gates. The release's `python-tests.log` is the authoritative final integrated count and result after all concurrent work.

`tools/windows_r7_gate.py` must run on native Windows. It executes the Windows-compatible regression suite, restores a mixed old installation with broken Colorama, invokes the actual generated CMD wrapper from a Unicode/spaced/`!` path, creates a genuinely private fresh `.venv` with real Flask/MetaTrader5 imports, invokes the installed launcher with `--check`, and verifies read-only `--diagnose` preserves state bytes and excludes the fixture token. It records the exact Git commit and actual test count in `WINDOWS_RESULT.json`.

The Linux audit did not execute native Windows or a broker terminal. The release packager refuses to ship unless `fresh_environment`, `installed_launcher_check` and `read_only_diagnostics` are true in successful native evidence for the same commit. Android R7.3 classes, all 23 chart PNGs (nine public timeframes; M10 remains legacy engine compatibility only) and the unchanged signing certificate are separately required. `physical_mt5` remains `NOT_TESTED`.

## Preserved data and remaining operational limits

The installer never deletes/replaces campaign databases, WAL/SHM, pairing tokens or broker-clock files. It keeps an existing `.venv`; bundled Colorama is repaired and missing packages may be installed inside it. Pip requires network access when dependencies are absent. Raw pip output is deliberately omitted from saved logs because package-index URLs may contain credentials. Program backups remain available; dependency package changes are not a full transactional snapshot of the entire environment.

Diagnosis establishes local listener/process facts only. It cannot prove phone Wi-Fi, VPN or firewall reachability, nor broker availability. Startup logs contain structured status and exit codes; the server inherits the console directly so its displayed pairing key is never copied into the startup log. Runtime log redaction is implemented and verified separately in the server audit.

Sources: `mt5_bridge/START_BRIDGE_V10_0.bat`, `mt5_bridge/bridge_startup.py`, `tools/r7_updater.py`, `tools/windows_r7_gate.py`, `tools/package_r7.py`. The updater and package share one generated Windows wrapper. BAT files intentionally use CRLF; whitespace verification uses `git -c core.whitespace=cr-at-eol diff --check`.
