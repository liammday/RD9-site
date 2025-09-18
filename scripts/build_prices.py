#!/usr/bin/env python3
import csv
import html
import hashlib
import io
import json
import os
import pathlib
import re
import sys
import urllib.request
from collections import OrderedDict

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
        return [], [], []

    headers = [h.strip() for h in rows[0]]
    norm_headers = [h.lower() for h in headers]
    raw_rows = []
    norm_rows = []

    for r in rows[1:]:
        values = (r + [""] * len(headers))[: len(headers)]
        if not any(v.strip() for v in values):
            continue
        cleaned = [v.strip() for v in values]
        raw_rows.append({headers[i]: cleaned[i] for i in range(len(headers))})
        norm_rows.append({norm_headers[i]: cleaned[i] for i in range(len(headers))})

    return headers, raw_rows, norm_rows

def escape(s: str) -> str:
    return html.escape(s if s is not None else "", quote=False)

def slugify(*parts: str) -> str:
    text = "-".join(p for p in parts if p)
    text = text.replace("–", "-").replace("—", "-")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "section"


def unique_slug(base: str, used: set[str]) -> str:
    slug = base or "section"
    counter = 2
    while slug in used:
        slug = f"{base}-{counter}"
        counter += 1
    used.add(slug)
    return slug


def format_number(value: float) -> str:
    if float(value).is_integer():
        value = int(value)
        if value and value % 1000 == 0:
            return f"{value // 1000}k"
        return str(value)
    return ("%.2f" % value).rstrip("0").rstrip(".")


def capitalise(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def format_job(category: str, item: str) -> str:
    category = (category or "").strip()
    item = (item or "").strip()
    cat_lower = category.lower()
    item_lower = item.lower()

    if cat_lower == "scheduled service":
        if not item:
            return "Scheduled Service"
        if item_lower == "maintenance":
            return "Maintenance"
        if "service" not in item_lower:
            return f"{item} Service"
        return item

    if cat_lower == "fluids":
        if not item:
            return "Fluids"
        if "change" not in item_lower:
            return f"{item} Change"
        return item

    return item or category or "—"


def format_miles_part(value: str) -> str:
    raw = (value or "").replace(",", "").strip()
    if not raw:
        return ""
    try:
        number = float(raw)
    except ValueError:
        return capitalise(value.strip())
    if number == 0:
        return ""
    label = format_number(number)
    return f"{label} miles"


def format_years_part(value: str) -> str:
    raw = (value or "").replace(",", "").strip()
    if not raw:
        return ""
    try:
        number = float(raw)
    except ValueError:
        return capitalise(value.strip())
    if number == 0:
        return ""
    if float(number).is_integer():
        number = int(number)
        unit = "year" if number == 1 else "years"
        return f"{number} {unit}"
    return f"{format_number(number)} years"


def format_interval(miles: str, years: str) -> str:
    parts = []
    miles_part = format_miles_part(miles)
    years_part = format_years_part(years)
    if miles_part:
        parts.append(miles_part)
    if years_part:
        parts.append(years_part)
    return " / ".join(parts) if parts else "—"


CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}
CURRENCY_SYMBOL = CURRENCY_SYMBOLS.get(CURRENCY.upper(), CURRENCY + " ")


