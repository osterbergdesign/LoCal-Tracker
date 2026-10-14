# Matkoll

A self-hosted meal planner and calorie tracker for a household. It runs as one small Docker container with a SQLite database, and installs on your phone like an app.

- **Barcode scanning** with the phone camera. Products are looked up in Open Food Facts and saved locally, so each barcode is only fetched once. Unknown products can be added from the label and are remembered.
- **Photo logging.** Snap your plate and a vision model lists what it sees with estimated grams and calories. You check the amounts, swap any item for a matching food from the database, and log it. Works with a local Ollama model, the Claude API, the OpenAI API (or any OpenAI-compatible server), or several at once.
- **Recipes with kcal per gram.** Add raw ingredients, weigh the finished dish, and Matkoll works out kcal per gram and per 100 g of the cooked food. Recipes can then be logged by the gram like any other food, and used inside other recipes.
- **Shared meal plan.** Plan the week for the household; each person logs their own portion with one tap.
- **Household accounts.** Personal diaries and goals; shared foods, recipes and plan.
- **Food data:** Livsmedelsverket's ~2,500 Swedish foods (downloaded on first start), USDA FoodData Central search, Open Food Facts search, and your own foods.
- CSV export of your diary.

## Quick start

```bash
cp .env.example .env        # optional, everything can be set in the app later
docker compose up -d --build
```

Open `http://<server>:8080`, create the first account (it becomes the admin), and add the rest of the household under **You → Household**.

The Swedish food database downloads in the background on first start; progress shows under **You → Food databases**.

## iPhone app

`ios-app/` holds a native iPhone app around your server, with Apple's barcode scanner and Apple Health sync. Building it needs a Mac with Xcode; see [ios-app/README.md](ios-app/README.md).

## Proxmox LXC

Paste this into the shell of your Proxmox VE host (node → **Shell**):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/osterbergdesign/LoCal-Tracker/main/lxc/matkoll-lxc.sh)"
```

It asks a few questions, creates an unprivileged Debian container (12 on Proxmox VE 8, 13 on 9) that starts on boot, and installs Matkoll in it from this repository as a systemd service. No Docker needed.

**Updating:** run this on the host, with your container's ID:

```bash
pct exec 116 -- matkoll-update
```

It backs up the database, pulls the latest code from GitHub, updates Python packages and restarts. Data and settings are kept. (Containers created with the older bundled script don't have `matkoll-update` yet; for those, run `bash -c "$(curl -fsSL https://raw.githubusercontent.com/osterbergdesign/LoCal-Tracker/main/lxc/matkoll-lxc.sh)" -- update 116` once.)

Without questions, or with your own settings:

```bash
curl -fsSL https://raw.githubusercontent.com/osterbergdesign/LoCal-Tracker/main/lxc/matkoll-lxc.sh -o matkoll-lxc.sh
CTID=150 RAM=2048 NET=192.168.1.50/24 GATEWAY=192.168.1.1 bash matkoll-lxc.sh -y
```

Settings: `CTID`, `CT_HOSTNAME`, `CORES`, `RAM`, `DISK`, `BRIDGE`, `NET` (`dhcp` or `192.168.1.50/24`), `GATEWAY`, `VLAN`, `STORAGE`, `TEMPLATE_STORAGE`, `PORT`, `OLLAMA=yes`, `OLLAMA_MODEL`, `OLLAMA_URL`, `ROOT_PASSWORD`, `SSH_KEY_FILE`.

Inside the container:

| What | Where |
| --- | --- |
| App | `/opt/matkoll/src` (git checkout), Python venv in `/opt/matkoll/venv` |
| Settings | `/etc/matkoll/matkoll.env` (then `systemctl restart matkoll`) |
| Data | `/var/lib/matkoll/matkoll.db` |
| Backups | daily copies in `/var/lib/matkoll/backups`, last 14 kept; `matkoll-backup` makes one now |
| Logs | `journalctl -fu matkoll` |

For photo recognition the script can point Matkoll at an Ollama server you already run, or install Ollama inside the container (CPU only; it raises RAM to 8 GiB and disk to 20 GiB and downloads the model in the background). A GPU is better used by a separate Ollama VM or container with the GPU passed through.

`lxc/install.sh` also works on any Debian or Ubuntu machine or VM, without Proxmox.

## Use HTTPS for the camera

Browsers only allow live camera access on HTTPS pages. Over plain HTTP everything else works, and you can still photograph a barcode or a meal through the phone's camera app, but the live barcode scanner needs HTTPS. Easy options:

- **Tailscale:** `tailscale serve --bg 8080` on the server gives you `https://<machine>.<tailnet>.ts.net` with a real certificate, reachable from your phones anywhere.
- **A reverse proxy you already run** (Caddy, Nginx Proxy Manager, Traefik, SWAG) pointed at port 8080.

