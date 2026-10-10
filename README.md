# aeo-pipeline

Brief in, citable page out, scored.

AI answer engines (ChatGPT search, Perplexity, Google AI Overviews, and the rest) tend to cite pages that are easy to quote: a crisp definition of each entity, claims with their sources attached, FAQ blocks whose answers come first, honest comparison tables, a visible freshness date, and schema.org markup. `aeo-pipeline` builds pages with that structure from a product brief, grades any Markdown page for it on a 0 to 100 scale with a line-by-line list of deductions, and applies a deterministic fix pass that moves the score up.

Python 3.11+, standard library only, zero runtime dependencies.

## Quick start

```sh
pip install -e ".[dev]"     # or: export PYTHONPATH=src

python -m aeo_pipeline generate --brief examples/briefs/devtool.yaml --output page.md
python -m aeo_pipeline score    --page page.md
python -m aeo_pipeline revise   --page examples/pages/sloppy.md --output page-v2.md
python -m aeo_pipeline history  --page examples/pages/sloppy.md
```

The installed console script `aeo-pipeline` takes the same arguments.

## Architecture

```
  brief.yaml
      |
      v
  yamlish.py + brief.py      strict YAML subset -> validated, frozen Brief
      |
      v
  generate.py                templates + rules, deterministic, never invents
      |
      v
  page.md  <------------------------------------------+
      |                                               |
      v                                               |
  page.py                    Markdown model: lines, headings,
      |                      tables, code blocks, sections
      |                                               |
      +--------------------+                          |
      |                    |                          |
      v                    v                          |
  score.py <-- rules.py --> revise.py ----------------+
  8 checks,    shared      one deterministic fix pass,
  0 to 100,    detection   then re-score
  line-level   rules
  deductions
      |
      v
  storage.py                 SQLite: briefs, page versions (parent links),
                             score history

  cli.py: generate | score | revise | history
```

The scorer and the reviser read the same detection rules from `rules.py`, so the reviser fixes exactly what the scorer flags and the two cannot drift apart.

## What a generated page contains

Every page from `generate` has, in order:

1. An H1 with the product name, the brief's description as a lead quote, and `Last updated: YYYY-MM-DD`.
2. **Definitions**: each brief entity as `- **Term**: one sentence.`
3. **Key facts**: every brief claim followed by `(Source: name, <url>)`.
4. **Comparison**: a table of the product vs each named competitor, using only attributes the brief states. Missing cells read "Not stated". With no competitors in the brief, the section still renders and says so, and the scorer deducts.
5. **FAQ**: each brief question as an H3 with the direct answer on the next line. Answers come from the brief, or for "What is X?" from the entity definition. Anything else gets a visible `Answer needed` placeholder rather than an invented answer.
6. **Structured data**: a fenced `json` block with schema.org JSON-LD (`Product` and `FAQPage`). Placeholder answers are left out of the JSON-LD.

The same brief always produces byte-identical output. The only input that can vary is the freshness date when the brief has no `updated` field, in which case it falls back to today; pass `--updated` to pin it.

## Scoring rubric

Eight checks, 100 points. Each check starts at its weight and loses points per deduction, never below zero. Deductions past zero are still listed, marked "check already at 0", so the report is complete. Every deduction names its line, or `page` when the problem is something missing from the whole page.

| Check | Points | Deductions |
|---|---|---|
| Entity definitions | 20 | No Definitions section: 20. Section with no `- **Term**:` entries: 20. Each definition that is not crisp (more than one sentence, over 30 words, or no "is / are / refers to / means / describes"): 4. With a brief, each brief entity not defined: 5. |
| Claim-to-source binding | 20 | A claim is any bullet in a claims section (Key facts, Evidence, Claims, ...) and any other prose line with a statistic (percent, multiplier, money, counts of time or people). No `(Source: ...)` on the line: 5. Only a `source needed` placeholder: 2. Definitions and tables are exempt. |
| FAQ coverage | 20 | No FAQ section: 20. Each question written as plain text (`Q: ...?` or `**...?**`) instead of an H3: 2. H3 with no answer: 4. Placeholder answer: 3. Answer that opens with a list, table, or quote instead of a direct sentence: 2. With a brief, each brief question not answered as an H3: 20 divided by the number of brief questions (fuzzy match). Without a brief, an FAQ with no H3 questions: 20. |
| Comparison table | 10 | No table: 10. No competitor column: 5. No rows: 3. With a brief, each named competitor missing from the header: 2. |
| Freshness date | 5 | No `Last updated:` / `Updated:` / `As of:` line: 5. Date that is not YYYY-MM-DD: 3. |
| Heading structure | 10 | No H1, or each extra H1: 4. Each skipped level (H2 to H4): 2. Each empty section: 2. |
| Sourced superlatives | 10 | "best", "leading", "fastest", "#1", "world-class", "most trusted", and similar, with no source on the same line: 5. Only a placeholder source: 2. Question headings are exempt, since people do ask "what is the best X?". |
| Structured data | 5 | No JSON-LD block: 5. Block that does not parse: 5. No `FAQPage` node: 2. No `Product` node: 2. |

