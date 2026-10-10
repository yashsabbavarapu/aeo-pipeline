"""Brief in, citation-ready Markdown page out.

Generation is template and rule based, and deterministic: the same brief
always yields byte-identical output. Nothing on the page is invented. Every
sentence comes from a brief field; where the brief has no data, the page
says so ("Not stated") or leaves a visible placeholder the scorer will flag.
"""

import json
import re
from datetime import date

from .brief import Brief
from .rules import PLACEHOLDER_ANSWER

NOT_STATED = "Not stated"

_WHAT_IS = re.compile(r"(?i)^\s*what\s+(?:is|are)\s+(?:an?\s+|the\s+)?(.+?)\s*\??\s*$")


def generate_page(brief: Brief, updated: date | None = None) -> str:
    """Render the page. ``updated`` overrides the brief's freshness date.

    If neither is set, today's date is used, which is the one input that can
    make two runs differ. The bundled fixtures always set ``updated``.
    """
    stamp = (updated or brief.updated or date.today()).isoformat()
    parts = [
        f"# {brief.product}",
        "",
        f"> {brief.description}",
        "",
        f"Last updated: {stamp}",
        "",
        f"**Who it is for:** {_sentence(brief.audience)}",
        "",
        definitions_section(brief),
        claims_section(brief),
        comparison_section(brief),
        faq_section(brief),
        schema_section(build_jsonld(brief, faq_pairs(brief), stamp)),
    ]
    return "\n".join(parts).rstrip() + "\n"


def definitions_section(brief: Brief) -> str:
    lines = ["## Definitions", ""]
    lines += [definition_line(e.name, e.definition) for e in brief.entities]
    return "\n".join(lines) + "\n"


def definition_line(term: str, definition: str) -> str:
    return f"- **{term}**: {_sentence(definition)}"


def claims_section(brief: Brief) -> str:
    lines = ["## Key facts", ""]
    for claim in brief.claims:
        lines.append(f"- {_sentence(claim.text)} {source_note(claim.source, claim.url)}")
    return "\n".join(lines) + "\n"


def source_note(source: str, url: str = "") -> str:
    """The inline source marker the scorer looks for: ``(Source: Name, <url>)``."""
    return f"(Source: {source}" + (f", <{url}>" if url else "") + ")"


def comparison_section(brief: Brief) -> str:
    """A table of only the attributes the brief states, for any product.

    Always rendered. With no competitors in the brief the table has only the
    product column, and the scorer deducts for the missing comparison.
    """
    columns = [(brief.product, dict(brief.product_attributes))]
    columns += [(c.name, dict(c.attributes)) for c in brief.competitors]
    attributes: list[str] = []
    for _, attrs in columns:
        for name in attrs:
            if name not in attributes:
                attributes.append(name)
    rivals = [c.name for c in brief.competitors]
    if not rivals:
        intro = (
            f"The brief names no competitors for {brief.product}, so there is nothing to "
            "compare against yet. Add competitors to the brief to fill this table."
        )
    else:
        rivals_text = rivals[0] if len(rivals) == 1 else ", ".join(rivals[:-1]) + f" and {rivals[-1]}"
        intro = (
            f"How {brief.product} compares with {rivals_text}. Only attributes stated in the "
            f"product brief are shown. \"{NOT_STATED}\" means the brief has no data for that "
            "cell, not that the feature is missing."
        )
    lines = [
        "## Comparison",
        "",
        intro,
        "",
        "| Attribute | " + " | ".join(_cell(name) for name, _ in columns) + " |",
        "|" + "---|" * (len(columns) + 1),
    ]
    for attr in attributes:
        cells = [_cell(attrs.get(attr, NOT_STATED)) for _, attrs in columns]
        lines.append(f"| {_cell(attr)} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def answer_for(brief: Brief, question: str) -> str:
    """The direct answer for a question, drawn only from the brief.

    Order: an answer written in the brief; for "What is X?" the entity's
    definition; otherwise a visible placeholder the scorer flags.
    """
    for seed in brief.faq:
        if seed.question.strip().lower() == question.strip().lower() and seed.answer:
            return _sentence(seed.answer)
    m = _WHAT_IS.match(question)
    if m:
        subject = m.group(1).strip().lower()
        for entity in brief.entities:
            if entity.name.lower() == subject:
                return _sentence(entity.definition)
        if subject == brief.product.lower():
            return _sentence(brief.description)
    return f"{PLACEHOLDER_ANSWER}: add a direct answer to this question in the brief."


def faq_pairs(brief: Brief) -> list[tuple[str, str]]:
    return [(_question(s.question), answer_for(brief, s.question)) for s in brief.faq]


def faq_section(brief: Brief) -> str:
    lines = ["## FAQ", ""]
    for question, answer in faq_pairs(brief):
        lines += [f"### {question}", "", answer, ""]
    return "\n".join(lines)


def build_jsonld(brief: Brief | None, faq: list[tuple[str, str]], stamp: str,
                 product: str = "", description: str = "") -> str:
    """schema.org JSON-LD with a Product node and an FAQPage node."""
    name = brief.product if brief else product
    desc = brief.description if brief else description
    product_node: dict[str, object] = {"@type": "Product", "name": name}
    if desc:
        product_node["description"] = desc
    if brief and brief.url:
        product_node["url"] = brief.url
    if brief:
        product_node["audience"] = {"@type": "Audience", "audienceType": brief.audience}
    answered = [(q, a) for q, a in faq if not a.startswith(PLACEHOLDER_ANSWER)]
    faq_node: dict[str, object] = {
        "@type": "FAQPage",
        "dateModified": stamp,
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in answered
        ],
    }
    doc = {"@context": "https://schema.org", "@graph": [product_node, faq_node]}
    return json.dumps(doc, indent=2, ensure_ascii=False)


def schema_section(jsonld: str) -> str:
    return "\n".join([
        "## Structured data",
        "",
        "Paste this JSON-LD into a `<script type=\"application/ld+json\">` tag in the page head.",
        "",
        "```json",
        jsonld,
        "```",
        "",
    ])


def _sentence(text: str) -> str:
    t = " ".join(text.split())
    return t if t.endswith((".", "!", "?")) else t + "."


def _question(text: str) -> str:
    t = " ".join(text.split())
    return t if t.endswith("?") else t + "?"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")
