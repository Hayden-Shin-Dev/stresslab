# WHAT IF Azure Static Web App

`site/` is the single source tree for the deployed static site. It includes the Google login, holdings, stress-analysis, live market-data, and live-news diagnostic pages with their route/auth configuration.

`deploy-manifest.json` records the required page and runtime files. `deploy.py` copies `site/` as one deployable unit and verifies that configured rewrite targets exist before deployment.

The `/news-monitor` page reads each signed-in user's debate events and displays `web_news` citations from `debate.evidence_ready`. News collection runs during the debate evidence step; it is not a continuous standalone news feed.

The temporary `/debate-monitor` page lists the signed-in user's debates and checks event replay plus the debate WebSocket connection. It does not start a debate.

The `/workflow-demo` page uses the authenticated same-origin APIs for live quotes, holdings, stress analysis, and debate questions. News becomes available from debate evidence after a run starts; there is no standalone continuous news endpoint in this app.

Open `/workflow-demo?demo=1` for a local functional demo without API calls. It simulates changing quote values, adds clearly labeled sample headlines every 12 seconds, accepts a holding amount and text documents, calculates an illustrative stress result, and returns a deterministic sample answer that includes the selected data. Those sample values and answers are not live market/news data or model output.

Build locally:

```sh
python3 apps/web/quote-monitor/deploy.py --build-only /tmp/whatif-site
```

The output directory is the Azure Static Web Apps package root. `README.md`, `deploy.py`, and `deploy-manifest.json` remain outside `site/` and are not published.
