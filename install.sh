#!/bin/bash
# Voice Transcriber Installation Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

echo "=== Voice Transcriber Setup ==="
echo ""

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Install system dependencies (for audio)
echo "Installing system dependencies..."
if command -v apt &> /dev/null; then
    sudo apt install -y portaudio19-dev python3-pyaudio libsndfile1 2>/dev/null || true
elif command -v dnf &> /dev/null; then
    sudo dnf install -y portaudio-devel python3-pyaudio libsndfile 2>/dev/null || true
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR"

# Activate and install dependencies
echo "Installing Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$SCRIPT_DIR/requirements.txt"

# Create .env from example if it doesn't exist
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo ""
    echo "Created .env file - please edit it to add your GROQ_API_KEY"
fi

# Create desktop entry for KDE/GNOME
DESKTOP_FILE="$HOME/.local/share/applications/voice-transcriber.desktop"
mkdir -p "$HOME/.local/share/applications"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Voice Transcriber
Comment=Record and transcribe audio with AI cleanup
Exec=$VENV_DIR/bin/python $SCRIPT_DIR/main.py
Icon=audio-input-microphone
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Utility;
Keywords=voice;audio;transcription;record;
StartupNotify=false
X-KDE-autostart-after=panel
EOF

echo ""
echo "=== Installation Complete ==="
echo ""
echo "To run the application:"
echo "  $VENV_DIR/bin/python $SCRIPT_DIR/main.py"
echo ""
echo "Or search for 'Voice Transcriber' in your application menu."
echo ""
echo "Hotkeys:"
echo "  Ctrl+Shift+R - Start recording"
echo "  Ctrl+Shift+S - Stop recording"
echo ""
echo "Don't forget to set your GROQ_API_KEY in $SCRIPT_DIR/.env"