Pass `--brief` to check FAQ and entity coverage against the brief. Without it, `score` looks up the brief the page was generated or revised from in the database, and if there is none it scores against the page alone (and says so).

## Demo walkthrough

### 1. Brief to page

```sh
$ python -m aeo_pipeline generate --brief examples/briefs/fintech.yaml --output page.md
Wrote page.md (122 lines) from examples/briefs/fintech.yaml
Citation-worthiness: 100/100
```

The output for both example briefs is checked in as `examples/pages/clearpond.md` and `examples/pages/spanlens.md`. A test asserts the generator still reproduces them byte for byte.

### 2. Score a page someone wrote by hand

`examples/pages/sloppy.md` is the kind of page the pipeline exists to fix: marketing superlatives, unsourced numbers, questions as plain text, a skipped heading level, an empty section.

```sh
$ python -m aeo_pipeline score --page examples/pages/sloppy.md
Citation-worthiness: 16/100  (examples/pages/sloppy.md)
No brief given: FAQ and entity coverage are checked against the page only.

Checks:
  Entity definitions         0/20
  Claim-to-source binding   10/20
  FAQ coverage               0/20
  Comparison table           0/10
  Freshness date             0/5
  Heading structure          6/10
  Sourced superlatives       0/10
  Structured data            0/5

Deductions (13):
  page      definitions  -20  no Definitions section: add '## Definitions' with one '- **Term**: Term is ...' bullet per key entity
  line 9    claims       -5   claim has no source (contains a statistic): add '(Source: ...)' on the same line
  line 10   claims       -5   claim has no source (contains a statistic): add '(Source: ...)' on the same line
  line 18   faq          -2   question is plain text: make it an H3 ('### ...?') with the answer directly below
  line 21   faq          -2   question is plain text: make it an H3 ('### ...?') with the answer directly below
  line 16   faq          -16  FAQ section has no H3 questions
  page      comparison   -10  no comparison table: add a table of attributes vs named competitors
  page      freshness    -5   no freshness date: add 'Last updated: YYYY-MM-DD' under the title
  line 12   headings     -2   heading jumps from H2 to H4
  line 24   headings     -2   section 'Pricing' is empty
  line 3    superlatives -5   superlative 'best' has no source on the same line
  line 7    superlatives -5   superlative 'leading' has no source on the same line
  page      schema       -5   no schema.org JSON-LD block: add a fenced ```json block with FAQPage and Product
```

`--json` prints the same report as JSON. `--min-score N` exits 1 below N, for use in CI.

### 3. Revise

```sh
$ python -m aeo_pipeline revise --page examples/pages/sloppy.md --output sloppy-v2.md --updated 2026-10-10
Revised examples/pages/sloppy.md -> sloppy-v2.md
Citation-worthiness: 16 -> 80 (+64)
No brief: definitions and sources come from the page or become placeholders.

Changes applied (9):
  - line 12: heading 'Security' H4 -> H3 (no skipped levels)
  - line 3: superlative 'best' marked 'source needed'
  - line 7: superlative 'leading' marked 'source needed'
  - line 9: claim marked 'source needed'
  - line 10: claim marked 'source needed'
  - added a freshness date: 'Last updated: 2026-10-10'
  - added a Definitions section from sentences already on the page: Clearpond
  - turned 2 plain-text question(s) into H3 FAQ entries
  - added a schema.org JSON-LD block (Product + FAQPage)

