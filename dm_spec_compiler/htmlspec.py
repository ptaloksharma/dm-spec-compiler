"""Rich HTML spec-pack DOM extractor (πd Genius HTML format) — deterministic.

Parses the three rich HTML spec shapes straight from the DOM (BeautifulSoup),
returning plain dicts that ``design.py`` merges into a validated TechDesign.
NO LLM, NO guessing — every extraction is a CSS-selector + cell-position rule.
Domain-agnostic: nothing here keys on any business word.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_STATE_ID = re.compile(r"^T\d{2}[a-z]?$")
_INV_ID = re.compile(r"^I-\d{2}$")
_ARROW_RE = re.compile(r"(.+?)\s*(?:->|→|⟶|&gt;)\s*(.+)")

_AUTONOMY = {
    "lv-det": "code",
    "lv-ais": "ai_suggests",
    "lv-aid": "ai_decides",
    "lv-hum": "person",
}


def _cls(el) -> set[str]:
    return set(el.get("class", [])) if el else set()


def _txt(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _rows(table) -> list[list]:
    out = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if cells:
            out.append(cells)
    return out


def _autonomy_of(li) -> str:
    for cls, tag in _AUTONOMY.items():
        if li.find(class_=cls):
            return tag
    return "code"


def _section_table(soup, sec_id: str):
    sec = soup.find(id=sec_id)
    if sec is None:
        return None
    if sec.name == "table":
        return sec
    return sec.find("table", class_="t") or sec.find("table")


def _snake(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _sections_ending(soup, suffix: str):
    return [soup.find(id=i) for i in
            [x.get("id") for x in soup.find_all(id=True)
             if isinstance(x.get("id"), str) and x.get("id").endswith(suffix)]]


# --------------------------------------------------------------------------- #
# Entity & State Model                                                          #
# --------------------------------------------------------------------------- #
def _parse_catalogue(soup) -> list[dict]:
    table = _section_table(soup, "catalogue")
    if table is None:
        return []
    ents: dict[str, dict] = {}
    order: list[str] = []
    for cells in _rows(table)[1:]:
        name_el = cells[0].find(class_="mono") or cells[0]
        name = _snake(_txt(name_el))
        if not name:
            continue
        pill = cells[0].find(class_="pill")
        scope = _txt(pill) if pill else ""
        owner = _txt(cells[1]) if len(cells) > 1 else ""
        acts = [a.strip() for a in _txt(cells[2]).split(",")] if len(cells) > 2 else []
        acts = [a for a in acts if a]
        if name not in ents:
            ents[name] = {"name": name, "table": name + "s", "scope": scope,
                          "owner": owner, "acts": acts, "fields": [],
                          "typed_fields": []}
            order.append(name)
        else:
            e = ents[name]
            e["acts"] = sorted(set(e["acts"]) | set(acts))
            if scope and not e["scope"]:
                e["scope"] = scope
    return [ents[n] for n in order]


def _parse_attr_tables(soup, entities: list[dict]) -> None:
    by_name = {e["name"]: e for e in entities}
    for table in soup.find_all("table", class_="t"):
        if "attrs" not in _cls(table):
            continue
        ref = None
        prev = table.find_previous(["h1", "h2", "h3", "h4", "caption"])
        if prev is not None:
            cand = _snake(_txt(prev))
            # strip a trailing "attributes"/"attrs" word from the heading
            cand = re.sub(r"_(attributes?|attrs)$", "", cand)
            if cand in by_name:
                ref = cand
        if ref is None:
            # single-context packs: nearest entity by document order, else first
            for name in by_name:
                if table.find_previous(string=re.compile(name, re.I)):
                    ref = name
            if ref is None and by_name:
                ref = next(iter(by_name))
        if ref is None:
            continue
        for cells in _rows(table)[1:]:
            if not cells:
                continue
            name_el = cells[0].find(class_="mono") or cells[0]
            fname = _snake(_txt(name_el))
            if not fname:
                continue
            ty_el = (cells[0].find(class_="ty")
                     or (cells[1].find(class_="ty") if len(cells) > 1 else None))
            ftype = _txt(ty_el) if ty_el else (_txt(cells[1]) if len(cells) > 1 else "")
            note = _txt(cells[2]) if len(cells) > 2 else ""
            by_name[ref]["typed_fields"].append(
                {"name": fname, "type": ftype or "str", "note": note})
            if fname not in by_name[ref]["fields"]:
                by_name[ref]["fields"].append(fname)


def _parse_states(soup) -> list[dict]:
    containers = [c for c in _sections_ending(soup, "-states") if c is not None]
    if not containers:
        containers = [t for t in soup.find_all("table") if t.find(class_="st")]
    states: list[dict] = []
    for cont in containers:
        for td in cont.find_all(class_="st"):
            classes = _cls(td)
            sid_el = td.find(class_="mono") or td
            token = _txt(sid_el).split()
            sid = token[0] if token else ""
            if not _STATE_ID.match(sid):
                continue
            name_el = td.find(class_="nm") or td.find(class_="name")
            m = td.find(class_="meaning") or td.find(class_="desc")
            states.append({
                "id": sid,
                "name": _snake(_txt(name_el)) or sid.lower(),
                "description": _txt(m),
                "terminal": "term" in classes,
                "hold": False,
            })
    seen, out = set(), []
    for s in states:
        if s["id"] not in seen:
            out.append(s)
            seen.add(s["id"])
    return out


def _parse_transitions(soup) -> list[dict]:
    containers = [c for c in _sections_ending(soup, "-trans") if c is not None]
    if not containers:
        return []
    out: list[dict] = []
    for cont in containers:
        table = cont if cont.name == "table" else (cont.find("table") or cont)
        for cells in _rows(table)[1:]:
            texts = [_txt(c) for c in cells]
            if not texts:
                continue
            first = texts[0].split()
            if not first or not _STATE_ID.match(first[0]):
                continue
            tid = first[0]
            frm, to, arrow_idx = "", "", -1
            for j, t in enumerate(texts[1:], start=1):
                m = _ARROW_RE.search(t)
                if m:
                    frm, to = m.group(1).strip(), m.group(2).strip()
                    arrow_idx = j
                    break
            rest = [t for k, t in enumerate(texts[1:], start=1) if k != arrow_idx]
            out.append({
                "id": tid, "from_state": frm, "to_state": to,
                "trigger": rest[0] if len(rest) > 0 else "",
                "guard": rest[1] if len(rest) > 1 else "",
                "effect": rest[2] if len(rest) > 2 else "",
                "scenario": rest[3] if len(rest) > 3 else "",
            })
    return out


def _parse_holds(soup) -> list[dict]:
    table = _section_table(soup, "holds")
    if table is None:
        return []
    out = []
    for cells in _rows(table)[1:]:
        ht = cells[0].find(class_="mono") or cells[0]
        rec = {
            "hold_type": _txt(ht),
            "placed_by": _txt(cells[1]) if len(cells) > 1 else "",
            "scope": _txt(cells[2]) if len(cells) > 2 else "",
            "auto_release": _txt(cells[3]) if len(cells) > 3 else "",
            "on_release": _txt(cells[4]) if len(cells) > 4 else "",
        }
        if rec["hold_type"]:
            out.append(rec)
    return out


def _parse_invariants(soup) -> list[dict]:
    table = _section_table(soup, "invariants")
    if table is None:
        return []
    out = []
    for cells in _rows(table)[1:]:
        iid_el = cells[0].find(class_="mono") or cells[0]
        token = _txt(iid_el).split()
        iid = token[0] if token else ""
        if not _INV_ID.match(iid):
            continue
        rule = _txt(cells[1]) if len(cells) > 1 else ""
        out.append({"id": iid, "rule": rule})
    return out


def extract_entity_state(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    entities = _parse_catalogue(soup)
    _parse_attr_tables(soup, entities)
    return {
        "entities": entities,
        "states": _parse_states(soup),
        "transitions": _parse_transitions(soup),
        "holds": _parse_holds(soup),
        "invariants": _parse_invariants(soup),
    }


# --------------------------------------------------------------------------- #
# Entry Point Catalogue                                                         #
# --------------------------------------------------------------------------- #
_KIND_MAP = {"k-cmd": "command", "k-evt": "event_handler", "k-qry": "query",
             "command": "command", "event handler": "event_handler",
             "event_handler": "event_handler", "query": "query"}


def _parse_ep(details) -> dict:
    ep: dict = {"id": details.get("id", ""), "name": "", "kind": "command",
                "proposed": False, "transition": "", "route": "",
                "input_schema": "", "guards": [], "processing": [],
                "outputs": [], "errors": [], "idempotency": "", "tests": []}
    dk = details.get("data-k", "")
    for k, v in _KIND_MAP.items():
        if k in dk:
            ep["kind"] = v
            break
    summary = details.find("summary")
    if summary:
        idel = summary.find(class_="id")
        if idel:
            ep["id"] = ep["id"] or _txt(idel)
        nm = summary.find(class_="nm")
        if nm:
            ep["name"] = _txt(nm)
        if summary.find(class_="s-prop"):
            ep["proposed"] = True
        tr = summary.find(class_="tr")
        if tr:
            ep["transition"] = _txt(tr)
        stxt = _txt(summary).lower()
        for k, v in _KIND_MAP.items():
            if " " in k and k in stxt:
                ep["kind"] = v
    eb = details.find("div", class_="eb")
    if not eb:
        return ep
    for ol in eb.find_all("ol"):
        for step in ol.find_all("li", recursive=False):
            ep["processing"].append(
                {"text": _txt(step), "autonomy": _autonomy_of(step)})
    for block in eb.find_all(["dt", "div", "p", "li", "span"]):
        lab = block.find(class_=re.compile(r"^(k|label|lbl|key)$"))
        text = _txt(block)
        if not text:
            continue
        if lab is not None:
            key = _txt(lab).lower()
            val = text.replace(_txt(lab), "", 1).lstrip(" :").strip()
        else:
            key = text.lower().split(":")[0]
            val = text.split(":", 1)[1].strip() if ":" in text else ""
        low = text.lower()
        if ("route" in key or "trigger" in key) and not ep["route"]:
            ep["route"] = val or text
        elif ("input" in key or "schema" in key) and not ep["input_schema"]:
            ep["input_schema"] = val or text
        elif "guard" in key:
            ep["guards"].append(val or text)
        elif "output" in key or "outbox" in key:
            monos = [_txt(m) for m in block.find_all(class_="mono")]
            ep["outputs"].extend(m for m in monos if m)
            if not monos and val:
                ep["outputs"].append(val)
        elif "error" in key:
            ep["errors"].append(val or text)
        elif "idempot" in key and not ep["idempotency"]:
            ep["idempotency"] = val or text
        elif "test" in key or low.startswith(("given", "when", "then")):
            ep["tests"].append(text)
    return ep


def extract_entry_points(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    eps = [_parse_ep(d) for d in soup.find_all("details", class_="ep")]
    return {"entry_points": [e for e in eps if e["id"]]}


# --------------------------------------------------------------------------- #
# EARS Requirements                                                             #
# --------------------------------------------------------------------------- #
def extract_requirements(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    nfrs = []
    nfr_sec = soup.find(id="nfr")
    if nfr_sec:
        table = (nfr_sec.find("table", class_="nfr-table")
                 or nfr_sec.find("table") or nfr_sec.find_next("table"))
        if table:
            for cells in _rows(table)[1:]:
                if len(cells) >= 2:
                    nfrs.append({"category": _txt(cells[0]),
                                 "requirement": _txt(cells[1]),
                                 "target": _txt(cells[2]) if len(cells) > 2 else ""})
    reqs = []
    for card in soup.find_all("div", class_="req-card"):
        rid_el = card.find(class_="req-id")
        rid = _txt(rid_el) or card.get("id", "")
        title = _txt(card.find(class_="req-title"))
        posture = _txt(card.find(class_="posture"))
        clauses = []
        for item in card.find_all(class_="ears-item"):
            tag = _txt(item.find(class_="ears-tag"))
            text = _txt(item.find(class_="ears-text")) or _txt(item)
            clauses.append({"tag": tag, "text": text})
        reqs.append({"id": rid, "title": title, "posture": posture,
                     "clauses": clauses})
    return {"nfr_requirements": nfrs, "ears_requirements": reqs}


# --------------------------------------------------------------------------- #
# Sniff + dispatch                                                              #
# --------------------------------------------------------------------------- #
def detect_spec_kind(fname: str, html: str) -> str | None:
    low = fname.lower()
    if "entity_and_state" in low or "state_model" in low:
        return "entity_state"
    if "entry_point" in low:
        return "entry_points"
    if low.endswith("-req.html") or low.endswith("_req.html") or "req.html" in low:
        return "requirements"
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("details", class_="ep"):
        return "entry_points"
    if soup.find("div", class_="req-card"):
        return "requirements"
    if soup.find(id="catalogue"):
        return "entity_state"
    return None


def extract_rich(fname: str, html: str) -> dict | None:
    kind = detect_spec_kind(fname, html)
    if kind == "entity_state":
        return {"__kind__": "entity_state", **extract_entity_state(html)}
    if kind == "entry_points":
        return {"__kind__": "entry_points", **extract_entry_points(html)}
    if kind == "requirements":
        return {"__kind__": "requirements", **extract_requirements(html)}
    return None
