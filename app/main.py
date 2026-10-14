import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import date as Date, timedelta

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import ai, db, ingredients, mealie, sources

STATIC = os.path.join(os.path.dirname(__file__), "static")
MEALS = ("breakfast", "lunch", "dinner", "snack")
COOKIE = "matkoll_session"
SECURE_COOKIE = os.environ.get("SECURE_COOKIE", "0") == "1"


# ---------------------------------------------------------------- helpers

def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(calc.hex(), h)
    except ValueError:
        return False


# When Matkoll runs inside Home Assistant, the integration calls it in-process and says who the HA user is.
# The secret is generated per start and never leaves the HA process, so the header can't be forged from outside.
TRUSTED_SECRET: str | None = None


def ha_user(request: Request):
    if not TRUSTED_SECRET or not hmac.compare_digest(request.headers.get("x-matkoll-secret", ""), TRUSTED_SECRET):
        return None
    try:
        info = json.loads(request.headers.get("x-matkoll-ha-user", ""))
        ha_id, name, admin = str(info["id"]), str(info.get("name") or "Home Assistant user"), bool(info.get("admin"))
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Unknown Home Assistant user")
    return ensure_ha_user(ha_id, name, admin)


def ensure_ha_user(ha_id: str, name: str, admin: bool):
    """The Matkoll account for a Home Assistant user, created on first use."""
    u = db.q1("SELECT * FROM users WHERE ha_user_id=?", (ha_id,))
    if not u:
        base, n, username = name[:40], 1, name[:40]
        while db.q1("SELECT id FROM users WHERE username=?", (username,)):
            n += 1
            username = f"{base[:36]} {n}"
        uid = db.run("INSERT INTO users (username, pw_hash, is_admin, ha_user_id) VALUES (?, '!', ?, ?)",
                     (username, 1 if admin else 0, ha_id))
        u = db.q1("SELECT * FROM users WHERE id=?", (uid,))
    elif bool(u["is_admin"]) != admin:
        db.run("UPDATE users SET is_admin=? WHERE id=?", (1 if admin else 0, u["id"]))
        u["is_admin"] = 1 if admin else 0
    return u


def current_user(request: Request):
    u = ha_user(request)
    if u:
        return u
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Not signed in")
    u = db.q1("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?", (token,))
    if not u:
        raise HTTPException(401, "Not signed in")
    return u


def admin_user(request: Request):
    u = current_user(request)
    if not u["is_admin"]:
        raise HTTPException(403, "Only an admin can do that")
    return u


def public_user(u):
    out = {k: u[k] for k in ("id", "username", "is_admin", "kcal_goal", "protein_goal", "carbs_goal", "fat_goal")}
    out["home_assistant"] = bool(u.get("ha_user_id")) and TRUSTED_SECRET is not None
    return out


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "Expected a JSON body")
    if not isinstance(data, dict):
        raise HTTPException(400, "Expected a JSON object")
    return data


