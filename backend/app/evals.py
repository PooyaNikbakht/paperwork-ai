"""Evals: run a provider over the sample documents and score it against the ground truth.

    uv run python -m app.evals --provider=mock
    uv run python -m app.evals --provider=anthropic          # needs ANTHROPIC_API_KEY
    uv run python -m app.evals --provider=openai             # needs OPENAI_API_KEY and OPENAI_MODEL
    uv run python -m app.evals --provider=mock --json out.json

Reports field-level accuracy, line-item accuracy, how many known document problems the checks
catch, how many extraction mistakes the checks catch, and false alarms on clean documents.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.extraction import locate_sources, normalize
from app.models import FieldSpec, spec_for
from app.pages import normalized_image, parse_file
from app.pipeline import dup_key_for
from app.providers import build_provider
from app.providers.base import Extractor, ProviderError, SourceFile
from app.providers.mock import load_truths
from app.samples import load_manifest, sample_path
from app.settings import Settings
from app.validation import CheckContext, DuplicateHit, run_checks
from app.values import norm_key


@dataclass
class DocResult:
    file: str
    doc_type: str
    classified_as: str | None = None
    fields_right: int = 0
    fields_total: int = 0
    lines_right: int = 0
    lines_total: int = 0
    wrong: list[str] = field(default_factory=list)
    fired: list[str] = field(default_factory=list)  # failed checks
    warned: list[str] = field(default_factory=list)
    expected: list[str] = field(default_factory=list)
    numbers_wrong: bool = False
    error: str | None = None
    seconds: float = 0.0

    @property
    def problems_caught(self) -> bool:
        return all(e in self.fired for e in self.expected)

    @property
    def flagged(self) -> bool:
        return bool(self.fired or self.warned)


def same_value(kind: str, expected: Any, got: Any) -> bool:
    if expected is None or got is None:
        return expected is None and got is None
    if kind in ("money", "number"):
        try:
            return abs(float(expected) - float(got)) <= 0.011
        except (TypeError, ValueError):
            return False
    return norm_key(str(expected)) == norm_key(str(got))


async def eval_doc(
    provider: Extractor, entry: dict[str, Any], truth: dict[str, Any], custom: list[FieldSpec]
) -> tuple[DocResult, Any, Any]:
    res = DocResult(entry["file"], truth["doc_type"], expected=list(entry["expected_checks"]))
    data = sample_path(entry["file"]).read_bytes()
    parsed = await asyncio.to_thread(parse_file, data, entry["media_type"])
    send, media = (data, entry["media_type"])
    if media != "application/pdf":
        send, media = normalized_image(data)
    src = SourceFile(send, media, entry["file"], entry["sha256"], parsed.page_count, parsed.texts)
    start = time.perf_counter()
    try:
        res.classified_as = await provider.classify(src)
        spec = spec_for(truth["doc_type"], custom)
        raw = await provider.extract(src, spec)
    except ProviderError as exc:
        res.error = f"{exc.code}: {exc.message}"
        return res, None, parsed
    res.seconds = time.perf_counter() - start
    ex = normalize(raw, spec)
    await asyncio.to_thread(locate_sources, ex, data if src.is_pdf else None, parsed.has_text_layer)

    for f in spec.fields:
        expected = truth["fields"].get(f.key, {}).get("value")
        got = ex.value(f.key)
        res.fields_total += 1
        if same_value(f.type, expected, got):
            res.fields_right += 1
        else:
            res.wrong.append(f"{f.key}: expected {expected!r}, got {got!r}")
            if f.type in ("money", "number"):
                res.numbers_wrong = True
    if spec.has_lines:
        t_lines = truth["line_items"]
        for i, t in enumerate(t_lines):
            got_line = ex.line_items[i] if i < len(ex.line_items) else None
            for key, kind in (
                ("description", "text"),
                ("quantity", "number"),
                ("unit_price", "money"),
                ("amount", "money"),
            ):
                res.lines_total += 1
                got = getattr(got_line, key) if got_line else None
                if same_value(kind, t[key], got):
                    res.lines_right += 1
                else:
                    res.wrong.append(f"line {i + 1} {key}: expected {t[key]!r}, got {got!r}")
                    if kind != "text":
                        res.numbers_wrong = True
        extra = len(ex.line_items) - len(t_lines)
        if extra > 0:
            res.lines_total += extra * 4
            res.wrong.append(f"{extra} extra line item(s)")
            res.numbers_wrong = True
        t_taxes = [(t["kind"], t["amount"]) for t in truth["taxes"]]
        g_taxes = [(t.kind, t.amount) for t in ex.taxes]
        res.fields_total += 1
        if len(t_taxes) == len(g_taxes) and all(
            a[0] == b[0] and same_value("money", a[1], b[1])
            for a, b in zip(t_taxes, g_taxes, strict=True)
        ):
            res.fields_right += 1
        else:
            res.wrong.append(f"taxes: expected {t_taxes}, got {g_taxes}")
            res.numbers_wrong = True
    return res, ex, parsed


async def run(provider: Extractor, concurrency: int) -> list[DocResult]:
    manifest = load_manifest()
    truths = {t["file"]: t for t in load_truths().values()}
    custom = [FieldSpec(**f) for f in manifest["custom_fields"]]
    sem = asyncio.Semaphore(concurrency)

    async def one(entry: dict[str, Any]) -> tuple[DocResult, Any, Any]:
        async with sem:
            return await eval_doc(provider, entry, truths[entry["file"]], custom)

    outcomes = await asyncio.gather(*(one(e) for e in manifest["documents"]))

    # Checks run in manifest order, so duplicates behave as they would in one batch.
    seen: dict[str, str] = {}
    for res, ex, parsed in outcomes:
        if ex is None:
            continue
        key = dup_key_for(ex)
        dups = [DuplicateHit("", seen[key], True, False)] if key and key in seen else []
        if key and key not in seen:
            seen[key] = res.file
        ctx = CheckContext(
            page_texts=parsed.texts, has_text_layer=parsed.has_text_layer, duplicates=dups
        )
        for c in run_checks(ex, ctx):
            if c.status == "fail":
                res.fired.append(c.id)
            elif c.status == "warn":
                res.warned.append(c.id)
    return [r for r, _, _ in outcomes]


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.1%})" if b else "n/a"


def report(results: list[DocResult], provider: Extractor, elapsed: float) -> dict[str, Any]:
    ok = [r for r in results if r.error is None]
    fields = (sum(r.fields_right for r in ok), sum(r.fields_total for r in ok))
    lines = (sum(r.lines_right for r in ok), sum(r.lines_total for r in ok))
    with_problems = [r for r in ok if r.expected]
    caught = sum(r.problems_caught for r in with_problems)
    mistakes = [r for r in ok if r.numbers_wrong]
    mistakes_caught = sum(r.flagged for r in mistakes)
    clean = [r for r in ok if not r.expected and not r.wrong]
    false_alarms = sum(bool(r.fired) for r in clean)
    classified = sum((r.classified_as == r.doc_type) for r in ok if r.classified_as is not None)
    summary = {
        "provider": provider.name,
        "model": provider.model,
        "documents": len(results),
        "errors": len(results) - len(ok),
        "field_accuracy": fields,
        "line_item_accuracy": lines,
        "document_problems_caught": (caught, len(with_problems)),
        "extraction_mistakes_caught": (mistakes_caught, len(mistakes)),
        "false_alarms_on_clean_documents": (false_alarms, len(clean)),
        "classification_accuracy": (classified, len(ok)),
        "seconds": round(elapsed, 1),
    }

    label = "demo mode" if provider.name == "mock" else provider.model
    print(f"\nPaperwork AI evals: {provider.name} ({label}), {len(results)} sample documents\n")
    print(f"{'Document':40} {'Type':8} {'Fields':>7} {'Lines':>7}  {'Checks failed':26} Result")
    print("-" * 104)
    for r in results:
        if r.error:
            print(f"{r.file:40} {r.doc_type:8} {'':>7} {'':>7}  {'':26} error: {r.error}")
            continue
        fired = ", ".join(r.fired) or "-"
        if r.expected:
            result = "caught" if r.problems_caught else f"MISSED {', '.join(r.expected)}"
        elif r.numbers_wrong:
            result = "misread, flagged" if r.flagged else "misread, NOT flagged"
        elif r.fired:
            result = "false alarm"
        else:
            result = "ok"
        lines_col = f"{r.lines_right}/{r.lines_total}" if r.lines_total else "-"
        fields_col = f"{r.fields_right}/{r.fields_total}"
        print(f"{r.file:40} {r.doc_type:8} {fields_col:>7} {lines_col:>7}  {fired:26} {result}")
    print("\nSummary")
    print(f"  Field accuracy              {pct(*fields)}")
    print(f"  Line item accuracy          {pct(*lines)}")
    print(f"  Document problems caught    {pct(caught, len(with_problems))}")
    print(f"  Extraction mistakes caught  {pct(mistakes_caught, len(mistakes))}")
    print(f"  False alarms (clean docs)   {pct(false_alarms, len(clean))}")
    print(f"  Classification accuracy     {pct(classified, len(ok))}")
    print(f"  Time                        {elapsed:.1f}s")
    wrong = [(r.file, w) for r in ok for w in r.wrong]
    if wrong:
        print("\nMisreads")
        for file, w in wrong:
            print(f"  {file}: {w}")
    print()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--provider", choices=["mock", "anthropic", "openai"], default="mock")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--json", help="Also write the results to this file.")
    args = parser.parse_args(argv)

    settings = Settings(mock_delay_seconds=0)
    if args.provider == "anthropic" and not settings.anthropic_api_key:
        print("Set ANTHROPIC_API_KEY to evaluate Claude.", file=sys.stderr)
        return 2
    if args.provider == "openai" and not (settings.openai_api_key and settings.openai_model):
        print("Set OPENAI_API_KEY and OPENAI_MODEL to evaluate OpenAI.", file=sys.stderr)
        return 2
    provider = build_provider(settings, args.provider)

    start = time.perf_counter()
    results = asyncio.run(run(provider, args.concurrency))
    summary = report(results, provider, time.perf_counter() - start)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"summary": summary, "documents": [asdict(r) for r in results]}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
