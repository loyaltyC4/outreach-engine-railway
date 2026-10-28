# outreach-engine

Automated cold-email engine. One cron tick = guards -> read inbound -> refill lead pool -> send within caps -> daily digest.
Standard library only. Campaign specifics (who qualifies, lead harvesting, email copy) live in one file per campaign (`engine/acd.py`).

## Where it runs
Railway account `hello@tenderwin`, project `outreach` (3541d8e7-aaec-46b8-ab1a-5a03eee845d9), environment production.
Service `acd-sender` (80f02a60-...): cron `*/30 * * * *`, volume `/data`. Token: `RAILWAY_TOKEN_OUTREACH` in `~/AutoClaw/Shared/.secrets/keys.env`.

## Operate
- Deploy: `RAILWAY_API_TOKEN=$RAILWAY_TOKEN_OUTREACH RW_PROJECT=... RW_ENV=... RW_SERVICE=... ./deploy.sh`
- Pause: set `KILL_SWITCH=1` on the service. Dry run: `DRY_RUN=1`.
- Change copy: edit `COPY` in `engine/acd.py`, redeploy.
- Local test: `DATA_DIR=$PWD/seed/state DRY_RUN=1 IGNORE_WINDOW=1 ./localenv.sh python3 engine/run.py acd`
- The engine never auto-replies to people. Real replies are emailed to OWNER_EMAIL; removes/replies suppress the whole organisation.
- Guards: spam complaint about our mail pauses sending; >6% bounces over 48h pauses sending; caps count every send from the inbox, any tool.
- `seed/` is private data (lead backlog + starting state) and is gitignored on purpose.
