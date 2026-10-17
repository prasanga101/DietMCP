# DietMCP

Tell ChatGPT what you ate and did, save dated logs in your existing Supabase tables, and receive a visual weekly PDF by email. This version replaces the repeated local login flow with a hosted, single-owner service.

## What is implemented

- Food/activity logging, corrections using a stable UUID, deletion and dated summaries.
- Fixed server-side owner UUID; model arguments cannot choose another user.
- Remote Streamable HTTP MCP at `/mcp`, protected by one-time GitHub OAuth restricted to your numeric GitHub user ID.
- Two-page PDF: intake vs TDEE bars, cumulative deficit chart, daily calorie/protein/exercise/TDEE/deficit table and calculation notes.
- Friday 16:00 Asia/Kathmandu email worker. Reporting period is the previous seven full dates (Friday through Thursday); current Friday is excluded because it is not complete at 4 PM.
- Durable delivery ledger and provider idempotency to suppress duplicate weekly mail.
- Age computed from the privately configured birth date for each log date. Height, weight, sex and optional target are configured privately; a target is not used to prescribe intake or a deadline.

## Private configuration

Preserve your existing `.env`; copy needed names from `.env.example`. Do not commit or paste it in chat.

Required for the database:

- `SUPABASE_URL`: project HTTPS URL.
- `SUPABASE_SERVER_KEY`: server-only Supabase secret key or legacy service-role key. The old publishable key is insufficient for this unattended architecture. This privileged key stays only on your server.
- `OWNER_USER_ID`: UUID of your existing user under Supabase Authentication → Users. There must be an Auth user because your tables reference auth.users. No repeated Supabase login is required.

All queries and writes are scoped to this owner. Existing RLS remains enabled. The server key bypasses RLS, so the server's owner filtering and OAuth restriction are essential. No SQL migration is required for the schema supplied in your previous conversation. Run `fitness check` to verify the actual tables.

Required for the hosted ChatGPT connection:

- `PUBLIC_URL`: your HTTPS origin, e.g. `https://diet.yourdomain.com`.
- `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`: create a GitHub OAuth app under GitHub Settings → Developer settings → OAuth Apps. Homepage is PUBLIC_URL, callback is `PUBLIC_URL/auth/callback`.
- `GITHUB_OWNER_ID`: your numeric GitHub account ID. Other accounts are rejected even after signing into GitHub.

Required for unattended email:

- `RESEND_API_KEY`: a sending key from Resend, entered privately on the host.
- `EMAIL_FROM`: a sender allowed by your Resend account, normally on a verified domain. Its testing sender has recipient restrictions; check your account.
- `EMAIL_TO=your-address@example.com`
- `REPORT_WEEKDAY=4`, `REPORT_HOUR=16`, `REPORT_MINUTE=0`, `TIMEZONE=Asia/Kathmandu`
- Set `WEEKLY_EMAIL_ENABLED=true` only when the configuration is ready.

Profile values belong in `.env` as shown in the example. The default baseline is Mifflin-St Jeor resting energy x 1.2 (a configurable sedentary assumption), excluding additional logged exercise. Optional `BASELINE_KCAL` overrides this estimate. Exercise records must contain additional net burn, with overlap/resting calories removed. Total daily step records may be stored with zero additional burn when already covered by baseline/workouts. This accounting choice is approximate; review it with real activity patterns.

## Local verification

```sh
uv sync
uv run fitness check
uv run fitness test
uv run pytest
uv run fitness report --start 2026-10-09 --output weekly-report.pdf
```

`test` inserts one marked zero-calorie food record, reads it, and removes it without changing your day-completion flags. If interrupted, remove any `CONNECTION TEST - DELETE ME` row. It verifies configured owner access, not cross-user RLS isolation.

```sh
uv run fitness send --start 2026-10-09
uv run fitness worker
```

`send` sends a real PDF once to the fixed recipient. Worker runs continuously and checks the configured local schedule once a minute. It catches up later on the same scheduled day after an outage; an outage lasting the entire day requires a manual send for that period. Keep one service instance. When WEEKLY_EMAIL_ENABLED is true, the server starts its scheduler in the same process. Do not run the standalone worker at the same time. Email provider acceptance is not proof of inbox delivery; inspect provider delivery events.

## Managed deployment on Render (selected route)

A ready-to-review `render.yaml` defines one always-on Python web service and a 1 GB persistent disk. This is a paid configuration; review Render's current price before creating it. Review the service and storage cost before activating deployment. Free Render web services sleep when idle and do not provide persistent disks, so this in-process Friday scheduler is not suitable for that tier.

