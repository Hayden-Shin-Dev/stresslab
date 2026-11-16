# WHAT IF Azure Static Web App

`site/` is the single source tree for the deployed static site. It includes the 9 main WHAT IF/login files, the 77 referenced inline images, the 2차 인트로, live-data pages, route/auth configuration, and video asset.

`deploy-manifest.json` records the nine primary files and required runtime paths. `deploy.py` copies `site/` as one deployable unit and verifies rewrite targets and image references before deployment.

Build locally:

```sh
python3 apps/web/quote-monitor/deploy.py --build-only /tmp/whatif-site
```

The output directory is the Azure Static Web Apps package root. `README.md`, `deploy.py`, and `deploy-manifest.json` remain outside `site/` and are not published.
