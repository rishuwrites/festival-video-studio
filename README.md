# Festival Video Studio

Create original Hindi festival explainers with research notes, original illustrations, narration, captions, background music, and a thumbnail.

## What it does

- Searches YouTube for relevant videos and requires public Hindi/English captions from **five distinct channels**.
- Compares source-video themes with current Google Search-grounded research.
- Requires at least two grounded web citations and records all source links in a research report.
- Generates an original 9–12 chapter Hindi script. Source captions are research inputs only: they are never saved in the report or copied into the script.
- Verifies the synthesized narration lasts at least six minutes before rendering.
- Produces an MP4, thumbnail, metadata JSON, and a research JSON report.
- Can upload directly to YouTube as a **private scheduled video** when YouTube upload is enabled in the manual workflow.

The default coverage is **all of India**, with extra research attention to **Uttar Pradesh and Bihar**, including regional customs. The script must separate nationwide facts from regional practices rather than presenting one state’s customs as universal. Exact muhurta timings vary city by city, so the nationwide video will not present one city’s time as valid across India.

## Run locally

Install Python dependencies and FFmpeg. On Windows, install a Devanagari font such as Nirmala UI. Set API keys in the shell; do not commit them:

```powershell
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY = "..."
$env:YT_CLIENT_ID = "..."
$env:YT_CLIENT_SECRET = "..."
$env:YT_REFRESH_TOKEN = "..."
python recap\festival_main.py --topic "Dhanteras" --date "2026"
```

YouTube search and uploads use your OAuth secrets (`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`). Without `YT_API_KEY`, the refresh token must include `youtube.readonly` as well as `youtube.upload`; YouTube Data API v3 must be enabled for the Google Cloud project. Alternatively, add a restricted `YT_API_KEY` Actions secret for public video search; OAuth still needs `youtube.upload` for publishing. Use `--scope` to customize coverage, or the older `--location` option as an alias. For example, `--scope "India (nationwide, focus on UP and Bihar)"`. Image generation can use Cloudflare credentials; the configured image providers are tried as fallbacks. Output is written to `output\`.

## GitHub Actions

This workflow uses a **self-hosted Linux runner** because GitHub-hosted runners may be blocked from retrieving YouTube captions. Since this project folder is on Windows, the recommended setup is Ubuntu under WSL 2; it also provides the Linux text-shaping support needed for Hindi rendering.

1. Install WSL 2 and Ubuntu on Windows if they are not installed. In Ubuntu, install the video and Hindi-font dependencies:

   ```bash
   sudo apt-get update
   sudo apt-get install -y ffmpeg fonts-noto-core libraqm0 libfribidi0 libharfbuzz0b python3 python3-pip
   ```

2. In the private repository, open **Settings → Actions → Runners → New self-hosted runner**, choose **Linux x64**, and follow GitHub's instructions inside the Ubuntu/WSL shell. Keep that shell and the Windows computer awake while jobs execute. Leave the runner's default labels: `self-hosted`, `linux`, and `x64`. The workflow installs Python packages and verifies FFmpeg, RAQM, and a Devanagari font before generation.
3. Add `GEMINI_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN` as repository Actions secrets. The refresh token needs `youtube.upload`; it also needs `youtube.readonly` for source searches unless you provide the optional `YT_API_KEY` secret for public search. YouTube Data API v3 must be enabled for the Google Cloud project. Optionally add `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`.
4. Run **Festival explainer video** manually with a topic, festival date, **publish date (YYYY-MM-DD)**, and **publish time (24-hour HH:MM IST)**. The upload checkbox is on by default and creates a private scheduled video; the selected time must still be at least 15 minutes in the future after rendering finishes. Turn upload off to generate a preview only.

Only attach a self-hosted runner to this private repository and run trusted workflow code on it. Do not use the runner for untrusted pull requests or public-repository workflows.

## Tests

```powershell
python -m unittest discover -s tests -v
```
