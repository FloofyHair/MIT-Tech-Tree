#!/usr/bin/env python3
"""
MIT Catalog Scraper (specific courses only)
-------------------------------------------
Fetches and parses MIT's course catalog search result for given course codes
(e.g., "6.1200", "18.06", "5.111") and outputs normalized JSON.

Usage:
  python3 scrape_mit_catalog.py 6.1200
  python3 scrape_mit_catalog.py 6.1200 18.06 8.02
  python3 scrape_mit_catalog.py --merge classes.json 6.1200 18.06

Requires:
  pip install requests beautifulsoup4
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Tuple

try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    sys.stderr.write(
        "This script requires 'requests' and 'beautifulsoup4'. Install with:\n"
        "  pip install requests beautifulsoup4\n"
    )
    raise

BASE = "https://student.mit.edu/catalog/search.cgi?search={}"

SKIP_ICON_ALTS = {"______", "Add to schedule"}


# -----------------------
# Helpers
# -----------------------

def course_id_from_code(code: str) -> str:
    """A6_1200 from 6.1200 (keeps letters too, e.g., 18.01A -> A18_01A)."""
    code = code.strip()
    return "A" + code.replace(".", "_")


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_units(text: str) -> Optional[str]:
    m = re.search(r"Units:\s*([0-9\-]+)", text, re.I)
    return m.group(1) if m else None


def derive_area_color(code: str) -> Tuple[str, str]:
    """Return (area, color) from the leading department number in `code`."""
    m = re.match(r"^(\d+)", code.strip())
    dept = m.group(1) if m else ""
    if dept == "5":
        return "chem", "var(--chem)"
    if dept == "6":
        return "ee", "var(--ee)"
    if dept == "18":
        return "math", "var(--math)"
    return "other", "var(--other)"


def fetch_html(course: str) -> str:
    url = BASE.format(course)
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.text


# -----------------------
# Parsing
# -----------------------

def parse_course_html(html: str) -> Dict:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("blockquote") or soup

    # Title line: <h3>6.1200[J] Mathematics for Computer Science
    h3 = root.find("h3")
    if not h3:
        raise ValueError("Could not find <h3> title block for course")

    full_title = clean_text(h3.get_text(" ", strip=True))
    m = re.match(r"^([0-9A-Za-z\.\-]+(?:\[[Jj]\])?)\s+(.*)$", full_title)
    if m:
        raw_code, course_title = m.groups()
    else:
        parts = full_title.split(maxsplit=1)
        raw_code = parts[0]
        course_title = parts[1] if len(parts) > 1 else parts[0]

    # Normalize code by removing [J] flag for 'code' field, but keep 'Joint' tag
    joint = "[J]" in raw_code or "[j]" in raw_code
    code = raw_code.replace("[J]", "").replace("[j]", "")

    # Tags from <img alt="..."> (keep raw alts; UI can normalize)
    tags: List[str] = []
    for img in root.find_all("img"):
        alt = (img.get("alt") or "").strip()
        if not alt or alt in SKIP_ICON_ALTS:
            continue
        if alt not in tags:
            tags.append(alt)
    if joint and "Joint" not in tags:
        tags.insert(0, "Joint")

    # Prereq text
    prereq_text = None
    for br in root.find_all("br"):
        nxt = br.next_sibling
        if isinstance(nxt, str) and nxt.strip().lower().startswith("prereq:"):
            parts = []
            node = br.next_sibling
            if isinstance(node, str):
                node = node.next_sibling  # skip the literal "Prereq:" text node
            while node and getattr(node, "name", None) != "br":
                if getattr(node, "get_text", None):
                    parts.append(node.get_text(" ", strip=True))
                elif isinstance(node, str):
                    parts.append(node.strip())
                node = node.next_sibling
            prereq_text = clean_text(" ".join(p for p in parts if p))
            break
    if not prereq_text:
        txt = root.get_text("\n", strip=True)
        mt = re.search(r"Prereq:\s*(.+)", txt, re.I)
        if mt:
            prereq_text = clean_text(mt.group(1))

    # Units (from whole text)
    text_all = root.get_text("\n", strip=True)
    units = parse_units(text_all)

    # Description: the line right after the horizontal rule image(s)
    description = None
    hr_img = h3.find_next("img", alt="______")
    hr_img2 = hr_img.find_next("img", alt="______") if hr_img else None
    if hr_img2:
        hr_img = hr_img2
    if hr_img:
        first_br = hr_img.find_next("br")
        if first_br:
            node = first_br.next_sibling
            while node and (isinstance(node, str) and not node.strip()):
                node = node.next_sibling
            if node:
                if getattr(node, "get_text", None):
                    description = clean_text(node.get_text(" ", strip=True))
                elif isinstance(node, str):
                    description = clean_text(node.strip())
    if not description:
        # Fallback: longest paragraph that doesn’t say “subject found”
        paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in root.find_all("p")]
        paragraphs = [p for p in paragraphs if not re.search(r"subject found", p, re.I)]
        if paragraphs:
            desc = max(paragraphs, key=len)
            m2 = re.search(
                r"(Elementary\b.*|Introduces\b.*|Introduction\b.*|Provides\b.*|Covers\b.*|Studies\b.*|Examines\b.*|Overview\b.*|An introduction\b.*)",
                desc,
                re.I,
            )
            description = (m2.group(1).strip() if m2 else desc)

    # Instructors: italic names inside <i> ... </i>, with filtering
    instructors = []
    for iel in root.find_all("i"):
        txt = clean_text(iel.get_text(" ", strip=True))
        if not txt:
            continue
        low = txt.lower()

        # Skip known junk and schedules
        if low in ("+final", "no textbook information available", "tba"):
            continue
        if "subject found" in low:
            continue
        if re.match(r"^[MTWRFSU]{1,7}\s*\d", txt, re.I) or re.search(r"\d\.\d{2}\s*-\s*\d", txt):
            continue

        parent_text = iel.find_previous(string=True)
        if parent_text and re.search(r"(Lab|Recitation|Lecture):", parent_text, re.I):
            continue

        instructors.append(txt)

    # dedupe preserving order
    seen = set()
    instructors = [x for x in instructors if not (x in seen or seen.add(x))]

    # area/color
    area, color = derive_area_color(code)

    result = {
        "code": code,
        "title": course_title,
        "label": course_title,
        "description": description,
        "units": units,
        "prereq_text": prereq_text,
        "instructors": instructors,
        "tags": tags,
        "source": "student.mit.edu",
        "area": area,
        "color": color,
    }
    return result


def scrape_course(course: str) -> Dict:
    html = fetch_html(course)
    return parse_course_html(html)


def merge_into_nodes(nodes: Dict[str, Dict], course_obj: Dict) -> Dict[str, Dict]:
    """Merge/insert a course object into nodes mapping using our ID scheme."""
    code = course_obj.get("code") or ""
    if not code:
        return nodes
    cid = course_id_from_code(code)
    existing = nodes.get(cid, {})
    merged = {
        **existing,
        "code": code,
        "title": course_obj.get("title") or existing.get("title"),
        "label": course_obj.get("label") or existing.get("label") or course_obj.get("title") or code,
        "description": course_obj.get("description") or existing.get("description"),
        "units": course_obj.get("units") or existing.get("units"),
        "prereq_text": course_obj.get("prereq_text") or existing.get("prereq_text"),
        "instructors": course_obj.get("instructors") or existing.get("instructors"),
        "tags": course_obj.get("tags") or existing.get("tags"),
        "area": course_obj.get("area") or existing.get("area"),
        "color": course_obj.get("color") or existing.get("color"),
    }
    nodes[cid] = merged
    return nodes


# -----------------------
# CLI
# -----------------------

def main():
    ap = argparse.ArgumentParser(description="Scrape MIT catalog for course info (specific courses only).")
    # Put optionals BEFORE the positional to avoid “unrecognized arguments” confusion
    ap.add_argument("--merge", metavar="CLASSES_JSON",
                    help="Path to classes.json to merge into (updates nodes only)")
    ap.add_argument("--out", metavar="OUT_JSON",
                    help="Write scraped output JSON to a file (default: stdout)")
    ap.add_argument("courses", nargs="+",
                    help="Course numbers like 6.1200 18.06 5.111")
    args = ap.parse_args()

    scraped = {}
    for c in args.courses:
        try:
            obj = scrape_course(c)
            scraped[obj["code"]] = obj
        except Exception as e:
            sys.stderr.write(f"[warn] {c}: {e}\n")

    if args.merge:
        try:
            with open(args.merge, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {"nodes": {}}
        except Exception as e:
            sys.stderr.write(f"Failed to read {args.merge}: {e}\n")
            return 2

        nodes = data.get("nodes", {})
        for obj in scraped.values():
            nodes = merge_into_nodes(nodes, obj)
        data["nodes"] = nodes

        with open(args.merge, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Output only the items we just merged (mapped by our internal IDs)
        out_obj = {course_id_from_code(k): nodes[course_id_from_code(k)]
                   for k in scraped.keys()
                   if course_id_from_code(k) in nodes}
    else:
        out_obj = scraped

    out_text = json.dumps(out_obj, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out_text)
    else:
        print(out_text)


if __name__ == "__main__":
    sys.exit(main() or 0)
