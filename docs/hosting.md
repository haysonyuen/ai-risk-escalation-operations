# Hosting a public demo

The app can be hosted so people can try it in a browser without installing anything. The recommended option is **Streamlit Community Cloud** (free; it deploys straight from this GitHub repo).

## Public demo mode

Set `RISKOPS_PUBLIC_DEMO = "1"` when hosting. In this mode:

- every visitor gets a **private, freshly seeded copy** of the demo database, so visitors never see or overwrite each other's changes;
- a sidebar notice explains this and asks visitors not to enter real personal data;
- session databases idle for 12 hours are deleted;
- the live-model option is removed from the menu, so no API key can be used by visitors even if one is configured.

Without the flag (the default, e.g. on your own laptop), the app uses one persistent local database at `data/riskops.db`.

## Streamlit Community Cloud: step by step

1. Sign in at https://share.streamlit.io with your GitHub account and allow it to access this repository.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Choose repository `haysonyuen/ai-risk-escalation-operations`, branch `main`, main file path `app/streamlit_app.py`.
4. Optional: pick a custom subdomain, e.g. `ai-risk-escalation-ops`.
5. Open **Advanced settings**: set Python to 3.11 or 3.12, and in **Secrets** paste:
   ```toml
   RISKOPS_PUBLIC_DEMO = "1"
   ```
   Do **not** add an `ANTHROPIC_API_KEY` to a public demo: visitors could use your credits. The offline mode needs no key.
6. Click **Deploy**. The first build takes a few minutes. You get a URL like `https://<your-subdomain>.streamlit.app`.

Updates: pushing to `main` redeploys automatically.

Notes:
- Free apps go to sleep after a period without visitors; the first visitor then waits about a minute for it to wake up.
- The hosted demo uses only synthetic data and simulated actions, like the local version.