def num(v, name, minimum=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{name} must be a number")
    if f < minimum:
        raise HTTPException(400, f"{name} must be at least {minimum:g}")
    return f


def valid_date(s):
    try:
        return Date.fromisoformat(s).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(400, "Dates must look like 2026-10-14")


def valid_meal(m):
    if m not in MEALS:
        raise HTTPException(400, f"Meal must be one of {', '.join(MEALS)}")
    return m


def scaled(food: dict, grams: float) -> dict:
    return {k: round(food[k] * grams / 100, 1) for k in db.NUTRIENTS}


def food_exists(fid):
    f = db.q1("SELECT * FROM foods WHERE id=?", (fid,))
    if not f:
        raise HTTPException(404, "Food not found")
    return f


FOOD_COLS = "f.id, f.name, f.name_alt, f.brand, f.barcode, f.kcal, f.protein, f.carbs, f.fat, f.fiber, " \
            "f.serving_g, f.source, f.source_id"


def food_out(f):
    keep = ("id", "name", "name_alt", "brand", "barcode", "serving_g", "source", "source_id", *db.NUTRIENTS)
    out = {k: f.get(k) for k in keep}
    if f.get("source") == "recipe":
        r = db.q1("SELECT id FROM recipes WHERE food_id=?", (f["id"],))
        out["recipe_id"] = r["id"] if r else None
    return out


# ---------------------------------------------------------------- auth & users

async def auth_status(request: Request):
    n = db.q1("SELECT COUNT(*) AS n FROM users")["n"]
    try:
        me = public_user(current_user(request))
    except HTTPException:
        me = None
    return JSONResponse({"needs_setup": n == 0, "user": me})


def _new_session(user_id) -> Response:
    token = secrets.token_urlsafe(32)
    db.run("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    u = db.q1("SELECT * FROM users WHERE id=?", (user_id,))
    resp = JSONResponse({"user": public_user(u)})
    resp.set_cookie(COOKIE, token, max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax", secure=SECURE_COOKIE)
    return resp


def _validate_credentials(d):
    name = (d.get("username") or "").strip()
    pw = d.get("password") or ""
    if not (1 <= len(name) <= 40):
        raise HTTPException(400, "Pick a username")
    if len(pw) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    return name, pw


async def setup(request: Request):
    """Creates the first (admin) account. Only works on an empty install."""
    d = await body(request)
    if db.q1("SELECT COUNT(*) AS n FROM users")["n"] > 0:
        raise HTTPException(403, "Setup is already done")
    name, pw = _validate_credentials(d)
    uid = db.run("INSERT INTO users (username, pw_hash, is_admin) VALUES (?, ?, 1)", (name, hash_pw(pw)))
    return _new_session(uid)


async def login(request: Request):
    d = await body(request)
    u = db.q1("SELECT * FROM users WHERE username=?", ((d.get("username") or "").strip(),))
    if not u or not check_pw(d.get("password") or "", u["pw_hash"]):
        raise HTTPException(401, "Wrong username or password")
    return _new_session(u["id"])


async def logout(request: Request):
    db.run("DELETE FROM sessions WHERE token=?", (request.cookies.get(COOKIE, ""),))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


async def update_me(request: Request):
    u = current_user(request)
    d = await body(request)
    for k in ("kcal_goal", "protein_goal", "carbs_goal", "fat_goal"):
        if k in d:
            db.run(f"UPDATE users SET {k}=? WHERE id=?", (num(d[k], k), u["id"]))
    if d.get("new_password"):
        if not check_pw(d.get("password") or "", u["pw_hash"]):
            raise HTTPException(400, "Current password is wrong")
        if len(d["new_password"]) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        db.run("UPDATE users SET pw_hash=? WHERE id=?", (hash_pw(d["new_password"]), u["id"]))
    return JSONResponse({"user": public_user(db.q1("SELECT * FROM users WHERE id=?", (u["id"],)))})


async def users_list(request: Request):
    admin_user(request)
    return JSONResponse(db.q("SELECT id, username, is_admin, created FROM users ORDER BY id"))


async def users_create(request: Request):
    admin_user(request)
    d = await body(request)
    name, pw = _validate_credentials(d)
    if db.q1("SELECT id FROM users WHERE username=?", (name,)):
        raise HTTPException(400, "That username is taken")
    uid = db.run("INSERT INTO users (username, pw_hash, is_admin) VALUES (?, ?, ?)",
                 (name, hash_pw(pw), 1 if d.get("is_admin") else 0))
    return JSONResponse({"id": uid})


async def users_delete(request: Request):
    me = admin_user(request)
    uid = request.path_params["id"]
    if uid == me["id"]:
        raise HTTPException(400, "You can't delete your own account")
    db.run("DELETE FROM users WHERE id=?", (uid,))
    return JSONResponse({"ok": True})


async def users_reset_password(request: Request):
    admin_user(request)
    d = await body(request)
    if len(d.get("password") or "") < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    db.run("UPDATE users SET pw_hash=? WHERE id=?", (hash_pw(d["password"]), request.path_params["id"]))
    db.run("DELETE FROM sessions WHERE user_id=?", (request.path_params["id"],))
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------- foods

def local_search(query: str, user_id: int, limit=40, sources_filter=None):
    tokens = [t for t in query.lower().split() if t][:6]
    if not tokens:
        return []
    where = " AND ".join("f.search LIKE ?" for _ in tokens)
    args = [f"%{t}%" for t in tokens]
    if sources_filter:
        where += f" AND f.source IN ({','.join('?' * len(sources_filter))})"
        args += list(sources_filter)
    sql = f"""
        SELECT {FOOD_COLS},
               (SELECT COUNT(*) FROM entries e WHERE e.food_id = f.id AND e.user_id = ?) AS uses,
               CASE WHEN lower(f.name) LIKE ? THEN 0 ELSE 1 END AS prefix
        FROM foods f WHERE {where}
        ORDER BY uses DESC, prefix, CASE f.source WHEN 'recipe' THEN 0 WHEN 'custom' THEN 1 WHEN 'off' THEN 2
                 WHEN 'slv' THEN 3 ELSE 4 END, length(f.name)
        LIMIT ?"""
    rows = db.q(sql, [user_id, f"{tokens[0]}%", *args, limit])
    return [food_out(r) for r in rows]


async def foods_search(request: Request):
    u = current_user(request)
    qs = request.query_params.get("q", "").strip()
    return JSONResponse(local_search(qs, u["id"]))


async def foods_recent(request: Request):
    u = current_user(request)
    rows = db.q(f"""SELECT {FOOD_COLS}, e.grams AS last_grams
                    FROM (SELECT food_id, MAX(id) AS last FROM entries WHERE user_id = ?
                          GROUP BY food_id ORDER BY last DESC LIMIT 30) x
                    JOIN foods f ON f.id = x.food_id JOIN entries e ON e.id = x.last
                    ORDER BY x.last DESC""", (u["id"],))
    return JSONResponse([{**food_out(r), "last_grams": r["last_grams"]} for r in rows])


async def foods_remote(request: Request):
    """Searches USDA or Open Food Facts live. Results are not saved until one is picked."""
    current_user(request)
    source = request.path_params["source"]
    qs = request.query_params.get("q", "").strip()
    if not qs:
        return JSONResponse([])
    try:
        if source == "usda":
            res = await run_in_threadpool(sources.usda_search, qs, request.query_params.get("branded") == "1")
        elif source == "off":
            res = await run_in_threadpool(sources.off_search, qs)
        else:
            raise HTTPException(404, "Unknown source")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Search failed: {e}")
    return JSONResponse(res)


async def foods_import(request: Request):
    """Saves a remote search result into the local database and returns it."""
    u = current_user(request)
    d = await body(request)
    if d.get("source") not in ("usda", "off") or not d.get("source_id") or not d.get("name"):
        raise HTTPException(400, "Not a remote food")
    fid = db.upsert_food({**d, "created_by": u["id"]})
    return JSONResponse(food_out(db.q1("SELECT * FROM foods WHERE id=?", (fid,))))


async def foods_barcode(request: Request):
    current_user(request)
    code = "".join(ch for ch in request.path_params["code"] if ch.isdigit())
    if not 6 <= len(code) <= 14:
        raise HTTPException(400, "That doesn't look like a barcode")
    local = db.q1("SELECT * FROM foods WHERE barcode=? ORDER BY source='off', id DESC LIMIT 1", (code,))
    if local:
        return JSONResponse({"status": "ok", "food": food_out(local)})
    try:
        food, status = await run_in_threadpool(sources.off_barcode, code)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"status": "offline", "barcode": code, "error": str(e)})
    if not food:
        return JSONResponse({"status": status, "barcode": code})
    fid = db.upsert_food(food)
    return JSONResponse({"status": "ok", "food": food_out(db.q1("SELECT * FROM foods WHERE id=?", (fid,)))})


def _food_fields(d):
    name = (d.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "The food needs a name")
    f = {"name": name, "brand": (d.get("brand") or "").strip() or None,
         "barcode": "".join(ch for ch in str(d.get("barcode") or "") if ch.isdigit()) or None,
         "serving_g": num(d["serving_g"], "Serving size") if d.get("serving_g") not in (None, "") else None}
    for k in db.NUTRIENTS:
        f[k] = num(d.get(k) or 0, k)
    return f


async def foods_create(request: Request):
    u = current_user(request)
    f = _food_fields(await body(request))
    f.update(source="custom", created_by=u["id"])
    fid = db.upsert_food(f)
    return JSONResponse(food_out(db.q1("SELECT * FROM foods WHERE id=?", (fid,))))


async def foods_get(request: Request):
    current_user(request)
    return JSONResponse(food_out(food_exists(request.path_params["id"])))


async def foods_update(request: Request):
    current_user(request)
    f0 = food_exists(request.path_params["id"])
    if f0["source"] == "recipe":
        raise HTTPException(400, "Edit the recipe instead")
    f = _food_fields(await body(request))
    db.run(f"""UPDATE foods SET name=?, brand=?, barcode=?, serving_g=?, {', '.join(f'{k}=?' for k in db.NUTRIENTS)},
               search=? WHERE id=?""",
           (f["name"], f["brand"], f["barcode"], f["serving_g"], *[f[k] for k in db.NUTRIENTS],
            db.search_key(f["name"], f0.get("name_alt"), f["brand"], f["barcode"]), f0["id"]))
    return JSONResponse(food_out(food_exists(f0["id"])))


# ---------------------------------------------------------------- diary

def diary_for(user, day):
    rows = db.q(f"""SELECT e.id AS entry_id, e.meal, e.grams, e.created, {FOOD_COLS}, f.id AS food_id
                    FROM entries e JOIN foods f ON f.id = e.food_id
                    WHERE e.user_id = ? AND e.date = ? ORDER BY e.id""", (user["id"], day))
    meals = {m: {"entries": [], "totals": dict.fromkeys(db.NUTRIENTS, 0.0)} for m in MEALS}
    totals = dict.fromkeys(db.NUTRIENTS, 0.0)
    for r in rows:
        n = scaled(r, r["grams"])
        meal = meals[r["meal"]]
        meal["entries"].append({"id": r["entry_id"], "grams": r["grams"], "meal": r["meal"],
                                "food": food_out({**r, "id": r["food_id"]}), **n})
        for k in db.NUTRIENTS:
            meal["totals"][k] += n[k]
            totals[k] += n[k]
    rnd = lambda d: {k: round(v, 1) for k, v in d.items()}  # noqa: E731
    for m in meals.values():
        m["totals"] = rnd(m["totals"])
    return {"date": day, "meals": meals, "totals": rnd(totals),
            "goals": {k: user[f"{k}_goal"] for k in ("kcal", "protein", "carbs", "fat")}}


async def diary_get(request: Request):
    u = current_user(request)
    day = valid_date(request.query_params.get("date") or Date.today().isoformat())
    return JSONResponse(diary_for(u, day))


async def diary_history(request: Request):
    u = current_user(request)
    end = valid_date(request.query_params.get("end") or Date.today().isoformat())
    days = min(int(request.query_params.get("days", 14)), 120)
    start = (Date.fromisoformat(end) - timedelta(days=days - 1)).isoformat()
    rows = db.q("""SELECT e.date, ROUND(SUM(f.kcal * e.grams / 100), 0) AS kcal,
                          ROUND(SUM(f.protein * e.grams / 100), 1) AS protein
                   FROM entries e JOIN foods f ON f.id = e.food_id
                   WHERE e.user_id = ? AND e.date BETWEEN ? AND ? GROUP BY e.date""", (u["id"], start, end))
    by = {r["date"]: r for r in rows}
    out = []
    for i in range(days):
        d = (Date.fromisoformat(start) + timedelta(days=i)).isoformat()
        out.append({"date": d, "kcal": by.get(d, {}).get("kcal") or 0, "protein": by.get(d, {}).get("protein") or 0})
    return JSONResponse({"days": out, "goal": u["kcal_goal"]})


async def entries_create(request: Request):
    u = current_user(request)
    d = await body(request)
    items = d.get("items") if isinstance(d.get("items"), list) else [d]
    ids = []
    for it in items:
        food_exists(it.get("food_id"))
        ids.append(db.run("INSERT INTO entries (user_id, date, meal, food_id, grams) VALUES (?,?,?,?,?)",
                          (u["id"], valid_date(it.get("date")), valid_meal(it.get("meal")), it["food_id"],
                           num(it.get("grams"), "Amount", 0.1))))
    return JSONResponse({"ids": ids})


def _own_entry(request, u):
    e = db.q1("SELECT * FROM entries WHERE id=? AND user_id=?", (request.path_params["id"], u["id"]))
    if not e:
        raise HTTPException(404, "Entry not found")
    return e


async def entries_update(request: Request):
    u = current_user(request)
    e = _own_entry(request, u)
    d = await body(request)
    db.run("UPDATE entries SET grams=?, meal=?, date=? WHERE id=?",
           (num(d.get("grams", e["grams"]), "Amount", 0.1), valid_meal(d.get("meal", e["meal"])),
            valid_date(d.get("date", e["date"])), e["id"]))
    return JSONResponse({"ok": True})


async def entries_delete(request: Request):
    u = current_user(request)
    e = _own_entry(request, u)
    db.run("DELETE FROM entries WHERE id=?", (e["id"],))
    return JSONResponse({"ok": True})


async def diary_copy(request: Request):
    """Copies a day's (or one meal's) entries to another day, e.g. 'same breakfast as yesterday'."""
    u = current_user(request)
    d = await body(request)
    src, dst = valid_date(d.get("from")), valid_date(d.get("to"))
    args = [u["id"], dst, u["id"], src]
    extra = ""
    if d.get("meal"):
        extra = " AND meal = ?"
        args.append(valid_meal(d["meal"]))
    db.run(f"""INSERT INTO entries (user_id, date, meal, food_id, grams)
               SELECT ?, ?, meal, food_id, grams FROM entries WHERE user_id = ? AND date = ?{extra} ORDER BY id""",
           args)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------- recipes

def recipe_calc(recipe_id):
    r = db.q1("SELECT * FROM recipes WHERE id=?", (recipe_id,))
    if not r:
        raise HTTPException(404, "Recipe not found")
    items = db.q(f"""SELECT ri.id AS item_id, ri.grams, {FOOD_COLS} FROM recipe_items ri
                     JOIN foods f ON f.id = ri.food_id WHERE ri.recipe_id = ? ORDER BY ri.position, ri.id""",
                 (recipe_id,))
    totals = dict.fromkeys(db.NUTRIENTS, 0.0)
    out_items = []
    for it in items:
        n = scaled(it, it["grams"])
        for k in db.NUTRIENTS:
            totals[k] += n[k]
        out_items.append({"id": it["item_id"], "grams": it["grams"], "food": food_out(it), **n})
    raw = sum(it["grams"] for it in items)
    weight = r["final_weight_g"] or raw
    per100 = {k: round(v / weight * 100, 2) if weight else 0 for k, v in totals.items()}
    return {**r, "items": out_items, "raw_weight_g": raw, "weight_g": weight,
            "totals": {k: round(v, 1) for k, v in totals.items()}, "per100": per100,
            "kcal_per_g": round(totals["kcal"] / weight, 3) if weight else 0,
            "serving_g": round(weight / r["servings"], 1) if r["servings"] else None}


def recipe_save(recipe_id, d, user_id):
    name = (d.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "The recipe needs a name")
    items = d.get("items") or []
    if not items:
        raise HTTPException(400, "Add at least one ingredient")
    servings = num(d.get("servings") or 1, "Servings", 0.1)
    final = d.get("final_weight_g")
    final = num(final, "Cooked weight", 1) if final not in (None, "", 0, "0") else None
    c = db.conn()
    if recipe_id is None:
        recipe_id = c.execute(
            "INSERT INTO recipes (name, notes, servings, final_weight_g, created_by, source_url, mealie_id, mealie_slug) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (name, d.get("notes") or "", servings, final, user_id, d.get("source_url") or None,
             d.get("mealie_id") or None, d.get("mealie_slug") or None)).lastrowid
    else:
        c.execute("UPDATE recipes SET name=?, notes=?, servings=?, final_weight_g=?, updated=datetime('now') "
                  "WHERE id=?", (name, d.get("notes") or "", servings, final, recipe_id))
        c.execute("DELETE FROM recipe_items WHERE recipe_id=?", (recipe_id,))
    for i, it in enumerate(items):
        if not c.execute("SELECT 1 FROM foods WHERE id=?", (it.get("food_id"),)).fetchone():
            c.rollback()
            raise HTTPException(400, "An ingredient no longer exists")
        own = c.execute("SELECT food_id FROM recipes WHERE id=?", (recipe_id,)).fetchone()["food_id"]
        if own and it["food_id"] == own:
            c.rollback()
            raise HTTPException(400, "A recipe can't contain itself")
        c.execute("INSERT INTO recipe_items (recipe_id, food_id, grams, position) VALUES (?,?,?,?)",
                  (recipe_id, it["food_id"], num(it.get("grams"), "Ingredient amount", 0.1), i))
    c.commit()
    calc = recipe_calc(recipe_id)
    # Every recipe has a matching food row so it can be logged, planned and nested like any other food.
    fid = db.upsert_food({"name": name, "brand": "Recipe", **calc["per100"], "serving_g": calc["serving_g"],
                          "source": "recipe", "source_id": f"r{recipe_id}", "created_by": user_id})
    db.run("UPDATE recipes SET food_id=? WHERE id=?", (fid, recipe_id))
    refresh_parents(fid)
    mealie_id = db.q1("SELECT mealie_id FROM recipes WHERE id=?", (recipe_id,))["mealie_id"]
    if mealie_id:
        placeholder = db.q1("SELECT id FROM foods WHERE source='mealie' AND source_id=?", (mealie_id,))
        if placeholder:
            db.run("UPDATE plan SET food_id=?, grams=? WHERE food_id=?",
                   (fid, calc["serving_g"] or 300, placeholder["id"]))
    return recipe_calc(recipe_id)


