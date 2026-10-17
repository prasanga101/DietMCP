# DietMCP

A personal diet and activity tracker: ChatGPT tools save dated logs to Supabase, calculate daily energy balance, and generate a visual PDF that is emailed weekly.

## Features

- Food/activity logging, corrections with stable UUIDs, deletion and dated summaries.
- Intake, protein, additional exercise burn, estimated TDEE, daily deficit, weekly deficit and estimated weight-loss equivalent.
- Two-page PDF with daily intake/TDEE bars, cumulative deficit chart and daily detail table.
- Age calculated from a privately configured birth date. Height, current weight, sex and target remain private.
- Owner-restricted GitHub OAuth for the remote MCP; server-side Supabase access requires no repeated database login.

## Free hosting design

- **Render Free** hosts the MCP at `/mcp` over HTTPS.
- **Supabase** stores fitness logs, encrypted OAuth state and the delivery ledger.
- **GitHub Actions** runs the weekly PDF/email job independently of Render.
- **Resend** sends the PDF attachment over HTTPS; configure an approved sender and stay within your account's free allowance.

No payment card or paid Render disk is used by the supplied blueprint. Free tiers have quotas and availability limits. Render sleeps after 15 minutes of inactivity and can take about one minute to wake; reconnect/retry if a ChatGPT call times out during startup. OAuth state persists in Supabase across restarts. Scheduled GitHub jobs may run late, and public-repository schedules can be disabled after 60 days without repository activity. Check the Actions page if weekly emails stop.

Sources: [Render Free](https://render.com/docs/free), [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Private configuration

Only `.env.example` belongs in Git. Keep your actual `.env`, reports, sessions, database files and keys private.

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL` | Project HTTPS URL |
| `SUPABASE_SERVER_KEY` | Server-only secret key or legacy service-role key |
| `OWNER_USER_ID` | UUID of your existing Supabase Auth user |
| `STATE_ENCRYPTION_KEY` | Stable Fernet key for encrypted OAuth and delivery state |
| `PUBLIC_URL` | Assigned Render HTTPS origin |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | Your GitHub OAuth app credentials |
| `GITHUB_OWNER_ID` | Numeric GitHub user ID allowed to connect |
| `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_TO` | Private email sender configuration |
| `BIRTH_DATE`, `HEIGHT_CM`, `WEIGHT_KG`, `TARGET_WEIGHT_KG`, `SEX` | Private profile inputs |

Default timezone is Asia/Kathmandu. The workflow is scheduled Friday at 10:15 UTC, approximately 16:00 Nepal time. Reports cover the previous Friday through Thursday, excluding the unfinished delivery day. Age is computed for each log date. The baseline uses Mifflin-St Jeor resting expenditure x 1.2, excluding additional logged exercise; optional `BASELINE_KCAL` overrides it locally. The configured target is recorded without prescribing intake or a deadline.

## Setup

1. Run `deploy/private_state.sql` once in your Supabase SQL Editor. It creates one backend-only state table, with RLS enabled and no access for anonymous or authenticated clients. Your three fitness tables stay in place.
2. Enter private values in `.env`. Keep `STATE_ENCRYPTION_KEY` stable across local, Render and GitHub configuration; losing it makes saved state unreadable.
3. Run `uv sync`, `uv run fitness doctor`, `uv run fitness check`, `uv run fitness test`, then `uv run pytest`.
4. Create a Render Blueprint from `render.yaml`. It uses the free plan. Initially, the host can run in setup mode: `/health` reports `configuration_required`, and `/mcp` rejects calls until private configuration is complete. A live host URL does not mean the MCP is ready.
5. Add application variables in Render's Environment section. Use `/tmp/dietmcp` for `DATA_DIR`, `supabase` for `STATE_BACKEND`, and keep `WEEKLY_EMAIL_ENABLED=false` on Render. That last flag disables the in-process scheduler; GitHub supplies the schedule instead.
6. Register a GitHub OAuth app with your Render origin as Homepage and `PUBLIC_URL/auth/callback` as callback. Add its client credentials and your numeric GitHub owner ID to Render. All other GitHub identities are denied.
7. Set the same database, encryption, email and profile variables as **GitHub Actions secrets**, not ordinary public repository variables. OAuth client credentials are not needed by the email workflow. Set repository variable `WEEKLY_EMAIL_ENABLED=true` only after configuration.
8. Run **Actions → Weekly PDF email → Run workflow** for an immediate full-pipeline test. A blank start date selects the latest scheduled Friday's report period. The workflow never publishes the PDF as a public artifact or prints health records. Verify provider delivery events and your inbox.

`fitness test` uses one marked zero-calorie food record and removes it. If interrupted, remove any `CONNECTION TEST - DELETE ME` row manually. The check verifies configured owner access; it does not prove cross-user RLS isolation.

## ChatGPT and iPhone acceptance test

[Official OpenAI connection instructions](https://developers.openai.com/api/docs/guides/custom-mcp-server).

On ChatGPT web, add the HTTPS `/mcp` URL as a custom MCP plugin, choose OAuth and complete the one-time GitHub connection. Install and select the plugin in a chat. Availability depends on your ChatGPT plan/workspace and client. Hosting alone cannot guarantee native mobile support.

The required final test is to select the installed plugin in the **iPhone ChatGPT app**, log an entry there, and verify that it appears in Supabase. If the iPhone app cannot select/use the connection, that requirement is still unmet. A successful desktop test is insufficient.

## Tools and reporting rules

`get_context`, `log_food`, `log_activity`, `delete_entry`, `get_daily_summary`, `confirm_day`, `get_weekly_summary`, `generate_weekly_report`, `email_weekly_report`.

Only user-reported records should be saved. Nutrition and burn estimates must be labelled in notes. Use stable entry UUIDs for retries/corrections; a different UUID creates a distinct entry. Every edit reopens the day. Confirm both food and activity completeness only after the user's confirmation. Missing logs are unknown, not zero. Weekly totals and weight-loss equivalents require seven complete days; otherwise only a complete-day subtotal is shown.

TDEE = configured baseline + additional net exercise burn. Avoid counting baseline steps, resting burn and overlapping workouts twice. Weight-loss equivalent = weekly deficit / 7,700 kcal/kg; this is a rough energy equivalent rather than a prediction of scale weight. Positive deficit means shortfall; negative means surplus. Completed-day energy assumptions are saved so later profile edits do not rewrite history.

Formula references: [Mifflin-St Jeor](https://ajcn.nutrition.org/article/S0002-9165(23)16698-6/abstract), [NIDDK Body Weight Planner](https://www.niddk.nih.gov/health-information/weight-management/body-weight-planner).

All database operations are scoped to a fixed owner. The server key bypasses RLS and must never leave the backend. OAuth state and delivery payloads are encrypted before storage in the backend-only state table. Email retries reuse the exact payload and provider idempotency key. Uncertain sends older than 23 hours stop for manual review because provider idempotency retention is 24 hours. Keep one MCP instance and the serialized GitHub workflow. Local SQLite state and an in-process worker are optional for a persistent VPS; they are not used by the free deployment.
