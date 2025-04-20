#!/bin/bash

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
      # Copy the bot file
      cp "$file" bot.py
      echo "$file copied as bot.py"
      
      # Find and copy the associated toml file
      toml_file=$(grep "^$file" deploy_map.txt | cut -d' ' -f2)
      if [ -n "$toml_file" ]; then
        cp "$toml_file" pcc-deploy.toml
        echo "$toml_file copied as pcc-deploy.toml"
      else
        echo "Warning: No associated toml file found for $file in deploy_map.txt"
      fi
      break
    else
      echo "Invalid selection."
    fi
  done
else
  echo "bot.py already exists."
fi

# Extract version from toml file
VERSION=$(grep 'image' pcc-deploy.toml | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+')
IMAGE_NAME=$(grep 'image' pcc-deploy.toml | cut -d'"' -f2 | cut -d':' -f1)
BASE_NAME=$(basename "$IMAGE_NAME")
AGENT_NAME=$(grep 'agent_name' pcc-deploy.toml | cut -d'"' -f2)

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