def refresh_parents(food_id, seen=None):
    """A recipe used inside other recipes changed: recompute those so their numbers stay right."""
    seen = seen or set()
    for p in db.q("SELECT DISTINCT r.id, r.name, r.food_id FROM recipe_items ri JOIN recipes r ON r.id = ri.recipe_id "
                  "WHERE ri.food_id = ?", (food_id,)):
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        calc = recipe_calc(p["id"])
        db.upsert_food({"name": p["name"], "brand": "Recipe", **calc["per100"], "serving_g": calc["serving_g"],
                        "source": "recipe", "source_id": f"r{p['id']}"})
        if p["food_id"]:
            refresh_parents(p["food_id"], seen)


async def recipes_list(request: Request):
    current_user(request)
    rows = db.q("""SELECT r.id, r.name, r.servings, r.food_id, f.kcal AS kcal_per100, f.serving_g, r.mealie_slug, r.source_url,
                          (SELECT COUNT(*) FROM recipe_items WHERE recipe_id = r.id) AS n_items
                   FROM recipes r LEFT JOIN foods f ON f.id = r.food_id ORDER BY r.updated DESC""")
    return JSONResponse(rows)


async def recipes_get(request: Request):
    current_user(request)
    return JSONResponse(recipe_calc(request.path_params["id"]))


