# Installing with Docker

Docker installs everything (Python, Tesseract, the libraries and the embedding model) in one step, and it works the same on Mac, Windows and Linux.

## What's inside and what's outside

| In the container | On the machine |
|---|---|
| Python 3.12, Tesseract, the libraries | `documents/` |
| The embedding model | `index/` |
| The app | `.env` |

The documents, index and settings stay outside the container, so updating to a new version doesn't touch them.

The image uses the CPU-only version of PyTorch, which keeps it at about 720 MB instead of several GB. The embedding model is downloaded when the image is built, so the app starts quickly and search works offline.

## Install

Install Docker Desktop (Mac/Windows) or Docker Engine (Linux) first. On a new Mac, open Docker Desktop by hand once and accept the prompts before going on. Until you do, Docker commands just hang.

```bash
cd document-qa-assistant

cp .env.example .env
# Fill in GROQ_API_KEY, COMPANY_NAME and ADMIN_PASSWORD.
# TELEGRAM_* is only needed for the bot.

cp /path/to/documents/* documents/

docker compose up -d --build
docker compose exec assistant python scripts/ingest.py
```

The first build took about 7 minutes on a Mac, mostly downloading PyTorch. Later builds are much faster.

Open http://localhost:8000. From other computers on the same network, use the machine's IP address, e.g. `http://192.168.1.50:8000`.

To run the Telegram bot too:

```bash
docker compose --profile telegram up -d
```

## Commands

| | |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose down` |
| Status | `docker compose ps` |
| Logs | `docker compose logs -f assistant` |
| Re-index | `docker compose exec assistant python scripts/ingest.py` |
| Run the tests | `docker compose exec assistant python eval/run_eval.py` |
| Update | `git pull && docker compose up -d --build` |
| Back up | Copy `documents/` and `.env`. The index can be rebuilt. |

Documents can also be added from the admin page at `/admin`, which indexes them right away.

## Checklist after installing

1. `docker compose ps` shows the container as healthy
2. Restart the computer and check the page comes back on its own
3. `ADMIN_PASSWORD` is set
4. Ask a few questions and check the source links open
5. Write down the machine's IP address

## Common problems

- **Computer goes to sleep.** The app stops answering. Turn off sleep on that machine.
- **IP address changes.** Reserve a fixed IP for the machine in the router.
- **Docker doesn't start after a reboot.** On Mac and Windows, turn on "Start Docker Desktop when you sign in".
- **Port 8000 already in use.** Change the first number in `docker-compose.yml`, e.g. `"8080:8000"`.
