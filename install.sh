#!/bin/bash

case "$(uname -s)" in
Darwin)
  echo "Setup OSX dependencies"
  brew install python-tk
  ;;
Linux)
  echo "Setup Debian Dependencies"
  sudo apt get python3-tk
  ;;
*)
  echo "Unknown environment $(uname -s)"
  ;;

esac

python3 -m venv venv
source venv/bin/activate
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

if [[ "$(uname)" == "Linux" ]]; then
  echo "Create linux application"
  PROJ_DIR="$(pwd)"
  DESKTOP_FILE="$HOME/.local/share/applications/fsradio.desktop"
  cp fsradio.desktop "$DESKTOP_FILE"
  sed -i "s|%PROJ_DIR%|$PROJ_DIR|g" "$DESKTOP_FILE"
  update-desktop-database "$HOME/.local/share/applications" || true
fi
