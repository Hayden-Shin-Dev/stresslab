#!/usr/bin/env bash
set -euo pipefail
source ingestion/kiwoom/azure-env.sh
# Add these secret names in the collector app portal before running this command.
az containerapp update -g "$SL_RG" -n "$SL_APP" --set-env-vars MODE=stream KIWOOM_APP_KEY=secretref:kiwoom-app-key KIWOOM_SECRET_KEY=secretref:kiwoom-secret-key --output none
az containerapp logs show -g "$SL_RG" -n "$SL_APP" --type console --tail 30 --follow
