# Run it on your own Windows computer

1. **Python 3.11+**: install from python.org. Tick "Add python.exe to PATH".
2. **Get the code**: install Git, then in PowerShell:
   `git clone https://github.com/Harshitha995-lab/bioscriptz_portfolio` then
   `cd bioscriptz_portfolio` and `git checkout claude/zealous-carson-l0g3kl` and `cd brand-scouts`
3. **Install packages**: `pip install -r requirements.txt`
4. **ffmpeg** (needed for transcripts and video frames): `winget install Gyan.FFmpeg`, then close and reopen PowerShell.
5. **Keys**: copy `.env.example` to `.env` and fill in `APIFY_TOKEN` (Apify Console → Settings → API & Integrations) and `ANTHROPIC_API_KEY` (console.anthropic.com). Don't share `.env`.
6. **Check**: `python check_setup.py`. It lists anything still to fix.
7. **Try the demo first**: `python web.py --sample` and open http://127.0.0.1:8000
8. **Live**: `python web.py`. Type a topic, read the cost box, click Run.

The first transcript downloads a speech model (a few hundred MB) and is slow once. After that a 60 to 90 second Reel takes roughly a minute on a normal laptop CPU (my estimate, not measured). Set `WHISPER_MODEL=base` in `.env` for faster, less accurate transcripts, or `medium` for slower, more accurate ones.
