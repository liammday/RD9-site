#!/usr/bin/env python3
import csv, html, io, json, os, sys, urllib.request, pathlib, hashlib

SHEET_CSV_URL = os.environ.get("SHEET_CSV_URL")
TARGET_HTML   = os.environ.get("TARGET_HTML", "index.html")
MARK_START    = "<!-- BEGIN:PRICE_LIST -->"
MARK_END      = "<!-- END:PRICE_LIST -->"
JSON_OUT      = os.environ.get("JSON_OUT", "site/data/prices.json")  # optional
WRITE_JSONLD  = os.environ.get("WRITE_JSONLD", "0") == "1"           # opt-in
JSONLD_START  = "<!-- BEGIN:PRICE_LIST_JSONLD -->"
JSONLD_END    = "<!-- END:PRICE_LIST_JSONLD -->"
CURRENCY      = os.environ.get("CURRENCY", "GBP")

if not SHEET_CSV_URL:
    print("Missing SHEET_CSV_URL env var", file=sys.stderr)
    sys.exit(2)

def fetch_csv(url: str) -> str:
    with urllib.request.urlopen(url) as resp:
        data = resp.read()
    # Try utf-8 with BOM handling
    text = data.decode("utf-8-sig")
    return text

def parse_csv(text: str):
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    dicts = []
    for r in rows[1:]:
        # pad/truncate safely
        values = (r + [""] * len(headers))[:len(headers)]
        dicts.append({headers[i]: values[i].strip() for i in range(len(headers))})
    return headers, dicts

def escape(s: str) -> str:
    return html.escape(s if s is not None else "", quote=False)

def render_table(headers, rows):
    thead = "<thead><tr>" + "".join(f"<th>{escape(h)}</th>" for h in headers) + "</tr></thead>"
    body_cells = []
    for row in rows:
        tds = "".join(f"<td>{escape(str(row.get(h,'')))}</td>" for h in headers)
        body_cells.append(f"<tr>{tds}</tr>")
    tbody = "<tbody>\n" + "\n".join(body_cells) + "\n</tbody>"
    return f'<table class="w-full text-sm md:text-base">\n{thead}\n{tbody}\n</table>'

def replace_between_markers(text, start, end, replacement):
    i = text.find(start)
    j = text.find(end)
    if i == -1 or j == -1 or j < i:
        raise RuntimeError("Markers not found or out of order")
    return text[: i + len(start)] + "\n" + replacement + "\n" + text[j:]

def write_if_changed(path: str, content: str):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    if hashlib.sha256(existing.encode()).hexdigest() != hashlib.sha256(content.encode()).hexdigest():
        p.write_text(content, encoding="utf-8")
        return True
    return False

def maybe_make_jsonld(headers, rows):
    """
    Optional: map your column names to JSON-LD Offer/Service.
    Fill in the mapping below to enable (or set WRITE_JSONLD=1 + provide head markers).
    """
    # TODO: customise these to YOUR header names
    name_col = None          # e.g. "service_item" or "name"
    desc_col = None          # e.g. "description"
    price_col = None         # e.g. "price_gbp_inc_vat"
    currency = CURRENCY

    if not (name_col and price_col):
        return None  # Mapping not configured

    items = []
    for r in rows:
        name = r.get(name_col, "").strip()
        price = str(r.get(price_col, "")).strip().replace("£","")
        if not name or not price:
            continue
        obj = {
            "@type": "Offer",
            "price": price,
            "priceCurrency": currency,
            "itemOffered": {
                "@type": "Service",
                "name": name
            }
        }
        if desc_col and r.get(desc_col, "").strip():
            obj["itemOffered"]["description"] = r[desc_col].strip()
        items.append(obj)

    if not items:
        return None

    payload = {
        "@context": "https://schema.org",
        "@type": "OfferCatalog",
        "name": "Price List",
        "itemListElement": items
    }
    return '<script type="application/ld+json">' + json.dumps(payload, ensure_ascii=False) + "</script>"

def main():
    csv_text = fetch_csv(SHEET_CSV_URL)
    headers, rows = parse_csv(csv_text)

    # (Optional) sort here if desired, e.g. by a "service_item" column:
    # rows.sort(key=lambda r: (r.get("service_category",""), r.get("service_item","")))

    html_table = render_table(headers, rows)

    # Write JSON snapshot (handy for other parts of your site)
    if JSON_OUT:
        write_if_changed(JSON_OUT, json.dumps(rows, indent=2, ensure_ascii=False))

    # Inject table into the HTML page
    target = pathlib.Path(TARGET_HTML)
    html_src = target.read_text(encoding="utf-8")
    html_out = replace_between_markers(html_src, MARK_START, MARK_END, html_table)

    # Optional JSON-LD injection (requires head markers)
    if WRITE_JSONLD:
        jsonld = maybe_make_jsonld(headers, rows)
        if jsonld:
            html_out = replace_between_markers(html_out, JSONLD_START, JSONLD_END, jsonld)

    if html_out != html_src:
        target.write_text(html_out, encoding="utf-8")

if __name__ == "__main__":
    main()