Remaining deductions (6), for a human to fix:
  line 15   claims       -2   claim source is a placeholder (contains a statistic): replace 'source needed'
  line 16   claims       -2   claim source is a placeholder (contains a statistic): replace 'source needed'
  page      comparison   -10  no comparison table: add a table of attributes vs named competitors
  line 32   headings     -2   section 'Pricing' is empty
  line 5    superlatives -2   superlative 'best' is backed only by a 'source needed' placeholder
  line 13   superlatives -2   superlative 'leading' is backed only by a 'source needed' placeholder
```

Give it the brief and it can do more, because now it has real data: claims that match a brief claim get that claim's actual source, missing entities and brief questions are added, and the comparison table is built from the brief's attributes.

```sh
$ python -m aeo_pipeline revise --page examples/pages/sloppy.md --brief examples/briefs/fintech.yaml --output sloppy-v3.md
Revised examples/pages/sloppy.md -> sloppy-v3.md
Citation-worthiness: 16 -> 94 (+78)
```

The remaining 6 points are deliberately left for a human: the superlatives need a real source or a rewrite, and the empty Pricing section needs content or removal. The reviser does not delete what an author wrote.

The fix pass is one pass, deterministic, and idempotent: revising a revised page changes nothing, and a page that already scores 100 comes back byte-identical.

### 4. History

```sh
$ python -m aeo_pipeline history --page sloppy-v3.md
Score history for sloppy-v3.md:
  2026-10-10T21:02:27+00:00   94/100  revised    page 70101b01e2d6
```

Every command records the brief, each page version (revisions link to their parent), and every score in a SQLite file: `aeo-pipeline.db` in the working directory, or `--db PATH`, or `$AEO_PIPELINE_DB`. `--no-db` turns storage off.

## Brief format

See `examples/briefs/`. Required: `product`, `description`, `audience`, `entities` (name, definition), `claims` (text, source, optional url), `faq` (question, optional answer). Optional: `url`, `updated` (YYYY-MM-DD), `attributes` (the product's comparison attributes), `competitors` (name, attributes).

Briefs are parsed by a small strict YAML subset loader (`yamlish.py`): block mappings and sequences, quoted and plain scalars, comments. Flow collections, anchors, block scalars, and tags are rejected with a line number rather than half-supported.

## What v1 does NOT do

Be clear about these before relying on a score.

- **Generation is rule and template based, not an LLM.** It assembles the page from brief fields. It will not write persuasive prose, and it will not fill a gap: a question the brief does not answer gets a visible `Answer needed` placeholder.
- **The scorer is a heuristic, not an answer-engine probe.** It measures structure that is widely associated with being cited. It never queries ChatGPT, Perplexity, or any other engine, so a 100 means "well structured", not "will be cited". Claim detection is pattern based (bullets in a claims section, lines with statistics), so a claim with no number outside a claims section can slip through.
- **"Sourced" means a source marker is present, not that the source is real or says what the claim says.** Nothing is fetched or verified.
- **Freshness is checked for presence and format, not age.** A page last updated in 2019 passes.
- **The revise pass is mechanical.** It adds placeholders and structure. It does not rewrite superlatives, merge duplicate content, or fill empty sections.
- **Markdown only**, and only the subset `page.py` models (ATX headings, bullets, pipe tables, fenced code). No HTML input.
- **All fixtures are synthetic.** Spanlens, Clearpond, Ledgerline, Tinyform, their competitors, and every source cited in the examples are fictional.

## v2 roadmap

- **LLM drafting behind the same interface.** A `Drafter` that produces the same section structure from the brief, with the rule-based generator kept as the deterministic fallback and as the test oracle. The scorer stays the gate: a draft has to score at least as well as the template.
- **Live measurement through ai-answer-monitor.** Feed generated and revised pages to ai-answer-monitor to record whether answer engines actually cite them for the brief's questions, and store those results next to the heuristic score so the rubric weights can be fitted to real citation data instead of set by hand.
- **Sitemap-scale runs.** Score and revise every page in a sitemap or directory in one command, with per-page history in the same database and a summary of the most common deductions across the site.

## Development

```sh
pip install -e ".[dev]"
pytest -q
mypy src tests        # strict mode, configured in pyproject.toml
```

CI runs both on Python 3.11 and 3.12.

## License

MIT
