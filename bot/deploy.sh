#!/bin/bash

# Extract version from toml file
VERSION=$(grep 'image' pcc-deploy.toml | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+')
IMAGE_NAME=$(grep 'image' pcc-deploy.toml | cut -d'"' -f2 | cut -d':' -f1)
BASE_NAME=$(basename "$IMAGE_NAME")
AGENT_NAME=$(grep 'agent_name' pcc-deploy.toml | cut -d'"' -f2)

# Check if bot.py exists or fallback to bot_*.py
if [ ! -f "bot.py" ]; then
  echo "bot.py not found."

  bot_files=(bot_*.py)
  if [ ${#bot_files[@]} -eq 0 ]; then
    echo "No alternative bot_*.py files found."
    exit 1
  fi

  echo "Available bot files:"
  select file in "${bot_files[@]}"; do
    if [[ -n "$file" ]]; then
      echo "You selected $file"
      cp "$file" bot.py
      echo "$file copied as bot.py"
      break
    else
      echo "Invalid selection."
    fi
  done
else
  echo "bot.py already exists."
fi

# Check if login is needed
if [ "$1" != "--skip-login" ]; then
  pcc auth login
  docker login
fi

docker build --platform=linux/arm64 --no-cache -t "$BASE_NAME:latest" .
docker tag "$BASE_NAME:latest" "$IMAGE_NAME:$VERSION"
docker push "$IMAGE_NAME:$VERSION"
pcc deploy
pcc agent deployments "$AGENT_NAME"
pcc agent status "$AGENT_NAME"