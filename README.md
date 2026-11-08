# Floaty Rec

A tiny floating screen recorder and screenshot tool for **low-end Windows PCs**.
It stays on top of your screen as a small bar, and it's built to be light and lag-free.

## Features

- Floating always-on-top bar that you can drag anywhere
- One-click or hotkey recording and screenshots
- Uses your GPU encoder when available (NVIDIA NVENC, Intel QuickSync, AMD AMF)
- Falls back to CPU x264 `ultrafast` if there's no GPU encoder
- Records to MKV first (safe if it crashes), then converts to MP4 instantly with no re-encode
- Optional microphone / system audio recording
- The recorder bar is hidden from recordings and screenshots (Windows 10 2004+)
- Auto-downloads ffmpeg if it's missing
- Automatic retry in safe mode if a recording fails, plus a readable error log

## Hotkeys

| Key | Action |
|-----|--------|
| **F9** | Start / stop recording |
| **F10** | Take a screenshot |

Hotkeys work even while you're in a game or another app.

## Installation

1. Install [Python 3.9+](https://www.python.org/downloads/) (tick "Add Python to PATH").
2. Download `FloatyRec.pyw`.
3. Double-click it.
4. If ffmpeg isn't found, click the red **⬇ ffmpeg** button on the bar. It downloads automatically.
   You can also put `ffmpeg.exe` next to `FloatyRec.pyw` yourself.

No extra Python packages are needed.

## Settings (⚙)

- **FPS:** 15 / 24 / 30 / 60
- **Quality:** Original / 1080p / 720p / 480p (720p is the default and works well on weak PCs)
- **Audio:** pick a microphone or Stereo Mix
- **Encoder:** Auto / GPU / CPU
- **Folder:** where videos and screenshots are saved (default: `Videos\FloatyRec`)

## Tips for very slow PCs

- Use **480p** and **24 FPS**
- Pick a GPU encoder if you have one
- Close heavy apps while recording

## Troubleshooting

If recording fails, a popup shows the error. The full log is saved as
`last_ffmpeg_log.txt` in your save folder. Please attach it when opening an issue.

## Requirements

- Windows 10 / 11
- Python 3.9+
- ffmpeg (auto-downloaded)

## License

MIT
