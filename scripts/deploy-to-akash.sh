#!/usr/bin/env bash
set -euo pipefail

MANIFEST=${1:-akash/deploy.yaml}
DSEQ=${DSEQ:-$(date +%s)}
PROVIDER=${PROVIDER:-}

if [[ ! -f "$MANIFEST" ]]; then
  echo "Manifest $MANIFEST not found. Run scripts/build-for-akash.sh first." >&2
  exit 1
fi

echo "Using manifest: $MANIFEST"
echo "Deployment sequence: $DSEQ"

if [[ -z "$PROVIDER" ]]; then
  echo "PROVIDER environment variable not set. Listing providers..."
  akash provider list
  echo "Set PROVIDER=akash1... to target a specific provider."
  exit 0
fi

echo "Creating deployment on provider $PROVIDER"
akash tx deployment create "$MANIFEST" --from wallet --node $AKASH_NODE --gas auto --gas-adjustment 1.3 --chain-id $AKASH_CHAIN_ID --yes --dseq $DSEQ
echo "Creating lease"
akash tx market lease create --from wallet --node $AKASH_NODE --chain-id $AKASH_CHAIN_ID --yes --dseq $DSEQ --provider "$PROVIDER" --gseq 1 --oseq 1
echo "Query lease status"
akash query market lease get --dseq $DSEQ --provider "$PROVIDER" --gseq 1 --oseq 1
echo "To update: akash tx deployment update $MANIFEST --dseq $DSEQ ..."
