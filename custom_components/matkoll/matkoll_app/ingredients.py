"""Turns recipe ingredient lines ("2 dl vetemjöl", "1 förp majs (à 340 g)") into names and gram estimates.

Swedish and English. Estimates are a starting point that the user confirms on the import screen.
"""
import re
import unicodedata

FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125, "⅕": 0.2}

# unit -> (kind, factor). weight: grams per unit; volume: ml per unit; piece: handled per food; pack: uses "à N g"
UNITS = {
    "mg": ("weight", 0.001), "g": ("weight", 1), "gr": ("weight", 1), "gram": ("weight", 1),
    "hg": ("weight", 100), "kg": ("weight", 1000), "kilo": ("weight", 1000),
    "oz": ("weight", 28.35), "lb": ("weight", 453.6), "lbs": ("weight", 453.6),
    "ml": ("volume", 1), "cl": ("volume", 10), "dl": ("volume", 100), "l": ("volume", 1000), "liter": ("volume", 1000),
    "msk": ("volume", 15), "matsked": ("volume", 15), "matskedar": ("volume", 15),
    "tsk": ("volume", 5), "tesked": ("volume", 5), "teskedar": ("volume", 5),
    "krm": ("volume", 1), "kryddmått": ("volume", 1),
    "tbsp": ("volume", 15), "tablespoon": ("volume", 15), "tablespoons": ("volume", 15),
    "tsp": ("volume", 5), "teaspoon": ("volume", 5), "teaspoons": ("volume", 5),
    "cup": ("volume", 240), "cups": ("volume", 240), "kopp": ("volume", 240), "koppar": ("volume", 240),
    "st": ("piece", 1), "stycken": ("piece", 1), "styck": ("piece", 1), "pcs": ("piece", 1), "piece": ("piece", 1),
    "klyfta": ("clove", 1), "klyftor": ("clove", 1), "clove": ("clove", 1), "cloves": ("clove", 1),
    "skiva": ("slice", 1), "skivor": ("slice", 1), "slice": ("slice", 1), "slices": ("slice", 1),
    "nypa": ("weight", 0.5), "pinch": ("weight", 0.5),
    "kvist": ("weight", 2), "kvistar": ("weight", 2), "knippe": ("weight", 30), "kruka": ("weight", 25),
    "förp": ("pack", 1), "förpackning": ("pack", 1), "förpackningar": ("pack", 1), "paket": ("pack", 1),
    "pkt": ("pack", 1), "burk": ("pack", 1), "burkar": ("pack", 1), "påse": ("pack", 1), "påsar": ("pack", 1),
    "ask": ("pack", 1), "askar": ("pack", 1), "flaska": ("pack", 1), "tub": ("pack", 1), "can": ("pack", 1),
    "cans": ("pack", 1), "pack": ("pack", 1), "package": ("pack", 1),
    "bit": ("piece", 1), "bitar": ("piece", 1),
}

