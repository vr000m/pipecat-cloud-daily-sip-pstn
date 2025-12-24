#!/bin/bash

# Deploy bot-eu to Pipecat Cloud (EU or US region)

echo "Select deployment region:"
select region in "eu" "us"; do
  case $region in
    eu)
      TOML_FILE="pcc-deploy-eu.toml"
      break
      ;;
    us)
      TOML_FILE="pcc-deploy-us.toml"
      break
      ;;
    *)
      echo "Invalid selection. Please choose 1 for EU or 2 for US."
      ;;
  esac
done

# Check if the selected toml file exists
if [ ! -f "$TOML_FILE" ]; then
  echo "Error: $TOML_FILE not found."
  exit 1
fi

# Copy region-specific config to pcc-deploy.toml
cp "$TOML_FILE" pcc-deploy.toml
echo "Copied $TOML_FILE to pcc-deploy.toml"

# Extract agent name from toml file
AGENT_NAME=$(grep 'agent_name' pcc-deploy.toml | cut -d'"' -f2)
echo "Deploying agent: $AGENT_NAME"

# Check if login is needed
if [ "$1" != "--skip-login" ]; then
  pipecat cloud auth login
  docker login
fi

# Build and push Docker image, then deploy
# Note: pipecat cloud docker build-push reads from pcc-deploy.toml to determine
# registry settings, image names, and versions automatically
pipecat cloud docker build-push
pipecat cloud deploy

# Show status for the deployed agent
pipecat cloud agent status "$AGENT_NAME"
pipecat cloud agent deployments "$AGENT_NAME"
