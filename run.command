#!/bin/bash
# ============================================================================
#  Caption Engine - one-click setup and launch (macOS, Apple Silicon)
#
#  Double-click this file to start the caption engine.
#  The FIRST time it runs it installs everything the program needs
#  (Homebrew + Python + FFmpeg + AI libraries, ~4 GB download,
#  10-30 minutes depending on internet).
#  Every time AFTER that it skips setup and opens the app in a few seconds.
#
#  This is the Mac twin of run.bat. Two differences worth knowing:
#    * PyTorch comes from plain PyPI - the cu128 index in requirements.txt is
#      for Windows machines with an NVIDIA card and has no Mac builds.
#    * Instead of copying FFmpeg's DLLs next to torchcodec (run.bat step 5),
#      we point DYLD_FALLBACK_LIBRARY_PATH at Homebrew's FFmpeg 7 libraries.
# ============================================================================
set -u
cd "$(dirname "$0")" || exit 1
printf '\033]0;Caption Engine\007'

# ----------------------------------------------------------------------------
#  Helpers
# ----------------------------------------------------------------------------
die() {
    echo
    echo "  PROBLEM: $1"
    echo "  FIX:     $2"
    echo
    read -r -p "  Press Return to close this window. "
    exit 1
}

# Homebrew is not on PATH in a fresh double-click Terminal until the user's
# shell profile has been set up, so look in the two places it ever lives.
find_brew() {
    command -v brew >/dev/null 2>&1 && return 0
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -x "$candidate" ]; then
            eval "$("$candidate" shellenv)"
            return 0
        fi
    done
    return 1
}

# ffmpeg@7 is "keg-only": Homebrew installs it but deliberately does not put it
# on PATH, because the machine may also have a newer ffmpeg. So we wire it up
# by hand for this window only - nothing else on the Mac is changed.
#   PATH                       -> the renderer shells out to a bare "ffmpeg"
#   DYLD_FALLBACK_LIBRARY_PATH -> torchcodec dlopen()s libavutil.59.dylib etc.
wire_ffmpeg() {
    local prefix
    prefix="$(brew --prefix ffmpeg@7 2>/dev/null)"
    if [ -z "$prefix" ] || [ ! -x "$prefix/bin/ffmpeg" ]; then
        die "FFmpeg 7 (the tool that reads audio out of video files) is missing." \
            "Run: brew install ffmpeg@7   then double-click run.command again."
    fi
    export PATH="$prefix/bin:$PATH"
    export DYLD_FALLBACK_LIBRARY_PATH="$prefix/lib:${DYLD_FALLBACK_LIBRARY_PATH:-$HOME/lib:/usr/local/lib:/usr/lib}"
}

if [ "$(uname -m)" != "arm64" ]; then
    die "This is an Intel Mac, and the AI engine (PyTorch 2.8) has no Intel-Mac build." \
        "Send Kamoliddin a message - it needs a different set of library versions."
fi

find_brew || true

# If setup already finished once, this marker file exists - skip straight to
# launching the app.
if [ ! -f venv/.setup_complete ]; then

echo
echo " ============================================================"
echo "  CAPTION ENGINE - FIRST TIME SETUP"
echo " ============================================================"
echo
echo "  This looks like the first time running the app on this"
echo "  computer, so it will now install everything it needs."
echo "  It may ask for your Mac password once (that is macOS asking"
echo "  permission to install, not the app)."
echo
echo "  It downloads about 4 GB, so it can take 10-30 minutes."
echo "  Please keep this window open until it says DONE."
echo
read -r -p "  Press Return to start. "

# ============================================================================
#  STEP 1 / 6 - Homebrew
# ============================================================================
echo
echo "[Step 1 of 6] Checking for Homebrew..."
echo "              Homebrew is the standard installer for developer"
echo "              tools on macOS. We use it to get Python and FFmpeg."
if find_brew; then
    echo "              OK - Homebrew is installed."
else
    echo "              Not found - installing it now. It will ask for"
    echo "              your Mac password; typing shows nothing on screen,"
    echo "              which is normal. Press Return when it asks."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || die "Homebrew could not be installed." \
               "Open https://brew.sh in a browser and follow the one-line install there, then double-click run.command again."
    find_brew || die "Homebrew installed but this window cannot see it yet." \
                     "Close this window and double-click run.command again - setup continues where it left off."
    echo "              OK - Homebrew installed."
fi

