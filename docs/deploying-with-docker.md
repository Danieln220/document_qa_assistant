# Installing at a client, with Docker

Written 2026-09-22. This is the Premium delivery route: one command on the client's
machine instead of installing Python, Tesseract and a dozen libraries by hand.

Without Docker, an install is: Python 3.12, Tesseract, pip install, a virtual
environment, then discovering that their Windows machine puts Tesseract somewhere
else. With Docker it is `docker compose up -d`, and it behaves identically on a Mac,
a Windows machine and a Linux server.

## What is in the image

| Inside the container (fixed) | On the client's machine (theirs) |
|---|---|
| Python 3.12, Tesseract, every library | `documents/` - their documents |
| The embedding model, baked in at build time | `index/` - the search index |
| The app itself | `.env` - their settings and API key |

The split matters: a new version of the image replaces the old one **without
touching a single document**.

Two deliberate choices in the Dockerfile:

- **CPU-only PyTorch.** The default install pulls in NVIDIA GPU libraries and adds
  several gigabytes to an image that will never see a GPU in a back office.
- **The embedding model is downloaded at build time**, so the container starts
  instantly and searches with no internet connection at all.

## Installing at a client

**On their machine, once:** install Docker Desktop (Mac/Windows) or Docker Engine
(Linux). It is a normal download from docker.com.

Then:

```bash
# 1. Copy the project folder across (git clone, or a zip on a USB stick).
cd document-qa-assistant

# 2. Their settings.
cp .env.example .env
#    Edit .env:
#      GROQ_API_KEY      their own key
#      COMPANY_NAME      their company
#      ADMIN_PASSWORD    set this - the owner's page can delete documents
#      TELEGRAM_*        only if they want the bot

# 3. Their documents.
cp /path/to/their/documents/* documents/

# 4. Build and start. Measured on a Mac: 6 minutes 40 the first time
#    (most of it downloading PyTorch); later builds take seconds.
docker compose up -d --build

# 5. Index their documents.
docker compose exec assistant python scripts/ingest.py
```

Open **http://localhost:8000**. From other computers in the office, use the machine's
address, e.g. `http://192.168.1.50:8000`.

For the Telegram bot as well:

```bash
docker compose --profile telegram up -d
```

## Day-to-day commands

| Task | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose down` |
| Is it running? | `docker compose ps` |
| See what it is doing | `docker compose logs -f assistant` |
| Re-index after adding documents by hand | `docker compose exec assistant python scripts/ingest.py` |
| Run the accuracy test | `docker compose exec assistant python eval/run_eval.py` |
| Update to a new version | `git pull && docker compose up -d --build` |
| Back up | Copy the `documents/` folder and `.env`. The index rebuilds itself. |

The owner normally does none of this: they add documents through the owner's page at
`/admin`, which indexes immediately.

## What to check before leaving

1. `docker compose ps` shows the container **healthy**, not just running.
2. Reboot the machine, wait a minute, and load the page again. `restart: unless-stopped`
   should bring it back by itself. **Test this in front of them** - it is the whole
   point of the "always on" promise.
3. `ADMIN_PASSWORD` is set, and you have given it to them separately (not in the
   handover document).
4. Ask three real questions and check the citations open.
5. Find the machine's network address and write it into the handover document.

## Things that bite

- **The machine sleeping.** A Mac that goes to sleep stops answering. Turn sleep off
  in Energy Saver, or the "always on" promise quietly fails overnight.
- **A changing IP address.** Reserve one for that machine in their router, or staff
  will report it broken one morning.
- **Docker Desktop not starting at login** on Mac and Windows: tick "Start Docker
  Desktop when you sign in", otherwise nothing comes back after a reboot.
- **Port 8000 already in use.** Change the left-hand number in `docker-compose.yml`
  (e.g. `"8080:8000"`).
- **Image size.** About 720 MB (measured), thanks to the CPU-only PyTorch. Fine on a normal computer; worth
  mentioning before you install it on a tiny cloud instance.
- **Docker Desktop's first run needs someone at the keyboard.** On a fresh Mac it
  asks you to accept the service agreement and then asks for the machine's password
  to install its privileged helper. Until that is done, the interface appears to
  start but the Linux engine behind it never boots, and every command simply hangs.
  Seen on this machine: `docker info` hung, and Docker's own log said
  `cannot toggle VM OTel collector, backend is not running`, while its data folder
  was still only 1 MB - the sign that the engine's disk was never created. **Install
  Docker Desktop and open it once by hand before you start the install**, rather than
  launching it from a script.

## How to explain this to the customer

Keep Docker out of it unless they ask. What they care about is that it is contained,
always on, and theirs.

> "Everything the assistant needs is packaged into one box that sits on your machine.
> Nothing else on the computer is touched, and nothing is installed that could
> interfere with your other software. It starts by itself when the computer starts,
> so there is nothing for anyone to remember."

**"Where are our documents?"**
> "In a normal folder on your own computer - you can open it right now. The assistant
> reads from it. They are searched on this machine, not online."

**"What if we want to remove it?"**
> "One command, and it's gone. Your documents stay exactly where they are, because
> they were never inside it."

**"How do we update it?"**
> "I send you the new version and run one command. Your documents and settings aren't
> touched - they live outside the box."

**"Is it safe?"**
> "It runs with the lowest permissions it can, it can only see the documents folder
> you gave it, and the owner's page is password-protected. The only thing that leaves
> your office is the few lines of text needed to write each answer - and if even that
> isn't acceptable, we can run the AI on this machine too."

**If they ask what Docker is:**
> "A standard way of packaging software so it runs the same everywhere. Banks and
> hospitals run their systems this way. It means I'm not installing a pile of
> components onto your computer one by one, and nothing I install can break anything
> you already have."

## Pricing note

The first build of the image takes a few hours of your time. Every install after that
is about twenty minutes. That gap is why on-premise deployment belongs in the Premium
tier - and why you can offer it at a price that still works for the client.
