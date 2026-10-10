# Spanlens

> Spanlens is a local-first trace debugger that lets engineers replay OpenTelemetry traces on their laptop without sending data to a vendor.

Last updated: 2026-10-01

**Who it is for:** Backend and platform engineers who debug distributed systems.

## Definitions

- **Spanlens**: Spanlens is a local-first debugger that replays OpenTelemetry traces on a developer laptop.
- **OpenTelemetry**: OpenTelemetry is an open standard and toolkit for collecting traces, metrics, and logs from software.
- **Trace replay**: Trace replay is the practice of re-running a recorded request path step by step to find where it failed.
- **Local-first**: Local-first describes software that keeps the primary copy of your data on your own machine instead of a vendor server.

## Key facts

- Spanlens loads a 50,000-span trace in under 2 seconds on a 2023 laptop. (Source: Spanlens internal benchmark, September 2026, <https://spanlens.example.com/benchmarks>)
- Teams in the design-partner program cut median time-to-root-cause from 47 minutes to 18 minutes. (Source: Spanlens design-partner study, n=12 teams)
- Spanlens was rated the fastest setup among trace debuggers in the survey. (Source: 2026 Example DevTools Survey)
- Spanlens reads any OTLP export, so no code changes are required to start. (Source: OpenTelemetry OTLP specification, <https://opentelemetry.io/docs/specs/otlp/>)

## Comparison

How Spanlens compares with Spantrail Cloud and Ochre APM. Only attributes stated in the product brief are shown. "Not stated" means the brief has no data for that cell, not that the feature is missing.

| Attribute | Spanlens | Spantrail Cloud | Ochre APM |
|---|---|---|---|
| Deployment | Runs locally on macOS, Linux, Windows | Hosted SaaS | Hosted SaaS or self-hosted cluster |
| Data leaves your machine | No | Yes | Depends on deployment |
| OpenTelemetry native | Yes | Yes | Not stated |
| Pricing model | Free for individuals, per-seat for teams | Not stated | Usage-based |

## FAQ

### What is Spanlens?

Spanlens is a local-first debugger that replays OpenTelemetry traces on a developer laptop.

### Does Spanlens send my trace data to the cloud?

No. Spanlens reads traces from local OTLP files or a local collector, and nothing is uploaded.

### How is Spanlens different from a hosted APM?

A hosted APM stores your traces on its servers for dashboards and alerts. Spanlens is a debugger that keeps traces on your machine and focuses on replaying one request at a time.

### Do I need to change my instrumentation to use Spanlens?

No. If your services already emit OpenTelemetry data, Spanlens can read it as is.

### What is trace replay?

Trace replay is the practice of re-running a recorded request path step by step to find where it failed.

## Structured data

Paste this JSON-LD into a `<script type="application/ld+json">` tag in the page head.

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Product",
      "name": "Spanlens",
      "description": "Spanlens is a local-first trace debugger that lets engineers replay OpenTelemetry traces on their laptop without sending data to a vendor.",
      "url": "https://spanlens.example.com",
      "audience": {
        "@type": "Audience",
        "audienceType": "Backend and platform engineers who debug distributed systems"
      }
    },
    {
      "@type": "FAQPage",
      "dateModified": "2026-10-01",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "What is Spanlens?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "Spanlens is a local-first debugger that replays OpenTelemetry traces on a developer laptop."
          }
        },
        {
          "@type": "Question",
          "name": "Does Spanlens send my trace data to the cloud?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "No. Spanlens reads traces from local OTLP files or a local collector, and nothing is uploaded."
          }
        },
        {
          "@type": "Question",
          "name": "How is Spanlens different from a hosted APM?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "A hosted APM stores your traces on its servers for dashboards and alerts. Spanlens is a debugger that keeps traces on your machine and focuses on replaying one request at a time."
          }
        },
        {
          "@type": "Question",
          "name": "Do I need to change my instrumentation to use Spanlens?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "No. If your services already emit OpenTelemetry data, Spanlens can read it as is."
          }
        },
        {
          "@type": "Question",
          "name": "What is trace replay?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "Trace replay is the practice of re-running a recorded request path step by step to find where it failed."
          }
        }
      ]
    }
  ]
}
```