# ============================================================================
#  STEP 2 / 6 - Python 3.12 and FFmpeg 7
# ============================================================================
echo
echo "[Step 2 of 6] Installing Python 3.12 and FFmpeg 7..."
echo "              Python is the language the caption engine is written"
echo "              in; version 3.12 specifically is required. FFmpeg is"
echo "              what reads audio out of videos and writes the final"
echo "              .mov - version 7 specifically, because the AI video"
echo "              library does not support the newer FFmpeg 8 yet."
PY="$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"
if [ ! -x "$PY" ]; then
    brew install python@3.12 || die "Python 3.12 could not be installed." \
                                    "Check the internet connection, then double-click run.command again."
    PY="$(brew --prefix python@3.12)/bin/python3.12"
fi
[ -x "$PY" ] || die "Python 3.12 installed but was not found where expected." \
                    "Take a screenshot of this window and send it to Kamoliddin."

if [ ! -x "$(brew --prefix ffmpeg@7 2>/dev/null)/bin/ffmpeg" ]; then
    brew install ffmpeg@7 || die "FFmpeg 7 could not be installed." \
                                 "Check the internet connection, then double-click run.command again."
fi
wire_ffmpeg
echo "              OK - Python 3.12 and FFmpeg 7 ready."

# ============================================================================
#  STEP 3 / 6 - Private workspace (virtual environment)
# ============================================================================
echo
echo "[Step 3 of 6] Creating the app's private workspace (\"venv\" folder)..."
echo "              All the libraries get installed into this one folder"
echo "              inside the project, so nothing else on the computer"
echo "              is touched. Deleting the folder fully uninstalls them."
if [ ! -x venv/bin/python ]; then
    "$PY" -m venv venv || die "The workspace folder could not be created." \
                              "Take a screenshot of this window and send it to Kamoliddin."
fi
echo "              OK - workspace ready."
echo
echo "              Updating pip (the tool that downloads Python libraries)..."
venv/bin/python -m pip install --upgrade pip --quiet \
    || die "pip could not be updated - usually the internet connection dropping." \
           "Check the internet, then double-click run.command again."

# ============================================================================
#  STEP 4 / 6 - PyTorch (the AI engine) - this is the big download
# ============================================================================
echo
echo "[Step 4 of 6] Installing PyTorch, the AI engine that powers the"
echo "              speech recognition. THIS IS THE BIGGEST DOWNLOAD"
echo "              (2-3 GB) - it is normal for it to sit at the same"
echo "              percentage for a while. Please be patient."
venv/bin/python -m pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 \
    || die "PyTorch could not be installed - usually the internet connection dropping." \
           "Check the internet, then double-click run.command again - setup continues where it left off."
echo "              OK - PyTorch installed."

# ============================================================================
#  STEP 5 / 6 - The rest of the libraries
# ============================================================================
echo
echo "[Step 5 of 6] Installing the remaining libraries (speech recognition,"
echo "              subtitle rendering, image handling)..."
venv/bin/python -m pip install -r requirements.txt \
    || die "The libraries could not be installed - usually the internet connection dropping." \
           "Check the internet, then double-click run.command again - setup continues where it left off."
echo "              OK - libraries installed."

# ============================================================================
#  STEP 6 / 6 - Final check
# ============================================================================
echo
echo "[Step 6 of 6] Double-checking that everything loads correctly..."
venv/bin/python -c "import torch, torchcodec, whisperx" >/dev/null \
    || die "Setup finished installing but the final check failed." \
           "Take a screenshot of this window and send it to Kamoliddin. Do not delete anything yet."
ffmpeg -version >/dev/null 2>&1 \
    || die "Setup finished installing but FFmpeg does not run." \
           "Take a screenshot of this window and send it to Kamoliddin. Do not delete anything yet."

# Leave the marker so future launches skip all of the above.
echo ok > venv/.setup_complete

echo
echo " ============================================================"
echo "  DONE - setup finished successfully!"
echo " ============================================================"
echo
echo "  One heads-up: the FIRST TIME you transcribe a video, the app"
echo "  downloads the AI speech models themselves (a few more GB)."
echo "  That only happens once - after that everything is fast."
echo

fi  # end of first-time setup

# ============================================================================
#  Launch the app
# ============================================================================
find_brew || die "Homebrew is installed but this window cannot see it." \
                 "Close this window and double-click run.command again."
wire_ffmpeg

echo "Starting the Caption Engine..."
echo "(Keep this Terminal window open - it runs the app. A browser tab will open"
echo " automatically. Closing this window, or pressing Control-C, shuts the app"
echo " down. If something goes wrong, the error appears here.)"
venv/bin/python -m caption_engine.web
status=$?
# 130 = Control-C, 2 = quit signal. Both are the user stopping the app on
# purpose, not a crash.
if [ "$status" -ne 0 ] && [ "$status" -ne 130 ] && [ "$status" -ne 2 ]; then
    die "The app closed because of an error - see the message above." \
        "If you cannot fix it, take a screenshot of this window and send it to Kamoliddin."
fi
exit 0