# grams per ml, matched against the ingredient name (first match wins, so specific before general)
DENSITIES = [
    ("filmjölk", 1.03), ("mjölk", 1.03), ("milk", 1.03),  # before "mjöl", which is part of "mjölk"
    ("florsocker", 0.55), ("strösocker", 0.85), ("farinsocker", 0.8), ("socker", 0.85), ("sugar", 0.85),
    ("vetemjöl", 0.6), ("rågmjöl", 0.55), ("majsstärkelse", 0.6), ("potatismjöl", 0.75), ("mjöl", 0.6), ("flour", 0.6),
    ("havregryn", 0.4), ("oats", 0.4), ("müsli", 0.45), ("granola", 0.45), ("ströbröd", 0.45),
    ("ris", 0.85), ("rice", 0.85), ("couscous", 0.65), ("bulgur", 0.7), ("quinoa", 0.75), ("linser", 0.8),
    ("olja", 0.92), ("oil", 0.92), ("smör", 0.95), ("butter", 0.95), ("margarin", 0.95),
    ("gräddfil", 1.0), ("crème fraiche", 1.0), ("creme fraiche", 1.0), ("grädde", 1.0), ("cream", 1.0),
    ("yoghurt", 1.03), ("yogurt", 1.03), ("kvarg", 1.05),
    ("riven ost", 0.4), ("ost riven", 0.4), ("parmesan", 0.4), ("shredded cheese", 0.4),
    ("honung", 1.4), ("honey", 1.4), ("sirap", 1.4), ("syrup", 1.4),
    ("kakao", 0.45), ("cocoa", 0.45), ("salt", 1.2), ("bakpulver", 0.9), ("bikarbonat", 0.9),
    ("krossade tomater", 1.05), ("passerade tomater", 1.05), ("tomatpuré", 1.1), ("ketchup", 1.15),
    ("majonnäs", 0.92), ("senap", 1.05), ("soja", 1.15), ("vinäger", 1.0), ("ättika", 1.0),
    ("kokosmjölk", 1.0), ("buljong", 1.0), ("fond", 1.05), ("vatten", 1.0), ("water", 1.0), ("vin", 1.0),
    ("majs", 0.75), ("ärtor", 0.6), ("bönor", 0.75), ("kikärtor", 0.75), ("nötter", 0.55), ("mandel", 0.6),
    ("russin", 0.65), ("frön", 0.6), ("sesam", 0.6), ("kokosflingor", 0.35), ("spenat", 0.3), ("kål", 0.35),
    ("persilja", 0.1), ("dill", 0.1), ("basilika", 0.1), ("koriander", 0.1), ("gräslök", 0.15),
]

# grams per piece, matched against the ingredient name (first match wins)
PIECES = [
    ("vitlöksklyft", 5), ("klyfta vitlök", 5), ("garlic clove", 5), ("vitlök", 40), ("garlic", 5),
    ("schalottenlök", 30), ("shallot", 30), ("rödlök", 100), ("purjolök", 200), ("salladslök", 15), ("lök", 120),
    ("onion", 120), ("körsbärstomat", 15), ("cherry tomato", 15), ("tomat", 120), ("tomato", 120),
    ("potatis", 100), ("potato", 100), ("sötpotatis", 300), ("morot", 70), ("morötter", 70), ("carrot", 70),
    ("paprika", 150), ("bell pepper", 150), ("chili", 15), ("gurka", 350), ("cucumber", 350),
    ("zucchini", 250), ("squash", 250), ("aubergine", 300), ("broccoli", 400), ("blomkål", 600),
    ("citron", 100), ("lemon", 100), ("lime", 70), ("apelsin", 150), ("orange", 150), ("äpple", 150),
    ("apple", 150), ("banan", 120), ("banana", 120), ("avokado", 150), ("avocado", 150), ("päron", 160),
    ("ägg", 55), ("egg", 55), ("äggula", 18), ("äggulor", 18), ("äggvita", 33), ("äggvitor", 33),
    ("kycklingfilé", 150), ("kycklingbröst", 150), ("chicken breast", 150), ("kycklinglår", 110),
    ("laxfilé", 125), ("torskfilé", 125), ("fiskfilé", 125),
    ("tortilla", 40), ("hamburgerbröd", 60), ("pitabröd", 60), ("korv", 70), ("champinjon", 15),
    ("ingefära", 20), ("selleri", 40), ("rödbeta", 100), ("palsternacka", 100), ("fänkål", 250),
    ("buljongtärning", 10), ("lagerblad", 0.2), ("kanelstång", 3),
]
SLICE_G = 25
CLOVE_G = 5

STOP_WORDS = {"färsk", "färska", "fryst", "frysta", "hackad", "hackade", "riven", "rivna", "finhackad", "finhackade",
              "skivad", "skivade", "tärnad", "tärnade", "kokt", "kokta", "stor", "stora", "liten", "små", "mellanstor",
              "ca", "cirka", "gärna", "eller", "och", "till", "servering", "att", "steka", "i", "av", "med",
              "fresh", "chopped", "diced", "sliced", "large", "small", "medium", "minced", "grated", "to", "serve"}

_num = r"(\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)"
QTY_RE = re.compile(rf"^\s*(?:ca\.?\s+|cirka\s+|about\s+)?{_num}(?:\s*[-–]\s*{_num})?\s*")
PACK_RE = re.compile(r"(?:(?:à|á|a|ca|om|of)\s*|\(\s*)(\d+(?:[.,]\d+)?)\s*(g|gr|kg|ml|cl|dl|l)\b", re.I)