1. Put the project in your own GitHub repository, excluding `.env`, `.private`, `.venv` and reports. Do not publish the project secrets.
2. In Render, create a Blueprint from that repository's `render.yaml`. Review the cost before deployment.
3. Enter the prompted private environment values in Render. For PUBLIC_URL, use the service's assigned HTTPS `.onrender.com` origin. Set the GitHub OAuth app callback to that origin plus `/auth/callback`. The GitHub OAuth connection is a one-time setup; no Supabase login tool remains.
4. Initially leave WEEKLY_EMAIL_ENABLED=false. In Render's shell run `.venv/bin/fitness check`, `.venv/bin/fitness test`, and `.venv/bin/fitness send` to verify the live pipeline.
5. Set WEEKLY_EMAIL_ENABLED=true and redeploy. The same always-on service runs the weekly scheduler; it continues with your laptop off. Keep one instance and retain the attached disk.
6. Connect `https://YOUR_SERVICE.onrender.com/mcp` in ChatGPT and verify from your iPhone. This client compatibility check remains outstanding.

Hosting references: https://render.com/docs/blueprint-spec, https://render.com/docs/disks, https://render.com/docs/free

## Alternative deployment on a Linux VPS

No hosting account or domain has been supplied yet; this project is prepared for deployment but is not online.

1. Create a Linux VPS with Docker Compose, and point a DNS hostname at it. Open inbound ports 80 and 443.
2. Copy this project to the host, excluding `.env`, `.venv`, `.private` and local reports. Create the private `.env` directly on the host and set `DATA_DIR=/data`, `FASTMCP_HOME=/data/fastmcp`, `DIET_DOMAIN=your.hostname` and `PUBLIC_URL=https://your.hostname`.
3. `docker compose up -d --build` starts the MCP and HTTPS proxy.
4. `docker compose exec mcp /app/.venv/bin/fitness check` then `... fitness test` verifies the live database.
5. `docker compose exec mcp /app/.venv/bin/fitness send` tests a real report delivery.
6. After enabling email in `.env`, `docker compose up -d` recreates the service and starts its Friday scheduler.

Volumes persist OAuth registrations and delivery history. Preserve and back them up; deleting them loses connection/deduplication history. Do not scale this single-owner deployment to multiple replicas without replacing local storage and mutation locking.

## Connect to ChatGPT, then test on iPhone

Current OpenAI connection instructions: https://developers.openai.com/api/docs/guides/custom-mcp-server

On ChatGPT web, open Plugins, add a custom MCP server with URL `https://your.hostname/mcp`, choose OAuth and complete the one-time GitHub connection. Install the plugin, then select it with `@` in a chat. Availability depends on your plan/workspace and client. Older custom-app documentation describes web-only access; do not assume the iPhone app supports your personal connection until tested. Published directory plugins and private custom connections have different availability. Hosting alone cannot change client support.

Try: “Use DietMCP to log two eggs for breakfast today. Ask about portion uncertainty if needed.” Confirm the tool succeeds, then ask for today's summary and verify the database row. Repeat from the iPhone app using the same account. If the installed plugin is not selectable there, use ChatGPT web as the interim route; native iPhone support is still an open requirement.

## Daily reporting rules

Nutrition and burn may be estimates; label assumptions in notes. Never claim a save before tool success. Reuse entry UUIDs for retries or corrections so they do not become duplicate meals. Ask before marking a whole day complete. Any food/activity edit reopens the day. Zero food/exercise is allowed only after explicit confirmation; missing calories remain unknown. Weekly totals and weight-loss equivalents require all seven days complete; partial weeks show the subtotal for confirmed days without extrapolation.

At confirmation, calorie assumptions are stored in calculation_notes so later weight/profile changes do not rewrite previous completed days. The configured weight is a current input; no scale-weight history or trend is inferred. Update it when appropriate and reconfirm corrected days.

Weight-loss equivalent uses a rough 7,700 kcal/kg conversion, not a prediction of scale change. Formula sources: https://ajcn.nutrition.org/article/S0002-9165(23)16698-6/abstract and https://www.niddk.nih.gov/health-information/weight-management/body-weight-planner

Delivery retries reuse identical payloads and a provider idempotency key. A pending send older than 23 hours is blocked for manual review because the provider's key retention is 24 hours. Never delete the ledger just to retry an uncertain delivery.
