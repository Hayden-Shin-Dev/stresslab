#!/usr/bin/env bash
set -euo pipefail
source ingestion/kiwoom/azure-env.sh
# Creates a dedicated identity and collector app. Does not change the existing API app.
az identity create -g "$SL_RG" -n "$SL_IDENTITY" -l koreacentral --output none
SL_ID=$(az identity show -g "$SL_RG" -n "$SL_IDENTITY" --query id -o tsv)
SL_PRINCIPAL=$(az identity show -g "$SL_RG" -n "$SL_IDENTITY" --query principalId -o tsv)
SL_CLIENT=$(az identity show -g "$SL_RG" -n "$SL_IDENTITY" --query clientId -o tsv)
SL_ACR_ID=$(az acr show -g "$SL_RG" -n "$SL_ACR" --query id -o tsv)
SL_HUB_ID=$(az eventhubs eventhub show -g "$SL_RG" --namespace-name "$SL_HUB_NS" -n "$SL_HUB" --query id -o tsv)
az role assignment create --assignee-object-id "$SL_PRINCIPAL" --assignee-principal-type ServicePrincipal --role AcrPull --scope "$SL_ACR_ID" --output none
az role assignment create --assignee-object-id "$SL_PRINCIPAL" --assignee-principal-type ServicePrincipal --role "Azure Event Hubs Data Sender" --scope "$SL_HUB_ID" --output none
az acr build --registry "$SL_ACR" --image kiwoom-collector:pilot-v1 --file ingestion/kiwoom/Dockerfile .
az containerapp create -g "$SL_RG" -n "$SL_APP" --environment "$SL_ENV" --image "$SL_IMAGE" --user-assigned "$SL_ID" --registry-server "$SL_ACR.azurecr.io" --registry-identity "$SL_ID" --revisions-mode single --min-replicas 1 --max-replicas 1 --cpu 0.25 --memory 0.5Gi --env-vars MODE=probe AZURE_CLIENT_ID="$SL_CLIENT" EVENTHUB_NAMESPACE="$SL_HUB_NS.servicebus.windows.net" EVENTHUB_NAME="$SL_HUB" SYMBOLS=005930,005380 --output none
printf 'Probe deployed. Open collector console logs to read egress_ip_observed.
'
