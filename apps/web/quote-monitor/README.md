# WHAT IF Azure Static Web App

`site/` is the single source tree for the deployed static site. The public UI consists of Google login (`login.html`), real-time data (`quote-monitor/index.html`), and holdings (`holdings.html`). The data pages keep their authenticated `/api` and WebSocket connections.

`deploy-manifest.json` records these entry points and their runtime scripts. `deploy.py` copies `site/` as one deployable unit and verifies rewrite targets before deployment.

Build locally:

```sh
python3 apps/web/quote-monitor/deploy.py --build-only /tmp/whatif-site
```

The output directory is the Azure Static Web Apps package root. `README.md`, `deploy.py`, and `deploy-manifest.json` remain outside `site/` and are not published.
