# WHAT IF Azure Static Web App

`site/` is the single source tree for the deployed static site. It includes the Google login, holdings, stress-analysis, live market-data, and live-news diagnostic pages with their route/auth configuration.

`deploy-manifest.json` records the required page and runtime files. `deploy.py` copies `site/` as one deployable unit and verifies that configured rewrite targets exist before deployment.

The `/news-monitor` page reads each signed-in user's debate events and displays `web_news` citations from `debate.evidence_ready`. News collection runs during the debate evidence step; it is not a continuous standalone news feed.

Build locally:

```sh
python3 apps/web/quote-monitor/deploy.py --build-only /tmp/whatif-site
```

The output directory is the Azure Static Web Apps package root. `README.md`, `deploy.py`, and `deploy-manifest.json` remain outside `site/` and are not published.
