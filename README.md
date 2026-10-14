# LoCal

A self-hosted meal planner and calorie tracker for a household. Install it in **Home Assistant through HACS**, where it gets its own sidebar panel in the Home Assistant app and on your computer, or run it on its own (Proxmox LXC or Docker).

- **Barcode scanning** with the phone camera. Products are looked up in Open Food Facts and saved locally, so each barcode is only fetched once. Unknown products can be added from the label and are remembered.
- **Photo logging.** Snap your plate and a vision model lists what it sees with estimated grams and calories. You check the amounts, swap any item for a matching food from the database, and log it. Works with a local Ollama model, the Claude API, the OpenAI API (or any OpenAI-compatible server), or several at once.
- **Recipes with kcal per gram.** Add raw ingredients, weigh the finished dish, and Matkoll works out kcal per gram and per 100 g of the cooked food. Recipes can then be logged by the gram like any other food, and used inside other recipes.
- **Shared meal plan.** Plan the week for the household; each person logs their own portion with one tap.
- **Mealie.** Import Mealie recipes with calories worked out from their ingredients, and keep the meal plan in sync both ways.
- **Recipe links.** Paste a link from ICA, Arla, Köket and most other recipe sites; ingredients are matched to foods and their grams estimated for you to check.
- **Household accounts.** Personal diaries and goals; shared foods, recipes and plan.
- **Food data:** Livsmedelsverket's ~2,500 Swedish foods (downloaded on first start), USDA FoodData Central search, Open Food Facts search, and your own foods.
- CSV export of your diary.

## Home Assistant (HACS)

1. In Home Assistant, open **HACS**, click the **⋮** menu (top right) → **Custom repositories**.
2. Repository: `https://github.com/osterbergdesign/LoCal-Tracker`, type: **Integration** → **Add**.
3. Search HACS for **Matkoll**, open it, click **Download**, then restart Home Assistant (**Settings → System → Restart**).
4. **Settings → Devices & services → Add integration → Matkoll**.

**Matkoll** now appears in the sidebar. Everyone with a Home Assistant login gets their own diary and goals automatically; Home Assistant admins can change Matkoll's settings (photo recognition, Mealie) under **You**. The Swedish food database downloads in the background the first time.

In the **Home Assistant phone app**, the barcode button opens the app's own scanner. On a computer, scanning works in the browser when Home Assistant is opened over HTTPS (Nabu Casa or your own certificate).

Data is stored in `/config/matkoll/` and is included in Home Assistant backups.

### What Home Assistant gets

| Entity | What it shows |
| --- | --- |
| `sensor.matkoll_<name>_calories_eaten` | Calories logged today, per person (also `_calories_left`, `_protein_eaten`, `_carbohydrates_eaten`, `_fat_eaten`) |
| `sensor.matkoll_planned_breakfast` … `_dinner`, `_snack` | Today's planned meals from the shared plan |
| `calendar.matkoll_meal_plan` | The whole meal plan, for the calendar panel and dashboards |

Actions:

- **`matkoll.log_food`**: adds food by name or barcode to someone's diary. Without `person`, it uses whoever ran it.
  ```yaml
  action: matkoll.log_food
  data:
    food: havregryn
    grams: 80
    meal: breakfast
    person: person.anna
  ```
- **`matkoll.sync_mealie`**: syncs the meal plan with Mealie now (it also happens every 15 minutes).

Example automation idea: a notification at 14:00 if `sensor.matkoll_anna_calories_eaten` is still below 300.

## Mealie

Under **You → Mealie** (admin), enter Mealie's address and an API token (in Mealie: your user → **API Tokens** → create). Then:

- **Recipes → Import → From Mealie** lists your Mealie recipes. Pick one, check the ingredient matches and grams, and it becomes a Matkoll recipe with kcal per gram.
- **Recipes → Import → From a link** with **Save in Mealie too** ticked sends the link to Mealie, which reads the page (ICA, Arla, Köket and hundreds more), and then imports it into Matkoll.
- **Meal plan sync, both ways:** meals planned in Mealie appear in Matkoll's plan (tagged *Mealie*), and meals planned in Matkoll appear in Mealie, as a recipe link when the dish came from Mealie, otherwise as a note. Deleting or moving a meal on one side does the same on the other. Mealie recipes that aren't imported yet show up as one portion using Mealie's own nutrition numbers, if it has any; importing the recipe replaces them with exact values.

Ingredient amounts in grams are exact. Amounts in dl, spoons, pieces ("1 gul lök") or packs ("1 burk à 400 g") are converted with typical weights and densities, so check them on the import screen.

## iPhone app (optional)

`ios-app/` holds a native iPhone app around a standalone server, with Apple's barcode scanner and Apple Health sync. It needs a Mac with Xcode, and with a free Apple ID it must be reinstalled every 7 days; see [ios-app/README.md](ios-app/README.md). With Home Assistant, the HA app covers this instead.

## Standalone: Docker

```bash
cp .env.example .env        # optional, everything can be set in the app later
docker compose up -d --build
```

Open `http://<server>:8080`, create the first account (it becomes the admin), and add the rest of the household under **You → Household**.

## Standalone: Proxmox LXC

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

## Use HTTPS for the camera (standalone)

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
app/main.py         routes: auth, foods, diary, recipes, plan, import, Mealie sync, photo, settings
app/db.py           SQLite schema and helpers
app/sources.py      Open Food Facts, USDA, Livsmedelsverket
app/ingredients.py  turns "2 dl vetemjöl" into a name and grams
app/mealie.py       Mealie API client
app/ai.py           photo estimation via Ollama, Claude or OpenAI
app/static/         the web app (plain JS, no build step); ha-panel.js + ha.html for Home Assistant
custom_components/matkoll/   the Home Assistant integration (HACS)
lxc/                Proxmox helper script and the installer it runs
ios-app/            iPhone app (Capacitor): setup screen, native scanner, Apple Health
```

The integration carries its own copy of `app/` in `custom_components/matkoll/matkoll_app/`, because HACS only downloads that folder. After changing anything in `app/`, run `./scripts/sync-ha.sh` (CI fails if the copy is out of date).

## Data sources and licences

- Livsmedelsverket, Livsmedelsdatabasen — CC BY 4.0
- Open Food Facts — Open Database Licence (ODbL)
- USDA FoodData Central — public domain (CC0)
