# Packaged catalog verification — 2026-10-09

The unsigned macOS arm64 app bundle was rebuilt with the current frontend and Python 3.14.7/PyInstaller backend. This is a local package check, not a new public release, notarized build, or DMG/ZIP installer.

`npm --prefix frontend run test:package:catalog` launched the actual packaged Electron shell against its bundled backend binary, using a fresh disposable database and profile. The smoke launches the bundled backend separately (`START_BACKEND=false`) so both test processes can be cleaned up reliably; it does not re-test the shell's owned-backend startup/shutdown path. Agent execution is disabled with `/usr/bin/false`. No real chats, evaluation history, or model calls were touched.

Verified in the packaged renderer:

- All 601 workspaces and 601 chats loaded; newest tied-activity session `#601` selected initially.
- The oldest chat `#001` was reachable by scrolling and selected through mouse input.
- Both sidebar sections scroll independently. Workspace viewport: 274 px, content: 24,638 px. Session viewport: 339 px, content: 33,052 px.
- Screenshot inspection confirms the Sessions section and collapse footer remain visible, with workspace `0601` and chat `0001` selected.

The first run exposed unbounded sidebar lists that pushed Sessions out of view. The fix constrains the workspace list to at most 35% of sidebar height, gives sessions the remaining space, and keeps headings/footer outside the scroll regions. A separate Electron fix scans bounded workspace pages before authorizing file reveal; two new unit tests cover registration beyond the first 500 and malformed/error responses. Actual Finder file reveal was not invoked.

Evidence is retained locally in `/var/folders/k_/h_dcfnks7wj905cqj0qcz05c0000gn/T/workbench-packaged-catalog-gmhu3d/` (`report.json`, `catalog.png`, disposable fixture DB/profile). Temporary evidence may be removed by the OS. The smoke prints the directory for each new run and stops its app/backend processes when finished. Remote debugging is enabled only for the disposable test run, not normal startup.

Additional checks pass: 168 backend tests; 41 frontend/Electron regression tests; frontend build/lint/contract checks; backend lint/format/generated-contract drift checks; hidden Electron UI/IPC/CSP/navigation security smoke. Hosted CI and a new installer were not run in this batch.

This record concerns catalog layout and packaging, not benchmark sensitivity or model performance. Benchmark selection and source-build statistics subsequently changed; see [current methodology](evals-benchmark-methodology.md). Rerun package checks after rebuilding the latest source.
