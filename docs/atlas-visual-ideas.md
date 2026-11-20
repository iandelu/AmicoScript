# Experimental visual ideas

In the AI Assistant's Analyze tab, select **Ideas + fotogramas**, open a
transcribed recording and enter its original YouTube, Instagram or TikTok URL.
The user must ensure the URL matches the selected transcript. The application
downloads a video temporarily, samples three frames at 25%, 50% and 75%, and
asks a local Ollama vision model to describe them. It then combines these
descriptions with the timestamped transcript in an ordinary saved analysis.
Ideas are proposals for human review, not automatically accepted knowledge.
The three sampled images are retained locally with the analysis and shown in
the assistant along with their timestamps. Open a recording and choose
**Ver último análisis con fotogramas** to see them again. Analyses created
before this feature do not have saved frames and must be run again.

The feature needs `ffmpeg`, `ffprobe`, yt-dlp, `curl_cffi`, and a local Ollama
server. Configure the application's LLM settings with a local endpoint and
model. The vision endpoint defaults to `http://host.docker.internal:11434` and
the vision model to `gemma4:e4b`; operators may set `ATLAS_OLLAMA_URL` and
`ATLAS_VISION_MODEL` to change them. Only loopback and Docker's host alias are
accepted. On a non-Docker installation set the endpoint to
`http://localhost:11434`. The default model must be installed locally.

Three frames are a partial sample, not a complete visual transcript. Visual
descriptions and generated ideas can be wrong; verify evidence against the
original. Platform access and available formats can change. Analysis fails
explicitly if the video, frames or local model cannot be accessed; the
temporary directory is removed after processing. Recheck that the supplied URL
matches the recording: existing AmicoScript recordings do not preserve a
source URL for this purpose.

Current limitation: AmicoScript's library export does not yet include the
stored frames. Back up the `visual-evidence` directory under the data directory
separately if you need to restore them on another installation. Deleting an
analysis or its recording removes its saved frames.