async def recipes_create(request: Request):
    u = current_user(request)
    return JSONResponse(recipe_save(None, await body(request), u["id"]))


async def recipes_update(request: Request):
    u = current_user(request)
    recipe_calc(request.path_params["id"])
    return JSONResponse(recipe_save(request.path_params["id"], await body(request), u["id"]))


async def recipes_delete(request: Request):
    current_user(request)
    r = db.q1("SELECT * FROM recipes WHERE id=?", (request.path_params["id"],))
    if not r:
        raise HTTPException(404, "Recipe not found")
    db.run("DELETE FROM recipes WHERE id=?", (r["id"],))
    # The food row stays (renamed) when diary entries still point at it, so old days keep their numbers.
    if r["food_id"]:
        used = db.q1("""SELECT (SELECT COUNT(*) FROM entries WHERE food_id=?) + (SELECT COUNT(*) FROM plan WHERE food_id=?)
                        + (SELECT COUNT(*) FROM recipe_items WHERE food_id=?) AS n""", (r["food_id"],) * 3)["n"]
        if used:
            db.run("UPDATE foods SET source='custom', source_id=NULL, brand='Deleted recipe' WHERE id=?", (r["food_id"],))
        else:
            db.run("DELETE FROM foods WHERE id=?", (r["food_id"],))
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------- meal plan (shared by the household)

async def plan_get(request: Request):
    current_user(request)
    start = valid_date(request.query_params.get("start") or Date.today().isoformat())
    days = min(int(request.query_params.get("days", 7)), 31)
    end = (Date.fromisoformat(start) + timedelta(days=days - 1)).isoformat()
    rows = db.q(f"""SELECT p.id AS plan_id, p.date, p.meal, p.grams, p.note, p.origin, u.username AS added_by, {FOOD_COLS}, f.id AS food_id
                    FROM plan p JOIN foods f ON f.id = p.food_id LEFT JOIN users u ON u.id = p.created_by
                    WHERE p.date BETWEEN ? AND ? ORDER BY p.date, p.id""", (start, end))
    out = {}
    for i in range(days):
        d = (Date.fromisoformat(start) + timedelta(days=i)).isoformat()
        out[d] = {m: [] for m in MEALS}
    for r in rows:
        out[r["date"]][r["meal"]].append({"id": r["plan_id"], "grams": r["grams"], "note": r["note"], "meal": r["meal"],
                                          "origin": r["origin"],
                                          "added_by": r["added_by"], "food": food_out({**r, "id": r["food_id"]}),
                                          **scaled(r, r["grams"])})
    return JSONResponse({"start": start, "days": out, "mealie": mealie.configured() and mealie.config()["sync"]})


async def plan_create(request: Request):
    u = current_user(request)
    d = await body(request)
    food_exists(d.get("food_id"))
    pid = db.run("INSERT INTO plan (date, meal, food_id, grams, note, created_by) VALUES (?,?,?,?,?,?)",
                 (valid_date(d.get("date")), valid_meal(d.get("meal")), d["food_id"],
                  num(d.get("grams"), "Amount", 0.1), (d.get("note") or "")[:200], u["id"]))
    in_background(mealie_push_item, pid)
    return JSONResponse({"id": pid})


async def plan_update(request: Request):
    current_user(request)
    p = db.q1("SELECT * FROM plan WHERE id=?", (request.path_params["id"],))
    if not p:
        raise HTTPException(404, "Plan item not found")
    d = await body(request)
    db.run("UPDATE plan SET date=?, meal=?, grams=?, note=? WHERE id=?",
           (valid_date(d.get("date", p["date"])), valid_meal(d.get("meal", p["meal"])),
            num(d.get("grams", p["grams"]), "Amount", 0.1), (d.get("note", p["note"]) or "")[:200], p["id"]))
    if p["mealie_id"] and (d.get("date", p["date"]) != p["date"] or d.get("meal", p["meal"]) != p["meal"]):
        in_background(mealie_repush_item, p["id"], p["mealie_id"])
    return JSONResponse({"ok": True})