Caddy example:

```
matkoll.example.com {
    reverse_proxy matkoll:8080
}
```

Set `SECURE_COOKIE=1` in `.env` once it's served over HTTPS.

Then on the phone: open the site and choose **Add to Home Screen** (iPhone: Share menu; Android: browser menu).

## Photo recognition

### Local, with Ollama

Runs on your own hardware; photos never leave the house. A GPU makes it fast (a few seconds); on CPU only, expect a minute or more per photo.

```bash
docker compose --profile ollama up -d
docker exec matkoll-ollama ollama pull qwen2.5vl:7b
```

In Matkoll, under **You → Photo recognition**, set the Ollama address to `http://ollama:11434` and press **List models** to check it's reachable. If Ollama already runs elsewhere on your network, use its address instead (for example `http://192.168.1.20:11434`).

Vision models that work: `qwen2.5vl:7b` (good balance, ~6 GB), `qwen2.5vl:3b` (smaller machines), `llama3.2-vision:11b`, `gemma3:12b`. Larger models estimate portions better.

### Cloud

Paste a Claude or OpenAI API key under **You → Photo recognition**. The photo is shrunk to 1280 px before it's sent. With more than one provider set up, each person picks which to use when they take a photo.

Estimates are a starting point: portion sizes from a photo are often off by 20–30 %. The review screen exists so you can fix the grams before logging.

## How recipe calories are calculated

1. Each ingredient's energy = its kcal per 100 g × grams ÷ 100, summed for the whole dish.
2. The dish's weight is the **cooked weight** you enter (weighed without the pot). If you leave it empty, the sum of raw ingredient weights is used.
3. kcal per gram = total kcal ÷ dish weight.

Cooking changes weight a lot (pasta and rice absorb water, stews and roasts lose it), which is why weighing the finished dish matters. Example: 500 g beef, 800 g tomatoes, 380 g beans, 150 g onion and 20 g oil is 1,751 kcal; cooked down to 1,600 g that's 1.09 kcal per gram, so a 300 g bowl is 328 kcal.

When you edit a recipe, any recipe that uses it as an ingredient is recalculated too. Diary entries always use the recipe's current values.

## Backups

Everything lives in one SQLite file in the `matkoll-data` volume. To back it up while the app runs:

```bash
docker exec matkoll python -c "import sqlite3; s=sqlite3.connect('/data/matkoll.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
docker cp matkoll:/data/backup.db ./matkoll-backup-$(date +%F).db
```

## Settings by environment variable

See `.env.example`. Values saved in the app take priority over the environment.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECURE_COOKIE` | `0` | Set `1` behind HTTPS |
| `AUTO_IMPORT_SLV` | `1` | Download Livsmedelsverket's database on first start |
| `AI_DEFAULT_PROVIDER` | `ollama` | `ollama`, `anthropic` or `openai` |
| `OLLAMA_URL`, `OLLAMA_MODEL` | – , `qwen2.5vl:7b` | Local vision model |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | – , `claude-sonnet-5-5` | Claude |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` | – , `gpt-4.1-mini`, OpenAI | OpenAI or a compatible server |
| `USDA_API_KEY` | `DEMO_KEY` | USDA search (demo key: ~30 searches/hour) |

## Running without Docker

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Data goes to `./data`. For barcode scanning on iPhone, also download `@zxing/library`'s `umd/index.min.js` to `app/static/vendor/zxing.min.js` (the Docker build does this for you). Chrome on Android scans without it.

## Project layout

```
app/main.py      routes: auth, foods, diary, recipes, plan, photo, settings
app/db.py        SQLite schema and helpers
app/sources.py   Open Food Facts, USDA, Livsmedelsverket
app/ai.py        photo estimation via Ollama, Claude or OpenAI
app/static/      the web app (plain JS, no build step)
lxc/             Proxmox helper script and the installer it runs
ios-app/         iPhone app (Capacitor): setup screen, native scanner, Apple Health
```

## Data sources and licences

- Livsmedelsverket, Livsmedelsdatabasen — CC BY 4.0
- Open Food Facts — Open Database Licence (ODbL)
- USDA FoodData Central — public domain (CC0)
