# Smoke Test Procedure

1. Start stack (docker compose up -d or manual).
2. Open http://localhost:8000/health -> expect 200.
3. Open dashboard http://localhost:3000.
4. Register/login.
5. Create a project with a URL you control.
6. Run an execution against a simple flow (e.g., login + dashboard view).
7. Verify status reaches COMPLETED and evidence screenshots appear.
8. Inspect worker logs for browser execution.

Expected: execution transitions CREATED -> RUNNING -> COMPLETED; evidence captured.