async def plan_delete(request: Request):
    current_user(request)
    p = db.q1("SELECT * FROM plan WHERE id=?", (request.path_params["id"],))
    db.run("DELETE FROM plan WHERE id=?", (request.path_params["id"],))
    if p and p["mealie_id"]:
        in_background(mealie_delete_entry, p["mealie_id"])
    return JSONResponse({"ok": True})


async def plan_log(request: Request):
    """Logs planned items into the signed-in user's diary. Body: {ids: [...]} or {date, meal?}."""
    u = current_user(request)
    d = await body(request)
    if d.get("ids"):
        ids = [int(i) for i in d["ids"]]
        rows = db.q(f"SELECT * FROM plan WHERE id IN ({','.join('?' * len(ids))})", ids)
    else:
        args = [valid_date(d.get("date"))]
        extra = ""
        if d.get("meal"):
            extra = " AND meal=?"
            args.append(valid_meal(d["meal"]))
        rows = db.q(f"SELECT * FROM plan WHERE date=?{extra} ORDER BY id", args)
    grams = d.get("grams") or {}
    for r in rows:
        g = num(grams.get(str(r["id"]), r["grams"]), "Amount", 0.1)
        db.run("INSERT INTO entries (user_id, date, meal, food_id, grams) VALUES (?,?,?,?,?)",
               (u["id"], r["date"], r["meal"], r["food_id"], g))
    return JSONResponse({"logged": len(rows)})


# ---------------------------------------------------------------- Mealie meal plan sync (both ways)

MEAL_TO_MEALIE = {"breakfast": "breakfast", "lunch": "lunch", "dinner": "dinner", "snack": "snack"}
MEALIE_TO_MEAL = {"breakfast": "breakfast", "lunch": "lunch", "dinner": "dinner", "snack": "snack",
                  "side": "dinner", "dessert": "dinner", "drink": "snack"}
sync_status = {"state": "idle", "last": None, "error": None, "pulled": 0, "pushed": 0, "removed": 0}
_sync_lock = threading.Lock()


def in_background(fn, *args):
    def run():
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001 - best effort; the periodic sync retries
            sync_status["error"] = str(e)
    threading.Thread(target=run, daemon=True).start()


def _sync_on():
    return mealie.configured() and mealie.config()["sync"]


def mealie_push_item(plan_id):
    """Sends one Matkoll plan item to Mealie, as a recipe link when the dish came from Mealie."""
    if not _sync_on():
        return
    p = db.q1("SELECT p.*, f.name, f.source, f.source_id FROM plan p JOIN foods f ON f.id = p.food_id WHERE p.id=?",
              (plan_id,))
    if not p or p["mealie_id"]:
        return
    recipe_id = None
    if p["source"] == "recipe":
        r = db.q1("SELECT mealie_id FROM recipes WHERE food_id=?", (p["food_id"],))
        recipe_id = r["mealie_id"] if r else None
    elif p["source"] == "mealie":
        recipe_id = p["source_id"]
    mid = mealie.create_mealplan(p["date"], MEAL_TO_MEALIE[p["meal"]], recipe_id=recipe_id,
                                 title="" if recipe_id else p["name"],
                                 text="" if recipe_id else f"{round(p['grams'])} g per person")
    if mid is not None:
        db.run("UPDATE plan SET mealie_id=? WHERE id=?", (mid, plan_id))


def mealie_repush_item(plan_id, old_mealie_id):
    mealie_delete_entry(old_mealie_id)
    db.run("UPDATE plan SET mealie_id=NULL, origin='matkoll' WHERE id=?", (plan_id,))
    mealie_push_item(plan_id)


def mealie_delete_entry(mealie_id):
    if _sync_on():
        try:
            mealie.delete_mealplan(mealie_id)
        except mealie.MealieError as e:
            if "404" not in str(e):
                raise


def _mealie_entry_food(entry):
    """Finds or creates the food a Mealie plan entry stands for. Returns (food_id, grams per person)."""
    recipe_id = mealie.g(entry, "recipeId", "recipe_id")
    if recipe_id:
        r = db.q1("SELECT r.food_id, f.serving_g FROM recipes r JOIN foods f ON f.id = r.food_id WHERE r.mealie_id=?",
                  (str(recipe_id),))
        if r:
            return r["food_id"], r["serving_g"] or 300
        f = db.q1("SELECT id, serving_g FROM foods WHERE source='mealie' AND source_id=?", (str(recipe_id),))
        if f:
            return f["id"], f["serving_g"] or 100
        summary = mealie.g(entry, "recipe") or {}
        name = mealie.g(summary, "name", default="Recipe from Mealie")
        nutrition = None
        slug = mealie.g(summary, "slug")
        if slug:
            try:
                nutrition = mealie.nutrition_per_serving(mealie.get_recipe(slug))
            except mealie.MealieError:
                pass
        # Not imported into Matkoll yet: one Mealie portion stands in as "100 g", using Mealie's own
        # nutrition per serving when it has any. Importing the recipe gives exact numbers.
        fid = db.upsert_food({
            "name": f"{name} (1 portion)", "brand": "Mealie – import for exact calories",
            **{k: (nutrition or {}).get(k) or 0 for k in db.NUTRIENTS},
            "serving_g": 100, "source": "mealie", "source_id": str(recipe_id),
        })
        return fid, 100
    title = (mealie.g(entry, "title", default="") or "Meal from Mealie").strip()
    fid = db.upsert_food({"name": title, "brand": "Mealie note", "serving_g": 100,
                          "source": "mealie", "source_id": "note:" + title.lower()[:80]})
    return fid, 100


