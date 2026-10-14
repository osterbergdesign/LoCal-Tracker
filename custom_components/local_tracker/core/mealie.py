"""Mealie API client (https://mealie.io). Uses an API token created in Mealie under User → API Tokens."""
import requests

from . import db


class MealieError(RuntimeError):
    pass


def config():
    return {
        "url": (db.get_setting("mealie_url") or "").rstrip("/"),
        "token": db.get_setting("mealie_token") or "",
        "sync": db.get_setting("mealie_sync", "1") == "1",
    }


def configured() -> bool:
    c = config()
    return bool(c["url"] and c["token"])


def _req(method, path, **kw):
    c = config()
    if not (c["url"] and c["token"]):
        raise MealieError("Mealie isn't connected. Add its address and an API token under You → Mealie.")
    try:
        r = requests.request(method, c["url"] + path, timeout=kw.pop("timeout", 20),
                             headers={"Authorization": f"Bearer {c['token']}", "Accept": "application/json"}, **kw)
    except requests.RequestException as e:
        raise MealieError(f"Couldn't reach Mealie at {c['url']}: {e}")
    if r.status_code == 401:
        raise MealieError("Mealie rejected the API token. Create a new one in Mealie under User → API Tokens.")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
            if isinstance(detail, dict):
                detail = detail.get("message") or detail
        except ValueError:
            detail = r.text[:200]
        raise MealieError(f"Mealie returned {r.status_code}: {detail}")
    if r.status_code == 204 or not r.content:
        return None
    try:
        return r.json()
    except ValueError:
        return r.text


def g(obj, *keys, default=None):
    """Reads a field whether Mealie sent it in camelCase or snake_case."""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return default


def check():
    about = _req("GET", "/api/app/about")
    _req("GET", "/api/users/self")  # /about doesn't need a token; this does
    return {"version": g(about, "version", default="?") if isinstance(about, dict) else "?"}


def list_recipes(search: str = "", page: int = 1):
    data = _req("GET", "/api/recipes", params={"search": search, "page": page, "perPage": 40,
                                                "orderBy": "name", "orderDirection": "asc"})
    items = g(data, "items", default=[]) or []
    return [{"id": g(r, "id"), "slug": g(r, "slug"), "name": g(r, "name"),
             "servings": g(r, "recipeServings", "recipe_servings"),
             "yield": g(r, "recipeYield", "recipe_yield")} for r in items]


def get_recipe(slug: str):
    return _req("GET", f"/api/recipes/{slug}")


def create_from_url(url: str) -> str:
    """Asks Mealie to scrape a recipe page (ICA, Arla, Köket and hundreds more). Returns the new slug."""
    slug = _req("POST", "/api/recipes/create/url", json={"url": url, "includeTags": False}, timeout=60)
    if isinstance(slug, dict):
        slug = g(slug, "slug")
    if not slug or not isinstance(slug, str):
        raise MealieError("Mealie couldn't read a recipe from that page.")
    return slug.strip('"')


_PLAN_PATH = None


def _plan_path():
    """Mealie 2.x keeps meal plans per household; 1.x per group."""
    global _PLAN_PATH
    if _PLAN_PATH:
        return _PLAN_PATH
    try:
        _req("GET", "/api/households/mealplans", params={"perPage": 1})
        _PLAN_PATH = "/api/households/mealplans"
    except MealieError as e:
        if "404" not in str(e):
            raise
        _PLAN_PATH = "/api/groups/mealplans"
    return _PLAN_PATH


def mealplans(start: str, end: str):
    data = _req("GET", _plan_path(), params={"start_date": start, "end_date": end, "perPage": -1})
    if isinstance(data, list):
        return data
    return g(data, "items", default=[]) or []


def create_mealplan(date: str, entry_type: str, recipe_id=None, title="", text=""):
    body = {"date": date, "entryType": entry_type, "title": title, "text": text}
    if recipe_id:
        body["recipeId"] = recipe_id
    try:
        res = _req("POST", _plan_path(), json=body)
    except MealieError as e:
        # Older Mealie versions don't know "snack"
        if entry_type == "snack" and "422" in str(e):
            body["entryType"] = "side"
            res = _req("POST", _plan_path(), json=body)
        else:
            raise
    return g(res, "id")


def delete_mealplan(entry_id):
    _req("DELETE", f"{_plan_path()}/{entry_id}")


def nutrition_per_serving(recipe: dict):
    """Mealie stores nutrition per serving as strings like '450' or '450 kcal'."""
    import re
    n = g(recipe, "nutrition") or {}

    def num(*keys):
        v = g(n, *keys)
        if v is None:
            return None
        m = re.search(r"\d+(?:[.,]\d+)?", str(v))
        return float(m.group(0).replace(",", ".")) if m else None

    out = {"kcal": num("calories"), "protein": num("proteinContent", "protein_content"),
           "carbs": num("carbohydrateContent", "carbohydrate_content"), "fat": num("fatContent", "fat_content"),
           "fiber": num("fiberContent", "fiber_content")}
    return out if out["kcal"] else None


def ingredient_lines(recipe: dict):
    """Each ingredient as (text, food_name, quantity, unit_name). food/unit are set when Mealie parsed the line."""
    lines = []
    for ing in g(recipe, "recipeIngredient", "recipe_ingredient", default=[]) or []:
        if g(ing, "title") and not (g(ing, "food") or g(ing, "note") or g(ing, "display")):
            continue  # section heading
        food = g(ing, "food") or {}
        unit = g(ing, "unit") or {}
        text = g(ing, "display", "originalText", "original_text", "note", default="") or ""
        lines.append({
            "text": text.strip(),
            "food": g(food, "name"),
            "qty": g(ing, "quantity"),
            "unit": g(unit, "abbreviation") or g(unit, "name"),
        })
    return lines
