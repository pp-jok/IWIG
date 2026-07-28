#!/bin/zsh
set -eu

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This launcher supports macOS only. Start Google Chrome with the same --user-data-dir and --remote-debugging-port options on your platform." >&2
  exit 1
fi

CAPTURE_HOME="${XHS_CAPTURE_HOME:-$HOME/.xhs-url-video-capture}"
PROFILE="${XHS_CHROME_PROFILE_DIR:-$CAPTURE_HOME/chrome-profile}"
PORT="${XHS_CHROME_CDP_PORT:-9222}"
mkdir -p "$PROFILE"
open -na "Google Chrome" --args --user-data-dir="$PROFILE" --remote-debugging-port="$PORT" "https://www.xiaohongshu.com/"
echo "Chrome opened. Log in manually, keep this window open, then run capture."