def mealie_sync(start: str, end: str):
    """Pulls Mealie's plan into Matkoll's, removes what was deleted there, then pushes Matkoll-only items."""
    if not mealie.configured():
        raise mealie.MealieError("Mealie isn't connected.")
    with _sync_lock:
        sync_status.update(state="running", error=None)
        pulled = pushed = removed = 0
        try:
            entries = mealie.mealplans(start, end)
            seen = set()
            for e in entries:
                eid = mealie.g(e, "id")
                if eid is None:
                    continue
                seen.add(int(eid))
                day = str(mealie.g(e, "date", default=""))[:10]
                meal = MEALIE_TO_MEAL.get(mealie.g(e, "entryType", "entry_type", default="dinner"), "dinner")
                existing = db.q1("SELECT * FROM plan WHERE mealie_id=?", (int(eid),))
                if existing:
                    if existing["date"] != day or existing["meal"] != meal:
                        db.run("UPDATE plan SET date=?, meal=? WHERE id=?", (day, meal, existing["id"]))
                    continue
                food_id, grams = _mealie_entry_food(e)
                db.run("INSERT INTO plan (date, meal, food_id, grams, note, mealie_id, origin) "
                       "VALUES (?,?,?,?,?,?, 'mealie')",
                       (day, meal, food_id, grams, (mealie.g(e, "text", default="") or "")[:200], int(eid)))
                pulled += 1
            for r in db.q("SELECT id, mealie_id FROM plan WHERE mealie_id IS NOT NULL AND date BETWEEN ? AND ?",
                          (start, end)):
                if r["mealie_id"] not in seen:
                    db.run("DELETE FROM plan WHERE id=?", (r["id"],))
                    removed += 1
            if mealie.config()["sync"]:
                for r in db.q("SELECT id FROM plan WHERE mealie_id IS NULL AND origin='matkoll' "
                              "AND date BETWEEN ? AND ?", (start, end)):
                    mealie_push_item(r["id"])
                    pushed += 1
            sync_status.update(state="done", last=time.strftime("%Y-%m-%d %H:%M"),
                               pulled=pulled, pushed=pushed, removed=removed)
        except Exception as e:
            sync_status.update(state="error", error=str(e))
            raise
    return dict(sync_status)


def _sync_window():
    today = Date.today()
    return (today - timedelta(days=7)).isoformat(), (today + timedelta(days=28)).isoformat()


_stop = threading.Event()


def _sync_loop():
    while not _stop.wait(60):
        try:
            if _sync_on() and time.time() - _sync_loop.last >= 15 * 60:
                _sync_loop.last = time.time()
                mealie_sync(*_sync_window())
        except Exception:  # noqa: BLE001 - shown in settings via sync_status
            pass


_sync_loop.last = 0


async def mealie_sync_now(request: Request):
    current_user(request)
    try:
        st = await run_in_threadpool(mealie_sync, *_sync_window())
    except mealie.MealieError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(st)


async def mealie_status(request: Request):
    current_user(request)
    c = mealie.config()
    return JSONResponse({"configured": mealie.configured(), "sync": c["sync"], "url": c["url"], "status": sync_status})


async def mealie_check(request: Request):
    admin_user(request)
    try:
        return JSONResponse(await run_in_threadpool(mealie.check))
    except mealie.MealieError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- recipe import (links and Mealie)

def find_matches(name: str, user_id: int, limit=6):
    found = []
    for term in ingredients.search_terms(name):
        for f in local_search(term, user_id, limit=limit, sources_filter=("slv", "custom", "recipe", "off", "usda")):
            if f["id"] not in {x["id"] for x in found}:
                found.append(f)
        if len(found) >= 3:
            break
    return found[:limit]


def build_import(name, servings, lines, user_id, **meta):
    """lines: [{text, food?, qty?, unit?}] -> review data with gram estimates and food suggestions."""
    items = []
    for ln in lines:
        text = (ln.get("text") or "").strip()
        if ln.get("food"):
            q = ln.get("qty")
            guess = f"{q if q else ''} {ln.get('unit') or ''} {ln['food']}".strip() if (q or ln.get("unit")) else text
            parsed = ingredients.parse_line(guess or ln["food"])
            parsed["name"] = ln["food"]
            parsed["line"] = text or parsed["line"]
        else:
            if not text:
                continue
            parsed = ingredients.parse_line(text)
        if not parsed["name"]:
            continue
        matches = find_matches(parsed["name"], user_id)
        items.append({**parsed, "matches": matches, "food_id": matches[0]["id"] if matches else None,
                      "skip": ingredients.is_negligible(parsed["name"])})
    try:
        servings = max(1, int(float(servings))) if servings else 4
    except (TypeError, ValueError):
        servings = 4
    return {"name": name or "Imported recipe", "servings": servings, "items": items, **meta}


def _walk_ld(node):
    if isinstance(node, list):
        for x in node:
            yield from _walk_ld(x)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _walk_ld(node[key])


def extract_recipe(html: str):
    """Finds schema.org Recipe data (JSON-LD), which most recipe sites publish for search engines."""
    for m in re.finditer(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        for node in _walk_ld(data):
            t = node.get("@type")
            if "Recipe" in (t if isinstance(t, list) else [t]):
                return node
    return None


def _servings_from(y):
    if isinstance(y, list):
        y = next((v for v in y if v), None)
    m = re.search(r"\d+", str(y or ""))
    return int(m.group(0)) if m else None


def _import_mealie_recipe(slug, user_id, source_url=None):
    rec = mealie.get_recipe(slug)
    servings = mealie.g(rec, "recipeServings", "recipe_servings") or \
        mealie.g(rec, "recipeYieldQuantity", "recipe_yield_quantity") or \
        _servings_from(mealie.g(rec, "recipeYield", "recipe_yield"))
    return build_import(mealie.g(rec, "name"), servings, mealie.ingredient_lines(rec), user_id,
                        mealie_id=str(mealie.g(rec, "id") or ""), mealie_slug=mealie.g(rec, "slug", default=slug),
                        source_url=source_url or mealie.g(rec, "orgURL", "org_url"),
                        nutrition=mealie.nutrition_per_serving(rec))


async def import_url(request: Request):
    u = current_user(request)
    d = await body(request)
    url = (d.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(400, "Paste the full link to the recipe page, starting with https://")
    if d.get("via_mealie") and mealie.configured():
        try:
            slug = await run_in_threadpool(mealie.create_from_url, url)
            return JSONResponse(await run_in_threadpool(_import_mealie_recipe, slug, u["id"], url))
        except mealie.MealieError as e:
            raise HTTPException(400, str(e))

    def fetch():
        import requests
        r = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Matkoll/1.0; recipe import)",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8"})
        r.raise_for_status()
        return r.text
    try:
        html = await run_in_threadpool(fetch)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Couldn't open that page: {e}")
    rec = extract_recipe(html)
    if not rec or not rec.get("recipeIngredient"):
        hint = " Turn on 'Save in Mealie too' and Mealie will read it instead." if mealie.configured() else ""
        raise HTTPException(400, "Couldn't find a recipe on that page." + hint)
    n = rec.get("nutrition") or {}
    nutrition = None
    if n.get("calories"):
        m = re.search(r"\d+(?:[.,]\d+)?", str(n["calories"]))
        nutrition = {"kcal": float(m.group(0).replace(",", "."))} if m else None
    lines = [{"text": re.sub(r"<[^>]+>", "", str(x))} for x in rec.get("recipeIngredient") or []]
    return JSONResponse(build_import(rec.get("name"), _servings_from(rec.get("recipeYield")), lines, u["id"],
                                     source_url=url, nutrition=nutrition))


