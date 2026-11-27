#!/usr/bin/env bash
# Naver Blog Auto on Linux from source: sets up a private Python environment the first time, then starts the app.
#   ./run_linux.sh            the desktop app
#   ./run_linux.sh --selftest /tmp/st.txt
set -e
cd "$(dirname "$0")"
if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "tkinter가 없어요. 먼저 설치하세요:  sudo apt install python3-tk python3-venv   (Fedora: sudo dnf install python3-tkinter)"
  exit 1
fi
if [ ! -d .venv ]; then
  echo "처음 실행: 필요한 프로그램을 설치합니다 (몇 분 걸려요)..."
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  # the browser that writes the posts (skipped if Chrome is installed; the app can also fetch it later)
  command -v google-chrome >/dev/null || .venv/bin/python -m playwright install chromium
fi
exec .venv/bin/python app.py "$@"