def format_price(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "POA"
    candidate = raw.replace(",", "")
    try:
        number = float(candidate)
    except ValueError:
        return raw
    if float(number).is_integer():
        return f"{CURRENCY_SYMBOL}{int(number)}"
    return f"{CURRENCY_SYMBOL}{format_number(number)}"


GENERATION_RE = re.compile(r"^\s*([0-9]{2,4}[A-Za-z0-9]*)")


def extract_generation(model: str, variant: str, years: str) -> str:
    variant = (variant or "").strip()
    years = (years or "").strip()
    model = (model or "").strip()

    match = GENERATION_RE.match(variant)
    if match:
        return match.group(1)
    if years and any(c.isdigit() for c in years):
        return years
    if variant:
        return variant
    return model


def format_section_title(model: str, generation: str) -> str:
    model = (model or "").strip()
    generation = (generation or "").strip()
    if not generation or generation.lower() == model.lower():
        return model

    normalised = generation.replace("–", "-")
    if re.fullmatch(r"[0-9]{2,4}(?:-[0-9]{2,4})?", normalised):
        return f"{model} ({generation})"
    if generation.lower().startswith(model.lower()):
        remainder = generation[len(model) :].strip(" -–/")
        return f"{model} {remainder}" if remainder else model
    if re.fullmatch(r"[0-9]{2,4}[A-Za-z]?", generation):
        return f"{model} ({generation})"
    return f"{model} {generation}" if model else generation


def format_variant_heading(
    model: str,
    generation: str,
    variant: str,
    years: str,
    powertrain: str,
    transmission: str,
) -> str:
    name = (variant or "").strip()
    generation = (generation or "").strip()
    if generation and name.lower().startswith(generation.lower()):
        name = name[len(generation) :].strip()
        name = name.lstrip("-–/").strip()

    extras = [x.strip() for x in (years or "", powertrain or "", transmission or "") if x and x.strip()]
    if name and extras:
        return f"{name} ({', '.join(extras)})"
    if not name and extras:
        return ", ".join(extras)
    return name


def format_combination_title(
    model: str,
    generation: str,
    variant: str,
    years: str,
    powertrain: str,
    transmission: str,
) -> str:
    base = format_section_title(model, generation)
    heading = format_variant_heading(
        model,
        generation,
        variant,
        years,
        powertrain,
        transmission,
    )

    if base and heading:
        return f"{base} — {heading}"
    return heading or base or model or "Price list"


def format_row(row: dict) -> dict:
    job = format_job(row.get("service_category", ""), row.get("service_item", ""))
    interval = format_interval(row.get("interval_miles", ""), row.get("interval_years", ""))
    price = format_price(row.get("price_gbp_ex_vat", ""))
    return {
        "job": job,
        "interval": interval,
        "price": price,
        "service_category": row.get("service_category", ""),
        "service_item": row.get("service_item", ""),
        "interval_miles": row.get("interval_miles", ""),
        "interval_years": row.get("interval_years", ""),
        "raw_price": row.get("price_gbp_ex_vat", ""),
    }


def build_sections(rows: list[dict]) -> list[dict]:
    grouped: OrderedDict[
        tuple[str, str], OrderedDict[tuple[str, str, str, str], list[dict]]
    ] = OrderedDict()

    for row in rows:
        model = (row.get("model_family") or row.get("model") or "").strip()
        if not model:
            continue
        variant = (row.get("variant") or "").strip()
        years = (row.get("years") or "").strip()
        powertrain = (row.get("powertrain") or "").strip()
        transmission = (row.get("transmission") or "").strip()
        generation = extract_generation(model, variant, years)

        model_key = (model, generation)
        variant_key = (variant, years, powertrain, transmission)

        model_bucket = grouped.setdefault(model_key, OrderedDict())
        model_bucket.setdefault(variant_key, []).append(row)

    used_section_slugs: set[str] = set()
    used_model_slugs: set[str] = set()
    model_slug_map: dict[tuple[str, str], str] = {}
    structured_sections: list[dict] = []

    for (model, generation), variants in grouped.items():
        base_title = format_section_title(model, generation)
        model_slug = model_slug_map.get((model, generation))
        if model_slug is None:
            model_slug = unique_slug(slugify(model, generation), used_model_slugs)
            model_slug_map[(model, generation)] = model_slug

        for (variant, years, powertrain, transmission), entries in variants.items():
            section_title = format_combination_title(
                model, generation, variant, years, powertrain, transmission
            )
            section_slug = unique_slug(
                slugify(model, generation, variant, years, powertrain, transmission),
                used_section_slugs,
            )

            structured_sections.append(
                {
                    "model_family": model,
                    "generation": generation,
                    "variant": variant,
                    "years": years,
                    "powertrain": powertrain,
                    "transmission": transmission,
                    "slug": section_slug,
                    "model_slug": model_slug,
                    "model_title": base_title,
                    "title": section_title,
                    "rows": [format_row(e) for e in entries],
                }
            )

    return structured_sections


def render_price_sections(sections: list[dict]) -> str:
    lines = []
    outer_indent = "      "
    inner_indent = outer_indent + "  "
    lines.append(
        f'{outer_indent}<div class="mt-8 space-y-12" id="priceLists" aria-live="polite">'
    )

    for section in sections:
        attrs = [f'data-model="{escape(section["slug"])}"']
        if section.get("model_slug"):
            attrs.append(f'data-alias="{escape(section["model_slug"])}"')
        attr_str = " ".join(attrs)
        lines.append(f"{inner_indent}<section class=\"price-section hidden\" {attr_str}>")
        lines.append(
            f'{inner_indent}  <h3 class="text-2xl font-bold">{escape(section["title"])}</h3>'
        )
        rows = section.get("rows", [])
        if not rows:
            lines.append(
                f'{inner_indent}  <p class="mt-2 text-sm text-neutral-300">No price list is available for this model at the moment.</p>'
            )
        else:
            lines.append(
                f'{inner_indent}  <div class="mt-4 overflow-x-auto rounded-lg border border-white/10">'
            )
            lines.append(f'{inner_indent}    <table class="min-w-full table-auto text-sm">')
            lines.append(f'{inner_indent}      <thead class="bg-neutral-900/80">')
            lines.append(
                f'{inner_indent}        <tr><th class="px-4 py-3 text-left font-semibold">Job</th><th class="px-4 py-3 text-left font-semibold">Interval</th><th class="px-4 py-3 text-left font-semibold">Price (ex-VAT)</th></tr>'
            )
            lines.append(f'{inner_indent}      </thead>')
            lines.append(f'{inner_indent}      <tbody class="divide-y divide-white/10">')
            for item in rows:
                lines.append(
                    f'{inner_indent}        <tr><td class="px-4 py-3">{escape(item["job"])}</td><td class="px-4 py-3">{escape(item["interval"])}</td><td class="px-4 py-3">{escape(item["price"])}</td></tr>'
                )
            lines.append(f'{inner_indent}      </tbody>')
            lines.append(f'{inner_indent}    </table>')
            lines.append(f'{inner_indent}  </div>')
        lines.append(f"{inner_indent}</section>")

    lines.append(f"{outer_indent}</div>")
    return "\n".join(lines)


def render_datalist_options(sections: list[dict]) -> str:
    lines = ['              <option data-value="all" value="All models"></option>']
    seen: set[str] = set()
    for section in sections:
        model_slug = section.get("model_slug") or section["slug"]
        if model_slug in seen:
            continue
        seen.add(model_slug)
        model_title = section.get("model_title") or section["title"]
        lines.append(
            f'              <option data-value="{escape(model_slug)}" value="{escape(model_title)}"></option>'
        )
    return "\n".join(lines)


def build_json_payload(sections: list[dict]) -> list[dict]:
    payload = []
    for section in sections:
        payload.append(
            {
                "id": section["slug"],
                "title": section["title"],
                "model_family": section["model_family"],
                "generation": section["generation"],
                "variant": section.get("variant", ""),
                "years": section.get("years", ""),
                "powertrain": section.get("powertrain", ""),
                "transmission": section.get("transmission", ""),
                "model_slug": section.get("model_slug", ""),
                "model_title": section.get("model_title", ""),
                "items": section.get("rows", []),
            }
        )
    return payload


def replace_datalist_options(html_text: str, options_html: str) -> str:
    marker = '<datalist id="carOptions">'
    start = html_text.find(marker)
    if start == -1:
        return html_text
    start = html_text.find(">", start)
    if start == -1:
        return html_text
    start += 1
    end = html_text.find("</datalist>", start)
    if end == -1:
        return html_text
    return html_text[:start] + "\n" + options_html + "\n" + html_text[end:]


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
    headers, raw_rows, norm_rows = parse_csv(csv_text)

    if not raw_rows:
        print("No data rows found in CSV", file=sys.stderr)
        return

    available_keys: set[str] = set()
    for row in norm_rows:
        available_keys.update(row.keys())

    structured_keys = {"model_family", "variant", "service_category", "service_item"}
    legacy_keys = {"model", "job", "interval", "price"}

    target = pathlib.Path(TARGET_HTML)
    html_src = target.read_text(encoding="utf-8")
    html_out = html_src
    json_payload = None

    if structured_keys.issubset(available_keys):
        sections = build_sections(norm_rows)
        html_markup = render_price_sections(sections)
        html_out = replace_between_markers(html_out, MARK_START, MARK_END, html_markup)
        html_out = replace_datalist_options(html_out, render_datalist_options(sections))
        json_payload = build_json_payload(sections)
    elif legacy_keys.issubset(available_keys):
        html_table = render_table(headers, raw_rows)
        html_out = replace_between_markers(html_out, MARK_START, MARK_END, html_table)
        json_payload = raw_rows
    else:
        raise RuntimeError("CSV headers not recognised; cannot build price list")

    if JSON_OUT and json_payload is not None:
        write_if_changed(JSON_OUT, json.dumps(json_payload, indent=2, ensure_ascii=False))

    if WRITE_JSONLD:
        jsonld = maybe_make_jsonld(headers, raw_rows)
        if jsonld:
            html_out = replace_between_markers(html_out, JSONLD_START, JSONLD_END, jsonld)

    if html_out != html_src:
        target.write_text(html_out, encoding="utf-8")

if __name__ == "__main__":
    main()