async def mealie_recipes(request: Request):
    current_user(request)
    try:
        return JSONResponse(await run_in_threadpool(mealie.list_recipes, request.query_params.get("q", "")))
    except mealie.MealieError as e:
        raise HTTPException(400, str(e))


async def mealie_import(request: Request):
    u = current_user(request)
    d = await body(request)
    if not d.get("slug"):
        raise HTTPException(400, "Pick a recipe")
    try:
        return JSONResponse(await run_in_threadpool(_import_mealie_recipe, d["slug"], u["id"]))
    except mealie.MealieError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- photo logging

async def photo_analyze(request: Request):
    u = current_user(request)
    form = await request.form()
    upload = form.get("image")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(400, "Attach a photo")
    data = await upload.read()
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "Photo is too large (max 12 MB)")
    mime = upload.content_type if upload.content_type in ("image/jpeg", "image/png", "image/webp") else "image/jpeg"
    try:
        result = await run_in_threadpool(ai.analyze, data, mime, form.get("provider") or "", form.get("note") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Photo analysis failed: {e}")
    for it in result["items"]:
        matches = []
        for name in (it["name_sv"], it["name"]):
            if name:
                for m in local_search(name, u["id"], limit=4, sources_filter=("slv", "custom", "recipe", "usda", "off")):
                    if m["id"] not in {x["id"] for x in matches}:
                        matches.append(m)
        it["matches"] = matches[:5]
    return JSONResponse(result)


async def photo_log(request: Request):
    """Body: {date, meal, items: [{food_id?} | {name, kcal, protein, carbs, fat}, grams]}."""
    u = current_user(request)
    d = await body(request)
    day, meal = valid_date(d.get("date")), valid_meal(d.get("meal"))
    n = 0
    for it in d.get("items") or []:
        grams = num(it.get("grams"), "Amount", 0.1)
        if it.get("food_id"):
            fid = food_exists(it["food_id"])["id"]
        else:
            name = (it.get("name") or "").strip()
            if not name:
                raise HTTPException(400, "Each item needs a name")
            fid = db.upsert_food({"name": name, "brand": "Photo estimate", "source": "photo", "created_by": u["id"],
                                  **{k: num(it.get(k) or 0, k) for k in db.NUTRIENTS}})
        db.run("INSERT INTO entries (user_id, date, meal, food_id, grams) VALUES (?,?,?,?,?)",
               (u["id"], day, meal, fid, grams))
        n += 1
    return JSONResponse({"logged": n})


# ---------------------------------------------------------------- settings

async def settings_get(request: Request):
    u = current_user(request)
    cfg = ai.config()
    out = {"photo_providers": ai.available(cfg), "default_provider": cfg["ai_provider"],
           "slv": {**sources.slv_status, "imported": db.get_setting("slv_imported"),
                   "count": db.q1("SELECT COUNT(*) AS n FROM foods WHERE source='slv'")["n"]}}
    mc = mealie.config()
    out["mealie"] = {"configured": mealie.configured(), "sync": mc["sync"], "status": sync_status}
    if u["is_admin"]:
        out["ai"] = {k: ("••••" + v[-4:] if k in ai.SECRET_KEYS and v else v) for k, v in cfg.items()}
        key = db.get_setting("usda_api_key") or os.environ.get("USDA_API_KEY") or ""
        out["usda_api_key"] = "••••" + key[-4:] if key else ""
        out["mealie"].update(url=mc["url"], token="••••" + mc["token"][-4:] if mc["token"] else "")
    return JSONResponse(out)


async def settings_update(request: Request):
    admin_user(request)
    d = await body(request)
    for k in ai.DEFAULTS:
        if k in d:
            v = str(d[k] or "").strip()
            if k in ai.SECRET_KEYS and v.startswith("••••"):
                continue  # unchanged masked value
            if k == "ai_provider" and v not in ai.PROVIDERS:
                raise HTTPException(400, "Unknown provider")
            db.set_setting(k, v)
    if "usda_api_key" in d and not str(d["usda_api_key"]).startswith("••••"):
        db.set_setting("usda_api_key", str(d["usda_api_key"] or "").strip())
    if "mealie_url" in d:
        url = str(d["mealie_url"] or "").strip().rstrip("/")
        if url and not re.match(r"^https?://", url):
            url = "http://" + url
        db.set_setting("mealie_url", url)
    if "mealie_token" in d and not str(d["mealie_token"]).startswith("••••"):
        db.set_setting("mealie_token", str(d["mealie_token"] or "").strip())
    if "mealie_sync" in d:
        db.set_setting("mealie_sync", "1" if d["mealie_sync"] in (True, "1", "on", 1) else "0")
    return await settings_get(request)


async def slv_import(request: Request):
    admin_user(request)
    sources.start_slv_import()
    return JSONResponse(sources.slv_status)


async def ollama_models(request: Request):
    admin_user(request)
    url = (request.query_params.get("url") or ai.config()["ollama_url"]).rstrip("/")
    try:
        import requests
        r = await run_in_threadpool(requests.get, f"{url}/api/tags", timeout=8)
        r.raise_for_status()
        return JSONResponse([m["name"] for m in r.json().get("models", [])])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Couldn't reach Ollama at {url}: {e}")


async def export_csv(request: Request):
    u = current_user(request)
    rows = db.q("""SELECT e.date, e.meal, f.name, f.brand, e.grams, ROUND(f.kcal*e.grams/100,1) AS kcal,
                          ROUND(f.protein*e.grams/100,1) AS protein, ROUND(f.carbs*e.grams/100,1) AS carbs,
                          ROUND(f.fat*e.grams/100,1) AS fat
                   FROM entries e JOIN foods f ON f.id=e.food_id WHERE e.user_id=? ORDER BY e.date, e.id""", (u["id"],))
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["date", "meal", "name", "brand", "grams", "kcal", "protein", "carbs", "fat"])
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="matkoll-{u["username"]}.csv"'})


# ---------------------------------------------------------------- used by the Home Assistant integration

def summary_all(day: str | None = None):
    """Today's totals and goals for every user, for Home Assistant sensors."""
    day = day or Date.today().isoformat()
    users = db.q("SELECT * FROM users ORDER BY id")
    totals = {r["user_id"]: r for r in db.q(
        """SELECT e.user_id, SUM(f.kcal*e.grams/100) AS kcal, SUM(f.protein*e.grams/100) AS protein,
                  SUM(f.carbs*e.grams/100) AS carbs, SUM(f.fat*e.grams/100) AS fat,
                  SUM(f.fiber*e.grams/100) AS fiber, COUNT(*) AS entries
           FROM entries e JOIN foods f ON f.id = e.food_id WHERE e.date = ? GROUP BY e.user_id""", (day,))}
    out = []
    for u in users:
        t = totals.get(u["id"], {})
        kcal = round(t.get("kcal") or 0)
        out.append({
            "id": u["id"], "username": u["username"], "ha_user_id": u.get("ha_user_id"),
            "kcal": kcal, "kcal_goal": u["kcal_goal"], "kcal_left": round(u["kcal_goal"] - kcal),
            **{k: round(t.get(k) or 0, 1) for k in ("protein", "carbs", "fat", "fiber")},
            "protein_goal": u["protein_goal"], "carbs_goal": u["carbs_goal"], "fat_goal": u["fat_goal"],
            "entries": t.get("entries") or 0,
        })
    return {"date": day, "users": out, "plan": plan_range(day, day)}


