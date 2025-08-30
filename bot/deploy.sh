#!/bin/bash

# Check if bot.py and pcc-deploy.toml exist first
if [ -f "bot.py" ] && [ -f "pcc-deploy.toml" ]; then
    echo "Found existing deployment files."
    read -p "Would you like to deploy these files? (y/N) " deploy_existing
    if [[ "$deploy_existing" =~ ^[Yy]$ ]]; then
        echo "Proceeding with existing files..."
    else
        # Only check for deploy_map.txt if we're not using existing files
        if [ ! -f "deploy_map.txt" ]; then
            echo "Error: deploy_map.txt not found. This file is required for new deployments."
            exit 1
        fi
        
        read -p "Remove existing files and deploy new ones? (y/N) " confirm
        if [[ "$confirm" =~ ^[Yy]$ ]]; then
            rm -f bot.py pcc-deploy.toml
            echo "Removed existing deployment files"
        else
            echo "Keeping existing files"
            exit 0
        fi
    fi
elif [ ! -f "deploy_map.txt" ]; then
    echo "Error: deploy_map.txt not found and no existing deployment files found."
    exit 1
fi

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

# Extract version and image name from toml file
IMAGE_LINE=$(grep -E '^image\s*=' pcc-deploy.toml)
VERSION=$(echo "$IMAGE_LINE" | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+')
IMAGE_NAME=$(echo "$IMAGE_LINE" | cut -d'"' -f2 | cut -d':' -f1)
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