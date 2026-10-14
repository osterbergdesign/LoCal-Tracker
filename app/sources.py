"""External food databases: Open Food Facts (barcodes), USDA FoodData Central, Livsmedelsverket."""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import db

UA = {"User-Agent": "LoCal/1.0 (self-hosted calorie tracker)"}
OFF_BASE = os.environ.get("OFF_BASE_URL", "https://world.openfoodfacts.org")
SLV_BASE = os.environ.get("SLV_BASE_URL", "https://dataportal.livsmedelsverket.se/livsmedel/api/v1")
USDA_BASE = "https://api.nal.usda.gov/fdc/v1"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- Open Food Facts

OFF_FIELDS = "code,product_name,product_name_sv,product_name_en,brands,nutriments,serving_quantity"


def _off_to_food(p: dict):
    n = p.get("nutriments") or {}
    kcal = _num(n.get("energy-kcal_100g"))
    if kcal is None:
        kj = _num(n.get("energy-kj_100g")) or _num(n.get("energy_100g"))
        kcal = kj / 4.184 if kj is not None else None
    name = p.get("product_name_sv") or p.get("product_name") or p.get("product_name_en")
    if not name or kcal is None:
        return None
    alt = p.get("product_name_en") or p.get("product_name")
    return {
        "name": name.strip(),
        "name_alt": alt.strip() if alt and alt != name else None,
        "brand": (p.get("brands") or "").split(",")[0].strip() or None,
        "barcode": p.get("code"),
        "kcal": kcal,
        "protein": _num(n.get("proteins_100g")) or 0,
        "carbs": _num(n.get("carbohydrates_100g")) or 0,
        "fat": _num(n.get("fat_100g")) or 0,
        "fiber": _num(n.get("fiber_100g")) or 0,
        "serving_g": _num(p.get("serving_quantity")),
        "source": "off",
        "source_id": p.get("code"),
    }


def off_barcode(code: str):
    """Returns (food | None, status) where status is 'ok', 'not_found' or 'incomplete'."""
    r = requests.get(f"{OFF_BASE}/api/v2/product/{code}.json", params={"fields": OFF_FIELDS},
                     headers=UA, timeout=12)
    if r.status_code == 404:
        return None, "not_found"
    r.raise_for_status()
    data = r.json()
    if data.get("status") != 1 or not data.get("product"):
        return None, "not_found"
    p = data["product"]
    p.setdefault("code", code)
    food = _off_to_food(p)
    return (food, "ok") if food else (None, "incomplete")


def off_search(query: str):
    r = requests.get(f"{OFF_BASE}/cgi/search.pl", headers=UA, timeout=20, params={
        "search_terms": query, "search_simple": 1, "action": "process", "json": 1,
        "page_size": 25, "fields": OFF_FIELDS,
    })
    r.raise_for_status()
    return [f for f in (_off_to_food(p) for p in r.json().get("products", [])) if f]


# ---------------------------------------------------------------- USDA FoodData Central

USDA_IDS = {"kcal": (1008, 2047, 2048), "protein": (1003,), "fat": (1004,), "carbs": (1005,), "fiber": (1079,)}


def usda_search(query: str, include_branded=False):
    key = db.get_setting("usda_api_key") or os.environ.get("USDA_API_KEY") or "DEMO_KEY"
    types = ["Foundation", "SR Legacy"] + (["Branded"] if include_branded else [])
    r = requests.post(f"{USDA_BASE}/foods/search", params={"api_key": key}, timeout=20,
                      json={"query": query, "dataType": types, "pageSize": 25})
    if r.status_code == 429:
        raise RuntimeError("USDA rate limit reached. Add your own free API key in Settings.")
    r.raise_for_status()
    out = []
    for item in r.json().get("foods", []):
        vals = {}
        for nut in item.get("foodNutrients", []):
            nid = nut.get("nutrientId")
            for k, ids in USDA_IDS.items():
                if nid in ids and k not in vals and (k != "kcal" or (nut.get("unitName") or "").upper() == "KCAL"):
                    vals[k] = _num(nut.get("value"))
        if vals.get("kcal") is None:
            continue
        out.append({
            "name": item.get("description", "").capitalize(),
            "brand": item.get("brandOwner") or item.get("brandName"),
            "barcode": item.get("gtinUpc"),
            **{k: vals.get(k) or 0 for k in db.NUTRIENTS},
            "source": "usda",
            "source_id": str(item.get("fdcId")),
        })
    return out


