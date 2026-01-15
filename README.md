# Voice Transcriber

Minimal Linux tool for recording and transcribing audio with AI cleanup.

## Features
- Global hotkey (Win+H) to toggle recording
- Transcription via Groq Whisper API
- Text cleanup via Groq LLM
- System tray integration

## Setup
```bash
./install.sh
cp .env.example .env  # Add your GROQ_API_KEY
./venv/bin/python main.py
```

## Requirements
- Linux with PulseAudio/PipeWire
- Groq API key