def _to_float(s):
    s = s.strip().replace(",", ".")
    total = 0.0
    for part in s.split():
        if "/" in part:
            a, b = part.split("/", 1)
            total += float(a) / float(b) if float(b) else 0
        else:
            total += float(part)
    return total


def _normalize(line: str) -> str:
    # Unicode fractions first ("1 ½" -> "1.5"), before NFKC turns them into "1⁄2".
    for ch, val in FRACTIONS.items():
        line = re.sub(rf"(\d+)\s*{ch}", lambda m, v=val: f"{int(m.group(1)) + v:g}", line)
        line = line.replace(ch, f"{val:g}")
    line = unicodedata.normalize("NFKC", line).replace("⁄", "/")
    return re.sub(r"\s+", " ", line).strip()


def _lookup(table, name):
    low = name.lower()
    for key, val in table:
        if key in low:
            return val
    return None


def parse_line(line: str) -> dict:
    """Returns {line, name, qty, unit, grams, estimated} — grams None when it can't be guessed."""
    original = line.strip()
    text = _normalize(original)
    qty = None
    m = QTY_RE.match(text)
    if m:
        a = _to_float(m.group(1))
        b = _to_float(m.group(2)) if m.group(2) else None
        qty = (a + b) / 2 if b else a
        text = text[m.end():]
    unit = None
    first = re.match(r"^([A-Za-zÅÄÖåäöéè]+)\.?(?=\s|$)", text)
    if first and first.group(1).lower() in UNITS:
        unit = first.group(1).lower()
        text = text[first.end():].strip()

    pack_g = None
    pm = PACK_RE.search(text)
    if pm:
        amount = _to_float(pm.group(1))
        u = pm.group(2).lower()
        kind, factor = UNITS.get(u, ("weight", 1))
        pack_g = amount * factor  # ml treated as g (packs of liquids are close to 1 g/ml)

    name = re.sub(r"\([^)]*\)", " ", text)                      # drop parentheses
    name = re.split(r"\s+(?:alt\.?|eller|or)\s+|,|;", name)[0]   # first alternative only
    name = PACK_RE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .-–")

    grams = _estimate(qty, unit, name, pack_g)
    return {"line": original, "name": name, "qty": qty, "unit": unit, "grams": grams,
            "estimated": grams is not None and unit not in (None,) and UNITS.get(unit, ("",))[0] != "weight"}


def _estimate(qty, unit, name, pack_g):
    if unit:
        kind, factor = UNITS[unit]
        q = qty if qty is not None else 1
        if kind == "weight":
            return round(q * factor, 1)
        if kind == "volume":
            density = _lookup(DENSITIES, name) or 1.0
            return round(q * factor * density, 1)
        if kind == "pack":
            return round(q * pack_g, 1) if pack_g else None
        if kind == "clove":
            return round(q * CLOVE_G, 1)
        if kind == "slice":
            return round(q * SLICE_G, 1)
        if kind == "piece":
            per = _lookup(PIECES, name)
            return round(q * per, 1) if per else None
    if pack_g and qty:
        return round(qty * pack_g, 1)
    if qty is not None:
        per = _lookup(PIECES, name)
        return round(qty * per, 1) if per else None
    return None


def search_terms(name: str) -> list[str]:
    """Search strings to try against the food database, most specific first."""
    words = [w for w in re.findall(r"[A-Za-zÅÄÖåäöéèü]+", name.lower()) if w not in STOP_WORDS and len(w) > 1]
    terms = []
    if words:
        terms.append(" ".join(words))
        if len(words) > 1:
            terms.append(" ".join(words[-2:]))
        terms += sorted(set(words), key=len, reverse=True)
    out = []
    for t in terms:
        if t not in out:
            out.append(t)
    return out


def is_negligible(name: str) -> bool:
    """Salt, pepper and other seasonings 'to taste' — fine to skip."""
    low = name.lower()
    return bool(re.search(r"\b(salt|peppar|pepper|svartpeppar|kryddor?|efter smak|to taste)\b", low)) and len(low) < 40