def plan_range(start: str, end: str):
    """Planned meals between two dates (inclusive), for the Home Assistant calendar."""
    rows = db.q("""SELECT p.id, p.date, p.meal, p.grams, p.note, p.origin, f.name, f.kcal
                   FROM plan p JOIN foods f ON f.id = p.food_id
                   WHERE p.date BETWEEN ? AND ? ORDER BY p.date, p.id""", (start, end))
    return [{**r, "kcal": round(r["kcal"] * r["grams"] / 100)} for r in rows]


def default_meal_now():
    h = time.localtime().tm_hour
    return "breakfast" if h < 10 else "lunch" if h < 14 else "snack" if h < 17 else "dinner" if h < 21 else "snack"


def log_food_for(user_id: int, food: str, grams: float, meal: str | None = None, day: str | None = None):
    """Logs food by name or barcode, e.g. from a Home Assistant action or voice. Returns what was logged."""
    if grams is None or float(grams) <= 0:
        raise ValueError("Amount must be more than 0 grams")
    food = (food or "").strip()
    if not food:
        raise ValueError("Say which food to log")
    digits = "".join(ch for ch in food if ch.isdigit())
    f = None
    if len(digits) >= 8 and len(digits) == len(food.replace(" ", "")):
        f = db.q1("SELECT * FROM foods WHERE barcode=? LIMIT 1", (digits,))
        if not f:
            found, _ = sources.off_barcode(digits)
            if found:
                f = db.q1("SELECT * FROM foods WHERE id=?", (db.upsert_food(found),))
    if not f:
        matches = local_search(food, user_id, limit=1)
        if not matches:
            for term in ingredients.search_terms(food):
                matches = local_search(term, user_id, limit=1)
                if matches:
                    break
        if not matches:
            raise ValueError(f"No food matching '{food}'")
        f = db.q1("SELECT * FROM foods WHERE id=?", (matches[0]["id"],))
    meal = meal or default_meal_now()
    if meal not in MEALS:
        raise ValueError(f"Meal must be one of {', '.join(MEALS)}")
    day = day or Date.today().isoformat()
    db.run("INSERT INTO entries (user_id, date, meal, food_id, grams) VALUES (?,?,?,?,?)",
           (user_id, day, meal, f["id"], float(grams)))
    return {"food": f["name"], "grams": float(grams), "meal": meal, "date": day, **scaled(f, float(grams))}


# ---------------------------------------------------------------- app

async def index(request: Request):
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})


async def sw(request: Request):
    return FileResponse(os.path.join(STATIC, "sw.js"), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


async def health(request: Request):
    return JSONResponse({"ok": True})


async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def startup():
    db.init()
    if os.environ.get("AUTO_IMPORT_SLV", "1") == "1" and not db.get_setting("slv_imported"):
        sources.start_slv_import()
    _stop.clear()
    threading.Thread(target=_sync_loop, daemon=True, name="matkoll-mealie-sync").start()


def shutdown():
    _stop.set()


@asynccontextmanager
async def lifespan(app):
    startup()
    yield
    shutdown()


I = "{id:int}"
routes = [
    Route("/", index),
    Route("/sw.js", sw),
    Route("/health", health),
    Route("/api/auth", auth_status),
    Route("/api/auth/setup", setup, methods=["POST"]),
    Route("/api/auth/login", login, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]),
    Route("/api/me", update_me, methods=["PUT"]),
    Route("/api/users", users_list),
    Route("/api/users", users_create, methods=["POST"]),
    Route(f"/api/users/{I}", users_delete, methods=["DELETE"]),
    Route(f"/api/users/{I}/password", users_reset_password, methods=["PUT"]),
    Route("/api/foods/search", foods_search),
    Route("/api/foods/recent", foods_recent),
    Route("/api/foods/remote/{source}", foods_remote),
    Route("/api/foods/import", foods_import, methods=["POST"]),
    Route("/api/foods/barcode/{code}", foods_barcode),
    Route("/api/foods", foods_create, methods=["POST"]),
    Route(f"/api/foods/{I}", foods_get),
    Route(f"/api/foods/{I}", foods_update, methods=["PUT"]),
    Route("/api/diary", diary_get),
    Route("/api/diary/history", diary_history),
    Route("/api/diary/copy", diary_copy, methods=["POST"]),
    Route("/api/entries", entries_create, methods=["POST"]),
    Route(f"/api/entries/{I}", entries_update, methods=["PUT"]),
    Route(f"/api/entries/{I}", entries_delete, methods=["DELETE"]),
    Route("/api/recipes", recipes_list),
    Route("/api/recipes", recipes_create, methods=["POST"]),
    Route(f"/api/recipes/{I}", recipes_get),
    Route(f"/api/recipes/{I}", recipes_update, methods=["PUT"]),
    Route(f"/api/recipes/{I}", recipes_delete, methods=["DELETE"]),
    Route("/api/plan", plan_get),
    Route("/api/plan", plan_create, methods=["POST"]),
    Route("/api/plan/log", plan_log, methods=["POST"]),
    Route(f"/api/plan/{I}", plan_update, methods=["PUT"]),
    Route(f"/api/plan/{I}", plan_delete, methods=["DELETE"]),
    Route("/api/import/url", import_url, methods=["POST"]),
    Route("/api/mealie/status", mealie_status),
    Route("/api/mealie/check", mealie_check),
    Route("/api/mealie/recipes", mealie_recipes),
    Route("/api/mealie/import", mealie_import, methods=["POST"]),
    Route("/api/mealie/sync", mealie_sync_now, methods=["POST"]),
    Route("/api/photo/analyze", photo_analyze, methods=["POST"]),
    Route("/api/photo/log", photo_log, methods=["POST"]),
    Route("/api/settings", settings_get),
    Route("/api/settings", settings_update, methods=["PUT"]),
    Route("/api/settings/slv-import", slv_import, methods=["POST"]),
    Route("/api/settings/ollama-models", ollama_models),
    Route("/api/export.csv", export_csv),
    Mount("/static", StaticFiles(directory=STATIC), name="static"),
]

app = Starlette(routes=routes, lifespan=lifespan, exception_handlers={HTTPException: http_error})
