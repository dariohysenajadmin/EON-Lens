# Lens

Video intelligence for marketing and product teams. Paste a URL, upload a file, or compare 2-3 videos side by side. Lens watches them, frame by frame, and helps you take what works.

Four modes:

- **Marketing Hook Teardown** - frame-by-frame breakdown of the first 10 seconds. Hook strength, pattern interrupt, what's on screen at the moment of attention.
- **Product Demo Review** - what's clear, what's confusing, where viewers drop off, what to cut or add. Optionally returns starter code for a feature you saw.
- **Custom Goal** - tell Lens what you're trying to do, get analysis tuned to that goal.
- **Competitive Compare** - drop multiple videos and get a side-by-side teardown.

Plus a **Remix** button on every analysis. Click it and Lens reverse-engineers the video into something tuned for your brand voice (for marketing) or your tech stack (for dev). It uses your saved "My Context" so colleagues don't have to re-brief Lens every time.

## Prerequisites

You need these installed first (same toolkit Lens shares with the `/watch` skill):

- **Python 3.10+** - [python.org](https://www.python.org/downloads/) or `winget install Python.Python.3.12`
- **yt-dlp** - `winget install yt-dlp.yt-dlp`
- **ffmpeg** - `winget install Gyan.FFmpeg`

If you already set up the `/watch` skill, you have all three. Move on.

You also need API keys:

- **Anthropic API key** - from [console.anthropic.com](https://console.anthropic.com). Required. ~$0.20-0.80 per analysis depending on length and Remix.
- **Groq API key** (optional) - from [console.groq.com/keys](https://console.groq.com/keys). Only needed if a video has no captions and Lens needs to transcribe audio. Free tier is generous.

## Install

From a terminal in the `lens-app` folder:

```
pip install -r requirements.txt
```

That's it. Roughly 30 seconds.

## Run

**Windows (easiest):** double-click `run.bat`.

**Any platform:**

```
streamlit run app.py
```

Your default browser opens automatically at `http://localhost:8501`. If it doesn't, open that URL manually.

## First-time setup inside Lens

1. Open the **API keys** panel in the sidebar and paste your Anthropic key (Groq if you have one).
2. Open the **My Context** panel and paste a few lines about your brand (for marketing) or your tech stack (for dev). Examples are in the placeholder. Saving here means you don't have to re-explain who you are on every video.
3. Pick a theme (dark or light, your preference).
4. In the chat at the bottom, paste a YouTube URL or upload a file. Lens watches it.
5. Click one of the four preset chips and read the analysis.
6. Click **Remix for me** if you want a script (marketing) or starter code (dev) tuned to your context.

## Usage notes

**Multi-video sessions.** Drop a second URL in the chat and Lens will hold both videos in memory. Click **Competitive Compare** for a side-by-side teardown.

**Cost control.** Lens caps frame extraction at 30 frames per video by default - that's enough for most analyses. Each preset run with one video is roughly $0.20-0.40 in Claude tokens. A Remix adds another $0.20-0.40. Multi-video Compare is higher because all videos go to Claude in one prompt.

**Reset session.** Click the button in the sidebar to clear all videos and chat history without restarting the app.

**Files saved on disk.** Each session writes frame thumbnails and metadata to `data/session-XXXX/`. You can ignore that folder, or browse it to see what Lens actually sent to Claude.

## Sharing with colleagues

For now, each colleague needs to run Lens locally. They:

1. Install Python + yt-dlp + ffmpeg (or run the same `setup.ps1` from the watch-skill).
2. Get the `lens-app` folder (zip + share, or put it in shared storage).
3. `pip install -r requirements.txt`.
4. Get their own Anthropic + Groq keys (do not share keys - billing is per-account).
5. Double-click `run.bat`.

Future versions will add hosted access with team accounts.

## Troubleshooting

**"yt-dlp / ffmpeg not found"** - they're not on your PATH. Open a new terminal after installing, or run the `setup.ps1` from the watch-skill folder.

**"ANTHROPIC_API_KEY is not set"** - paste your key in the sidebar panel.

**Video URL fails to download** - update yt-dlp: `yt-dlp -U`. YouTube changes their backend periodically.

**Streamlit won't start on port 8501** - something else is using it. Run `streamlit run app.py --server.port 8502` instead.

**Frames load but Claude responds with weird formatting** - your Anthropic key may be on the free tier with model restrictions. Lens uses claude-sonnet-4-5 by default; verify your account has access.