# ---------------------------------------------------------------- Livsmedelsverket

SLV_CODES = {"PROT": "protein", "FAT": "fat", "CHO": "carbs", "FIBT": "fiber"}
SLV_NAMES = {"protein": "protein", "fett": "fat", "kolhydrater": "carbs", "fibrer": "fiber"}
slv_status = {"state": "idle", "done": 0, "total": 0, "error": None, "finished": None}
_slv_lock = threading.Lock()


def _slv_list(sprak: int):
    items, offset = [], 0
    while True:
        r = requests.get(f"{SLV_BASE}/livsmedel", params={"offset": offset, "limit": 1000, "sprak": sprak},
                         headers=UA, timeout=60)
        r.raise_for_status()
        page = r.json().get("livsmedel") or []
        items += page
        if len(page) < 1000:
            return items
        offset += 1000


def _slv_nutrients(nummer):
    for attempt in range(4):
        try:
            r = requests.get(f"{SLV_BASE}/livsmedel/{nummer}/naringsvarden", params={"sprak": 1},
                             headers=UA, timeout=30)
            r.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    vals = {}
    for nv in r.json():
        code = (nv.get("euroFIRkod") or "").upper()
        unit = (nv.get("enhet") or "").lower()
        name = (nv.get("namn") or "").lower()
        v = _num(nv.get("varde"))
        if v is None:
            continue
        if code == "ENERC" or name.startswith("energi"):
            if unit == "kcal" or "kcal" in name:
                vals.setdefault("kcal", v)
            continue
        key = SLV_CODES.get(code)
        if not key and not code:
            for prefix, k in SLV_NAMES.items():
                if name.startswith(prefix):
                    key = k
                    break
        if key:
            vals.setdefault(key, v)
    return vals


def slv_import():
    """Downloads the whole Swedish food database (~2,500 foods) into the local foods table."""
    if not _slv_lock.acquire(blocking=False):
        return
    try:
        slv_status.update(state="running", done=0, total=0, error=None)
        sv = _slv_list(1)
        en = {f["nummer"]: f.get("namn") for f in _slv_list(2)}
        slv_status["total"] = len(sv)

        def fetch(f):
            return f, _slv_nutrients(f["nummer"])

        with ThreadPoolExecutor(max_workers=6) as pool:
            for f, vals in pool.map(fetch, sv):
                if vals.get("kcal") is not None:
                    db.upsert_food({
                        "name": f["namn"], "name_alt": en.get(f["nummer"]), "brand": "Livsmedelsverket",
                        **{k: vals.get(k, 0) for k in db.NUTRIENTS},
                        "source": "slv", "source_id": str(f["nummer"]),
                    }, commit=False)
                slv_status["done"] += 1
                if slv_status["done"] % 200 == 0:
                    db.conn().commit()
        db.conn().commit()
        db.set_setting("slv_imported", time.strftime("%Y-%m-%d"))
        slv_status.update(state="done", finished=time.strftime("%Y-%m-%d %H:%M"))
    except Exception as e:  # noqa: BLE001 - surfaced in the UI
        db.conn().commit()
        slv_status.update(state="error", error=str(e))
    finally:
        _slv_lock.release()


def start_slv_import():
    if slv_status["state"] != "running":
        threading.Thread(target=slv_import, daemon=True).start()
