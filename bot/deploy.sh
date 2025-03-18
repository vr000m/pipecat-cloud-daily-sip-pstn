#!/bin/bash

# Extract version from toml file
VERSION=$(grep 'image' pcc-deploy.toml | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+')
IMAGE_NAME=$(grep 'image' pcc-deploy.toml | cut -d'"' -f2 | cut -d':' -f1)
BASE_NAME=$(basename "$IMAGE_NAME")
AGENT_NAME=$(grep 'agent_name' pcc-deploy.toml | cut -d'"' -f2)

# Check if login is needed
if [ "$1" != "--skip-login" ]; then
  docker login
fi

docker build --platform=linux/arm64 -t "$BASE_NAME:latest" .
docker tag "$BASE_NAME:latest" "$IMAGE_NAME:$VERSION"
docker push "$IMAGE_NAME:$VERSION"
pcc deploy
pcc agent deployments "$AGENT_NAME"
pcc agent status "$AGENT_NAME"
