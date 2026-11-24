"""Self-contained HTML report for one retrieval eval run, compared with a baseline if given.

``report.render_summary`` writes the Markdown summary; this renders the same
numbers as a page people can open in a browser or attach to a pull request:
headline figures with their change from the baseline, recall at each cutoff,
recall by tag, what changed question by question, the questions that missed,
and answer quality when the run scored answers.

Standard library only, with inline SVG charts and no external assets, so the
file works offline and can be unit-tested without the SDK or a stack. Every
value from the results file is escaped, because question text and file names
come from the dataset and the stack.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

# run_eval.py imports this module as a top-level script module, and the tests
# import it from the scripts.eval.retrieval package. A plain "import report"
# works only in the first case and "from . import report" only in the second.
report = importlib.import_module(f"{__package__}.report" if __package__ else "report")
diagnose = importlib.import_module(f"{__package__}.diagnose" if __package__ else "diagnose")

# A change smaller than this rounds to 0.000 at three decimals.
SHOWN_CHANGE = 0.0005
MAX_CHANGED_SHOWN = 25


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def noise_floor(results: Mapping[str, Any]) -> float:
    """The smallest change in an average that counts: half of one question's worth.

    Every metric is averaged over the questions, so one question moving one
    rank shifts an average by roughly 0.5 / questions or more. Anything smaller
    is rounding or run-to-run noise. The tiles, summary and table all use this.
    It never goes below ``SHOWN_CHANGE``, the smallest change three decimals can
    show, so on very large question sets the summary and tiles still agree.
    """
    count = len(results.get("queries") or ())
    return max(0.5 / count, SHOWN_CHANGE) if count else 0.005


def _delta(current: float, baseline: float | None, noise: float) -> str:
    """A change with an arrow and a sign, so it never relies on color alone.

    Changes under ``noise`` are shown muted, with "≈" and no arrow: the number
    stays visible but is not presented as a win or a loss.
    """
    if baseline is None:
        return ""
    change = current - baseline
    if abs(change) < SHOWN_CHANGE:
        return '<span class="delta same">no change</span>'
    if abs(change) < noise:
        return f'<span class="delta same">≈ {change:+.3f}<span class="sr"> (noise)</span></span>'
    good = change > 0  # every metric here is better when higher
    arrow, word = ("▲", "up") if good else ("▼", "down")
    return (
        f'<span class="delta {"good" if good else "bad"}">'
        f'<span aria-hidden="true">{arrow}</span> {change:+.3f}'
        f'<span class="sr"> ({word})</span></span>'
    )


# --- charts -----------------------------------------------------------------


def _bar_up(x: float, y: float, width: float, height: float, radius: float = 0.0) -> str:
    """A column path rising from the baseline; square, as Carbon charts draw them."""
    r = min(radius, width / 2, height)
    if height <= 0:
        return ""
    return (
        f"M{x:.1f},{y + height:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"H{x + width - r:.1f} Q{x + width:.1f},{y:.1f} {x + width:.1f},{y + r:.1f} "
        f"V{y + height:.1f} Z"
    )


def _bar_right(x: float, y: float, width: float, height: float, radius: float = 0.0) -> str:
    """A horizontal bar path from the baseline; square, as Carbon charts draw them."""
    r = min(radius, height / 2, width)
    if width <= 0:
        return ""
    return (
        f"M{x:.1f},{y:.1f} H{x + width - r:.1f} Q{x + width:.1f},{y:.1f} {x + width:.1f},{y + r:.1f} "
        f"V{y + height - r:.1f} Q{x + width:.1f},{y + height:.1f} {x + width - r:.1f},{y + height:.1f} "
        f"H{x:.1f} Z"
    )


def _legend(items: Sequence[tuple[str, str]]) -> str:
    """Swatch-and-text legend; identity never rests on color-matching alone."""
    return (
        '<ul class="legend">'
        + "".join(
            f'<li><span class="swatch {cls}" aria-hidden="true"></span>{_e(name)}</li>'
            for name, cls in items
        )
        + "</ul>"
    )


def column_chart(
    title: str,
    categories: Sequence[str],
    series: Sequence[tuple[str, str, Sequence[float | None]]],
    *,
    x_label: str,
    y_label: str,
) -> str:
    """Grouped columns on a 0–1 scale with axis titles. ``series`` is (name, css class, values).

    Each group is labeled once above its bars: the current value, or
    "baseline → current" when there are two series.
    """
    width, height = 560, 268
    left, right, top, bottom = 58, 8, 24, 52
    plot_w, plot_h = width - left - right, height - top - bottom
    band = plot_w / max(1, len(categories))
    bar = min(24.0, (band * 0.6 - 2 * (len(series) - 1)) / max(1, len(series)))
    group = bar * len(series) + 2 * (len(series) - 1)
    parts = [
        f'<text class="axis-title" transform="translate(14 {top + plot_h / 2:.1f}) rotate(-90)" '
        f'text-anchor="middle">{_e(y_label)}</text>',
        f'<text class="axis-title" x="{left + plot_w / 2:.1f}" y="{height - 6}" '
        f'text-anchor="middle">{_e(x_label)}</text>',
    ]
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        y = top + plot_h * (1 - tick)
        parts.append(
            f'<line class="grid{" base" if tick == 0 else ""}" x1="{left}" x2="{width - right}" '
            f'y1="{y:.1f}" y2="{y:.1f}"/>'
            f'<text class="tick" x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{tick:g}</text>'
        )
    for i, category in enumerate(categories):
        x0 = left + band * i + (band - group) / 2
        tallest = 0.0
        for j, (name, cls, values) in enumerate(series):
            value = values[i]
            if value is None:
                continue
            tallest = max(tallest, value)
            x = x0 + j * (bar + 2)
            h = plot_h * max(0.0, min(1.0, value))
            y = top + plot_h - h
            others = "; ".join(
                f"{other}: {_fmt(vals[i])}" for other, _, vals in series if other != name
            )
            tip = f"{_fmt(value)}\n{category}, {name}" + (f"\n{others}" if others else "")
            parts.append(
                f'<g class="mark" tabindex="0" data-tip="{_e(tip)}">'
                f'<rect class="hit" x="{x - 1:.1f}" y="{top}" width="{bar + 2:.1f}" '
                f'height="{plot_h}"/>'
                f'<path class="{cls}" d="{_bar_up(x, y, bar, h)}"/></g>'
            )
        shown = [values[i] for _, _, values in series if values[i] is not None]
        label = " → ".join(_fmt(v) for v in shown)
        parts.append(
            f'<text class="value" x="{x0 + group / 2:.1f}" '
            f'y="{top + plot_h * (1 - min(1.0, tallest)) - 6:.1f}" text-anchor="middle">'
            f"{_e(label)}</text>"
            f'<text class="tick" x="{left + band * (i + 0.5):.1f}" y="{top + plot_h + 18}" '
            f'text-anchor="middle">{_e(category)}</text>'
        )
    legend = _legend([(name, cls) for name, cls, _ in series]) if len(series) > 1 else ""
    return (
        f'<figure class="chart"><figcaption>{_e(title)}</figcaption>{legend}'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_e(title)}">'
        + "".join(parts)
        + "</svg></figure>"
    )


def tag_chart(
    title: str,
    rows: Sequence[tuple[str, int, float, float | None]],
    *,
    x_label: str,
) -> str:
    """Horizontal bars per tag: (tag, questions, current, baseline). Baseline is a tick.

    The scale runs 0–1 with ticks and an axis title; each bar is labeled with
    its value, and the baseline value beside it when there is one.
    """
    has_baseline = any(base is not None for *_, base in rows)
    label_w, width, row_h = 150, 560, 30
    plot_w = width - label_w - (128 if has_baseline else 56)
    rows_h = row_h * len(rows) + 4
    height = rows_h + 48
    parts = []
    for tick in (0, 0.5, 1.0):
        x = label_w + plot_w * tick
        parts.append(
            f'<line class="grid{" base" if tick == 0 else ""}" x1="{x:.1f}" x2="{x:.1f}" '
            f'y1="0" y2="{rows_h}"/>'
            f'<text class="tick" x="{x:.1f}" y="{rows_h + 16}" text-anchor="middle">{tick:g}</text>'
        )
    parts.append(
        f'<text class="axis-title" x="{label_w + plot_w / 2:.1f}" y="{height - 6}" '
        f'text-anchor="middle">{_e(x_label)}</text>'
    )
    for i, (tag, count, value, base) in enumerate(rows):
        y = i * row_h + 6
        w = plot_w * max(0.0, min(1.0, value))
        tip = f"{_fmt(value)}\n{tag} ({count} questions)" + (
            f"\nbaseline: {_fmt(base)}" if base is not None else ""
        )
        parts.append(
            f'<text class="label" x="{label_w - 8}" y="{y + 14}" text-anchor="end">{_e(tag)}'
            f'<tspan class="count"> {count}</tspan></text>'
            f'<g class="mark" tabindex="0" data-tip="{_e(tip)}">'
            f'<rect class="hit" x="{label_w}" y="{y - 3}" width="{plot_w}" height="{row_h - 2}"/>'
            f'<path class="current" d="{_bar_right(label_w, y, w, 18)}"/>'
        )
        end = label_w + w  # the label sits past the bar or the baseline tick, whichever is further
        if base is not None:
            bx = label_w + plot_w * max(0.0, min(1.0, base))
            end = max(end, bx)
            parts.append(
                f'<line class="baseline-halo" x1="{bx:.1f}" x2="{bx:.1f}" '
                f'y1="{y - 3}" y2="{y + 21}"/>'
                f'<line class="baseline-tick" x1="{bx:.1f}" x2="{bx:.1f}" '
                f'y1="{y - 3}" y2="{y + 21}"/>'
            )
        was = f'<tspan class="count"> (baseline {_fmt(base)})</tspan>' if base is not None else ""
        parts.append(
            f'</g><text class="value" x="{end + 8:.1f}" y="{y + 14}">{_fmt(value)}{was}</text>'
        )
    legend = (
        _legend([("Current run", "current"), ("Baseline", "baseline-key")]) if has_baseline else ""
    )
    return (
        f'<figure class="chart"><figcaption>{_e(title)}</figcaption>{legend}'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_e(title)}">'
        + "".join(parts)
        + "</svg></figure>"
    )


def change_bar(regressed: int, unchanged: int, improved: int) -> str:
    """One whole split into regressed, unchanged and improved questions."""
    total = regressed + unchanged + improved
    if total == 0:
        return ""
    width, height, gap = 900, 22, 2
    parts = []
    x = 0.0
    segments = [
        ("Regressed", "bad", regressed, "▼"),
        ("Unchanged", "same", unchanged, "●"),
        ("Improved", "good", improved, "▲"),
    ]
    shown = [s for s in segments if s[2]]
    usable = width - gap * (len(shown) - 1)
    for name, cls, count, _ in shown:
        w = usable * count / total
        parts.append(
            f'<g class="mark" tabindex="0" data-tip="{_e(f"{count} questions{chr(10)}{name}")}">'
            f'<rect class="seg {cls}" x="{x:.1f}" y="0" width="{w:.1f}" height="{height}"/>'
        )
        if w >= 28:
            parts.append(
                f'<text class="inside {cls}" x="{x + w / 2:.1f}" y="{height / 2 + 4.5}" '
                f'text-anchor="middle">{count}</text>'
            )
        parts.append("</g>")
        x += w + gap
    legend = (
        '<ul class="legend">'
        + "".join(
            f'<li><span class="swatch seg {cls}" aria-hidden="true"></span>'
            f'<span aria-hidden="true">{icon}</span> {name} {count}</li>'
            for name, cls, count, icon in segments
        )
        + "</ul>"
    )
    return (
        f'<figure class="chart"><figcaption>Questions compared with the baseline</figcaption>'
        f'{legend}<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{regressed} regressed, {unchanged} unchanged, {improved} improved">'
        + "".join(parts)
        + "</svg></figure>"
    )


# --- sections ---------------------------------------------------------------


# The recall clause of the verdict, then how ranking moved alongside it.
_RECALL_CLAUSE = {"up": "Recall improved", "down": "Recall fell", "flat": "Recall held steady"}
_RANK_CLAUSE = {
    ("up", "down"): (", but ", "relevant results tend to rank lower"),
    ("up", "up"): (", and ", "relevant results rank higher"),
    ("up", "flat"): (", with ", "ranking about the same"),
    ("down", "up"): (", though ", "the files that are found rank higher"),
    ("down", "down"): (", and ", "relevant results rank lower"),
    ("down", "flat"): (", with ", "ranking about the same"),
    ("flat", "up"): (", and ", "relevant results rank higher"),
    ("flat", "down"): (", but ", "relevant results tend to rank lower"),
}
_TONE = {"up": "good", "down": "bad", "flat": "same"}

# A run of text with an optional tone: good, bad or same (muted). Toned runs are bold.
Segment = tuple[str, str | None]


def _direction(change: float | None, noise: float) -> str:
    if change is None or abs(change) < noise:
        return "flat"
    return "up" if change > 0 else "down"


def _move(aggregate: Mapping[str, Mapping[str, float]], name: str, noise: float) -> list[Segment]:
    move = aggregate[name]
    tone = _TONE[_direction(move["delta"], noise)]
    return [
        (f"{report._label(name)} {_fmt(move['baseline'])} → ", None),
        (f"{_fmt(move['current'])} ({move['delta']:+.3f})", tone),
    ]


def summary_parts(
    results: Mapping[str, Any], diff: Mapping[str, Any] | None
) -> tuple[list[Segment], list[list[Segment]], float]:
    """The verdict and its supporting points as toned segments, plus the noise floor.

    With a baseline, the verdict pairs what happened to recall@k (are the right
    files found) with what happened to MRR (do they rank near the top), so a
    trade-off between the two is stated outright, each part in its own color.
    """
    run = results["run"]
    k = run["primary_k"]
    overall = results["metrics"].get("overall", {})
    noise = noise_floor(results)
    if diff is None:
        points: list[list[Segment]] = [
            [
                (
                    f"On average, {overall[f'recall@{k}'] * 100:.0f}% of each question's expected "
                    f"files are in the top {k} results (recall@{k} {_fmt(overall[f'recall@{k}'])}).",
                    None,
                )
            ]
        ]
        # How often a question succeeds at rank 1 is not recall@1: a question
        # expecting two files, ranked first and second, has recall@1 0.5 but a
        # relevant file first every time. A reciprocal rank of 1 is that success.
        queries = results["queries"]
        first = sum(
            1 for q in queries if q["metrics"].get("reciprocal_rank", 0) >= 1 - report.EPSILON
        )
        rank_one = (
            f"; recall@1, the share of each question's expected files at rank 1, is "
            f"{_fmt(overall['recall@1'])}"
            if "recall@1" in overall
            else ""
        )
        points.append(
            [
                (
                    f"A relevant file is ranked first for {first / len(queries) * 100:.0f}% of "
                    f"questions ({first} of {len(queries)}){rank_one}.",
                    None,
                )
            ]
        )
        tags = results["metrics"].get("by_tag", {})
        scored = {t: v[f"recall@{k}"] for t, v in tags.items() if f"recall@{k}" in v}
        if len(scored) > 1:
            weakest = min(scored, key=lambda t: scored[t])
            points.append([(f"Weakest tag: {weakest} (recall@{k} {_fmt(scored[weakest])}).", None)])
        verdict: list[Segment] = [
            (
                f"Recall@{k} is {_fmt(overall[f'recall@{k}'])} and MRR is {_fmt(overall.get('mrr'))}.",
                None,
            )
        ]
        return verdict, points, noise

    aggregate = diff["aggregate"]
    recall = diff["compare_metrics"][0]
    found = _direction(aggregate.get(recall, {}).get("delta"), noise)
    ranked = _direction(aggregate.get("mrr", {}).get("delta"), noise)
    if (found, ranked) == ("flat", "flat"):
        verdict = [("No meaningful change: recall and ranking held steady.", "same")]
    else:
        joiner, rank_text = _RANK_CLAUSE[(found, ranked)]
        verdict = [
            (_RECALL_CLAUSE[found], _TONE[found]),
            (joiner, None),
            (rank_text, _TONE[ranked]),
            (".", None),
        ]
    points = []
    if recall in aggregate:
        what = {"up": "more", "down": "fewer", "flat": "about as many"}[found]
        # The comparison may fall back to a cutoff both runs have (see compare_k).
        compared_k = recall.partition("@")[2] or k
        points.append(
            [
                *_move(aggregate, recall, noise),
                (f": {what} expected files reach the top {compared_k}.", None),
            ]
        )
    if "mrr" in aggregate:
        where = {"up": "higher", "down": "lower", "flat": "about as high"}[ranked]
        points.append(
            [
                *_move(aggregate, "mrr", noise),
                (f": the first relevant file sits {where} on average.", None),
            ]
        )
    if "passage_mrr" in aggregate:
        answer = _direction(aggregate["passage_mrr"]["delta"], noise)
        how = {"up": "nearer the top", "down": "further down", "flat": "about where it was"}[answer]
        points.append(
            [
                *_move(aggregate, "passage_mrr", noise),
                (f": the chunk holding the answer ranks {how}.", None),
            ]
        )
    regressed, improved = len(diff["regressed"]), len(diff["improved"])
    points.append(
        [
            ("Question by question: ", None),
            (f"{regressed} regressed", "bad" if regressed else "same"),
            (", ", None),
            (f"{improved} improved", "good" if improved else "same"),
            (", ", None),
            (f"{diff['unchanged']} unchanged", "same"),
            (".", None),
        ]
    )
    if diff.get("warnings"):
        points.append(
            [
                (
                    "The runs differ in setup (see the warning above), so part of this change "
                    "may come from that.",
                    None,
                )
            ]
        )
    return verdict, points, noise


def summary(results: Mapping[str, Any], diff: Mapping[str, Any] | None) -> tuple[str, list[str]]:
    """The verdict and points as plain text (see ``summary_parts``)."""
    verdict, points, _ = summary_parts(results, diff)
    return "".join(t for t, _ in verdict), ["".join(t for t, _ in p) for p in points]


def _segments(parts: Sequence[Segment]) -> str:
    return "".join(
        f'<strong class="tone {tone}">{_e(text)}</strong>' if tone else _e(text)
        for text, tone in parts
    )


def _summary(results: Mapping[str, Any], diff: Mapping[str, Any] | None) -> str:
    verdict, points, noise = summary_parts(results, diff)
    items = "".join(f"<li>{_segments(point)}</li>" for point in points)
    count = len(results.get("queries") or ())
    note = (
        f'<p class="summary-note">Changes under {noise:.3f} (half of one question\'s worth '
        f"across {count} questions) are treated as noise and shown in gray.</p>"
        if diff is not None
        else ""
    )
    return (
        '<section class="summary"><h2>Summary</h2>'
        f'<p class="verdict">{_segments(verdict)}</p><ul class="points">{items}</ul>{note}</section>'
    )


def _tiles(
    names: Sequence[str],
    overall: Mapping[str, float],
    base: Mapping[str, float],
    noise: float,
) -> str:
    tiles = []
    for name in names:
        if name not in overall:
            continue
        value = overall[name]
        before = base.get(name)
        sub = f'<div class="was">baseline {_fmt(before)}</div>' if before is not None else ""
        tiles.append(
            f'<div class="tile"><div class="tile-label">{_e(report._label(name))}</div>'
            f'<div class="tile-value">{_fmt(value)}</div>{_delta(value, before, noise)}{sub}</div>'
        )
    return f'<div class="tiles">{"".join(tiles)}</div>' if tiles else ""


def _meta(results: Mapping[str, Any]) -> str:
    run = results["run"]
    rows = [
        ("Time", run["timestamp"]),
        ("Target", run["target_url"]),
        ("Commit", (run.get("git_commit") or "unknown")[:12]),
        ("Dataset", f"{run['corpus_files']} documents, {run['query_count']} questions"),
        (
            "Search",
            f"fetch limit {run['fetch_limit']}, score threshold {run['score_threshold']}",
        ),
        ("Settings", report._settings_line(results)),
    ]
    return (
        '<details class="run-details"><summary>Run details</summary><dl class="meta">'
        + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in rows if v)
        + "</dl></details>"
    )


# Carbon's filled status icons at 16px: a colored disc with a glyph cut in contrast.
_ICONS = {
    "warning": (
        '<circle cx="8" cy="8" r="7" class="disc"/>'
        '<rect x="7.25" y="3.75" width="1.5" height="5.5" class="glyph"/>'
        '<circle cx="8" cy="11.5" r="1" class="glyph"/>'
    ),
    "info": (
        '<circle cx="8" cy="8" r="7" class="disc"/>'
        '<circle cx="8" cy="4.75" r="1" class="glyph"/>'
        '<rect x="7.25" y="6.75" width="1.5" height="5" class="glyph"/>'
    ),
}


def notification(kind: str, title: str, body: str) -> str:
    """A Carbon inline notification (low contrast, not dismissible).

    ``kind`` is ``warning`` or ``info``, the two statuses Carbon allows for a
    notice that loads with the page. The icon and title carry the status, so
    it never rests on color alone.
    """
    return (
        f'<div class="notification {kind}" role="status">'
        f'<svg class="notification-icon" viewBox="0 0 16 16" width="16" height="16" '
        f'aria-hidden="true">{_ICONS[kind]}</svg>'
        f'<p class="notification-text"><span class="notification-title">{_e(title)}</span> '
        f'<span class="notification-body">{_e(body)}</span></p></div>'
    )


def _callouts(diff: Mapping[str, Any] | None) -> str:
    if diff is None:
        return ""
    items = [notification("warning", "Runs differ", w) for w in diff.get("warnings", ())]
    items += [notification("info", "Note", n) for n in diff.get("notes", ())]
    return f'<div class="notifications">{"".join(items)}</div>' if items else ""


def _rank_change(entry: Mapping[str, Any]) -> str:
    ranks = entry["expected_ranks"]
    missing = entry.get("snippet_missing", {})
    parts = []
    for name in ranks["current"].keys() | ranks["baseline"].keys():
        before, after = ranks["baseline"].get(name), ranks["current"].get(name)
        note = " (snippet not found)" if name in missing.get("current", ()) else ""

        def show(rank: int | None) -> str:
            return "not returned" if rank is None else f"#{rank}"

        parts.append(
            f"<li><code>{_e(name)}</code> {_e(show(before))} → "
            f"<strong>{_e(show(after))}</strong>{_e(note)}</li>"
        )
    return f'<ul class="ranks">{"".join(sorted(parts))}</ul>'


def _deciding_move(
    entry: Mapping[str, Any], metrics: Sequence[str]
) -> tuple[str, Mapping[str, float]] | None:
    """The metric that classified this question, the first in ``metrics`` that moved."""
    for name in metrics:
        delta = entry["metrics"].get(name)
        if delta is not None and abs(delta["delta"]) > report.EPSILON:
            return name, delta
    return None


def _by_size_of_change(
    entries: Sequence[Mapping[str, Any]], metrics: Sequence[str]
) -> list[Mapping[str, Any]]:
    """Biggest deciding change first, then by question ID, so the order never varies."""

    def key(entry: Mapping[str, Any]) -> tuple[float, str]:
        move = _deciding_move(entry, metrics)
        return (-abs(move[1]["delta"]) if move else 0.0, str(entry["id"]))

    return sorted(entries, key=key)


def _change_rows(entries: Sequence[Mapping[str, Any]], metrics: Sequence[str], empty: str) -> str:
    """One collapsed row per changed question; expanding it shows every metric and rank."""
    if not entries:
        return f'<p class="empty">{_e(empty)}</p>'
    rows = []
    for entry in _by_size_of_change(entries, metrics)[:MAX_CHANGED_SHOWN]:
        moves = []
        for name in metrics:
            delta = entry["metrics"].get(name)
            if delta is None:
                continue
            moves.append(
                f"<span>{_e(report._label(name))} {_fmt(delta['baseline'])} → "
                f"<strong>{_fmt(delta['current'])}</strong></span>"
            )
        passage = entry.get("passage", {})
        if passage.get("current", "n/a") != "n/a" or passage.get("baseline", "n/a") != "n/a":
            moves.append(
                f"<span>Answer chunk {_e(passage.get('baseline'))} → "
                f"<strong>{_e(passage.get('current'))}</strong></span>"
            )
        decided = _deciding_move(entry, metrics)
        headline = (
            f"{report._label(decided[0])} {_fmt(decided[1]['baseline'])} → "
            f"{_fmt(decided[1]['current'])}"
            if decided
            else ""
        )
        rows.append(
            '<li><details class="change"><summary>'
            f'<code class="change-id">{_e(entry["id"])}</code>'
            f'<span class="change-query">{_e(entry["query"])}</span>'
            f'<span class="change-move">{_e(headline)}</span></summary>'
            f'<div class="change-body"><p class="change-full">{_e(entry["query"])}</p>'
            f'<div class="moves">{"".join(moves)}</div>{_rank_change(entry)}</div>'
            "</details></li>"
        )
    more = len(entries) - MAX_CHANGED_SHOWN
    tail = f'<p class="empty">And {more} more; see summary.md.</p>' if more > 0 else ""
    return f'<ul class="changes">{"".join(rows)}</ul>{tail}'


def _changed(diff: Mapping[str, Any]) -> str:
    """Regressed and improved questions as two tabs of collapsible rows.

    Without JavaScript the tab bar stays hidden and both panels show, one
    after the other, so nothing is out of reach.
    """
    metrics = diff["compare_metrics"]
    regressed, improved = diff["regressed"], diff["improved"]
    first = "improved" if improved and not regressed else "regressed"
    panels = [
        ("regressed", "▼", "Regressed", regressed, "No question regressed."),
        ("improved", "▲", "Improved", improved, "No question improved."),
    ]
    tabs = "".join(
        f'<button type="button" role="tab" id="tab-{key}" aria-controls="panel-{key}" '
        f'aria-selected="{"true" if key == first else "false"}" '
        f'tabindex="{0 if key == first else -1}">'
        f'<span aria-hidden="true">{icon}</span> {name} ({len(rows)})</button>'
        for key, icon, name, rows, _ in panels
    )
    bodies = "".join(
        f'<div role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}" tabindex="0">'
        f'<h3 class="panel-title"><span aria-hidden="true">{icon}</span> {name} ({len(rows)})</h3>'
        f"{_change_rows(rows, metrics, empty)}</div>"
        for key, icon, name, rows, empty in panels
    )
    return (
        "<section><h2>What changed</h2>"
        f'<p class="lede">Questions are compared on {_e(report._label(metrics[0]))}, then '
        "reciprocal rank, then nDCG; the first that moved decides. Largest changes come "
        "first; open a row for every metric and rank.</p>"
        + change_bar(len(regressed), diff["unchanged"], len(improved))
        + f'<div class="tabs" role="tablist" aria-label="Changed questions">{tabs}</div>'
        + bodies
        + "</section>"
    )


# Long lists start collapsed; short ones start open so nothing is hidden for no reason.
OPEN_UP_TO = 5


def _collapsible(title: str, count: int, body: str) -> str:
    opened = " open" if count <= OPEN_UP_TO else ""
    return (
        f'<section><details class="fold"{opened}><summary><h2>{_e(title)} ({count})</h2>'
        f"</summary>{body}</details></section>"
    )


def _table(head: Sequence[str], rows: Sequence[Sequence[str]], numeric_from: int = 1) -> str:
    """A plain table; cells are already escaped HTML."""
    head_html = "".join(
        f"<th{' class=num' if i >= numeric_from else ''}>{h}</th>" for i, h in enumerate(head)
    )
    body = "".join(
        "<tr>"
        + "".join(
            f"<td{' class=num' if i >= numeric_from else ''}>{c}</td>" for i, c in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{head_html}</tr></thead><tbody>{body}</tbody></table></div>'


def _missed(results: Mapping[str, Any]) -> str:
    k = results["run"]["primary_k"]
    missed = [q for q in results["queries"] if q["metrics"][f"recall@{k}"] < 1 - report.EPSILON]
    title = f"Questions below full recall@{k}"
    if not missed:
        empty = f'<p class="empty">Every question reached full recall@{k}.</p>'
        return _collapsible(title, 0, empty)
    rows = []
    for q in missed:
        top = ", ".join(item["filename"] for item in q["ranked_files"][:3]) or "none"
        rows.append(
            [
                f"<code>{_e(q['id'])}</code>",
                _e(q["query"]),
                _fmt(q["metrics"][f"recall@{k}"]),
                _e(report._ranks(q["expected_ranks"], report._snippet_missing(q))),
                _e(report._passage(q)),
                _e(top),
            ]
        )
    head = ["ID", "Question", f"recall@{k}", "Expected file ranks", "Answer chunk", "Top files"]
    return _collapsible(title, len(missed), _table(head, rows, numeric_from=2))


def _diagnosis(results: Mapping[str, Any]) -> str:
    """Why questions missed at the top k chunks, and unlabeled files that outrank labels."""
    summary = results.get("diagnosis")
    if not summary:
        return ""
    k = summary["k"]
    overall = summary["overall"]
    metrics_overall = results["metrics"].get("overall", {})
    clean = overall["questions"] - sum(overall[c] for c in diagnose.MISS_CLASSES)
    context = ""
    if f"context_precision@{k}" in metrics_overall:
        context = (
            f" Across all questions, context precision@{k} is "
            f"{_fmt(metrics_overall[f'context_precision@{k}'])} and "
            f"{metrics_overall[f'noise@{k}']:.0%} of the top {k} chunks come from files "
            "nobody expected."
        )
    causes = _table(
        ["Cause", "What it means", "Questions"],
        [
            [_e(diagnose.MISS_LABELS[c]), _e(report._meaning(c, k)), str(overall[c])]
            for c in diagnose.MISS_CLASSES
        ],
        numeric_from=2,
    )
    by_tag = ""
    if summary["by_tag"]:
        by_tag = "<h3>By tag</h3>" + _table(
            ["Tag", "Questions", *(_e(diagnose.MISS_LABELS[c]) for c in diagnose.MISS_CLASSES)],
            [
                [
                    _e(tag),
                    str(counts["questions"]),
                    *(str(counts[c]) for c in diagnose.MISS_CLASSES),
                ]
                for tag, counts in summary["by_tag"].items()
            ],
        )
    flagged = [q for q in results["queries"] if (q.get("diagnosis") or {}).get("class")]
    flagged.sort(key=lambda q: (diagnose.MISS_CLASSES.index(q["diagnosis"]["class"]), q["id"]))
    questions = _collapsible(
        f"Questions with a cause to fix at the top {k} chunks",
        len(flagged),
        _table(
            ["ID", "Question", "Cause", "Where it landed"],
            [
                [
                    f"<code>{_e(q['id'])}</code>",
                    _e(q["query"]),
                    _e(diagnose.MISS_LABELS[q["diagnosis"]["class"]]),
                    _e(report._diagnosis_detail(q)),
                ]
                for q in flagged
            ],
            numeric_from=99,
        )
        if flagged
        else f'<p class="empty">Every question has its expected files and answer chunk in the top {k}.</p>',
    )
    holes = summary["label_holes"]
    hole_body = (
        '<p class="lede">Each is either a confuser the ranking should push down or a relevant '
        "file the question's labels are missing. Check a few before treating them as misses.</p>"
        + _table(
            ["ID", "Unlabeled files (file rank)"],
            [
                [
                    f"<code>{_e(hole['id'])}</code>",
                    _e(", ".join(f"{f['filename']} (#{f['rank']})" for f in hole["files"])),
                ]
                for hole in holes
            ],
            numeric_from=99,
        )
        if holes
        else f'<p class="empty">No unlabeled file outranks every expected file in the top {k}.</p>'
    )
    skipped = (
        f'<p class="summary-note">{summary["skipped"]} questions had no chunk scores and were '
        "skipped.</p>"
        if summary.get("skipped")
        else ""
    )
    return (
        f"<section><h2>Why questions missed</h2>"
        f'<p class="lede">A chat answer is built from the top {k} chunks, so each question is '
        f"checked there: {clean} of {overall['questions']} have every expected file and the "
        f"answer chunk in it.{context}</p>"
        f"{causes}{by_tag}{skipped}</section>"
        + questions
        + _collapsible("Unlabeled files ranked above every expected file", len(holes), hole_body)
    )


def _answers(results: Mapping[str, Any], base: Mapping[str, float], noise: float) -> str:
    rows = [q for q in results["queries"] if "answer" in q]
    if not rows:
        return ""
    overall = results["metrics"].get("overall", {})
    names = ["answer_correct", "answer_grounded", "answer_cited", "answer_has_phrase"]
    judged = sum(1 for q in rows if q["answer"].get("judgement") is not None)
    chat_errors = sum(1 for q in rows if q["answer"].get("chat_error"))
    judge_errors = sum(1 for q in rows if q["answer"].get("judge_error"))
    wrong = [q for q in rows if (q["answer"].get("judgement") or {}).get("correctness") == 0]
    wrong_rows = [
        [
            _e(q["query"]),
            _e(q.get("expected_answer") or "n/a"),
            _e((q["answer"].get("text") or "")[:240]),
            _e(q["answer"]["judgement"]["reason"]),
        ]
        for q in wrong
    ]
    if wrong_rows:
        table = _table(["Question", "Reference", "Answer excerpt", "Judge's reason"], wrong_rows, 9)
    elif judged:
        table = '<p class="empty">No answers judged wrong.</p>'
    else:
        table = (
            '<p class="empty">No answers were judged (the run had no judge, or every '
            "judgement failed), so correctness is not shown.</p>"
        )
    counts = [f"{len(rows)} questions sent to chat", f"{judged} judged by an LLM"]
    if chat_errors:
        counts.append(f"{chat_errors} chat {'error' if chat_errors == 1 else 'errors'}")
    if judge_errors:
        counts.append(f"{judge_errors} judge {'error' if judge_errors == 1 else 'errors'}")
    return (
        "<section><h2>Answer quality</h2>"
        f'<p class="lede">{_e("; ".join(counts))}. Only judged answers count toward '
        "correctness and groundedness. Informational; the recall gate does not use "
        "these scores.</p>"
        + _tiles(names, overall, base, noise)
        + f'<details class="fold sub"{" open" if len(wrong) <= OPEN_UP_TO else ""}>'
        + f"<summary><h3>Answers judged wrong ({len(wrong)})</h3></summary>{table}</details>"
        + "</section>"
    )


def _all_metrics(overall: Mapping[str, float], base: Mapping[str, float], noise: float) -> str:
    rows = []
    for name, value in overall.items():
        before = base.get(name)
        rows.append(
            [
                _e(report._label(name)),
                _fmt(value),
                _fmt(before),
                _delta(value, before, noise) or "n/a",
            ]
        )
    return (
        "<section><details><summary>All metrics as a table</summary>"
        + _table(["Metric", "Current", "Baseline", "Change"], rows)
        + "</details></section>"
    )


def render_html(
    results: Mapping[str, Any],
    diff: Mapping[str, Any] | None = None,
    baseline: Mapping[str, Any] | None = None,
) -> str:
    """The whole report as one HTML document."""
    run = results["run"]
    k = run["primary_k"]
    overall = results["metrics"].get("overall", {})
    by_tag = results["metrics"].get("by_tag", {})
    base_metrics = (baseline or {}).get("metrics", {})
    base = base_metrics.get("overall", {}) if diff is not None else {}
    base_tags = base_metrics.get("by_tag", {}) if diff is not None else {}

    noise = noise_floor(results)
    headline = [f"recall@{k}", "mrr", f"ndcg@{k}", f"passage_hit@{k}", "passage_mrr"]
    k_values = [v for v in run.get("k_values", [k]) if f"recall@{v}" in overall]
    series: list[tuple[str, str, Sequence[float | None]]] = []
    if base:
        series.append(("Baseline", "baseline", [base.get(f"recall@{v}") for v in k_values]))
    series.append(("Current run", "current", [overall[f"recall@{v}"] for v in k_values]))
    recall_chart = column_chart(
        "Recall at each cutoff",
        [f"top {v}" for v in k_values],
        series,
        x_label="Results looked at (k)",
        y_label="Recall (share of expected files found)",
    )
    tag_rows = [
        (
            tag,
            int(scores["count"]),
            scores[f"recall@{k}"],
            base_tags.get(tag, {}).get(f"recall@{k}"),
        )
        for tag, scores in by_tag.items()
        if f"recall@{k}" in scores
    ]
    tags = tag_chart(
        f"recall@{k} by tag",
        tag_rows,
        x_label=f"recall@{k} (share of expected files in the top {k}); questions per tag in gray",
    )

    label = f" · {_e(run['label'])}" if run.get("label") else ""
    title = "Retrieval evaluation" + (" compared with baseline" if diff is not None else "")
    body = (
        f"<header><h1>{title}</h1>"
        f'<p class="lede">Run <code>{_e(run["run_id"])}</code>{label}'
        + (
            f" against baseline <code>{_e(diff['baseline_run_id'])}</code>"
            if diff is not None
            else ""
        )
        + f"</p>{_meta(results)}</header>"
        + _callouts(diff)
        + _summary(results, diff)
        + "<section><h2>Headline</h2>"
        + _tiles(headline, overall, base, noise)
        + "</section>"
        + f'<section class="charts">{recall_chart}{tags if tag_rows else ""}</section>'
        + (_changed(diff) if diff is not None else "")
        + _diagnosis(results)
        + _missed(results)
        + _answers(results, base, noise)
        + _all_metrics(overall, base, noise)
        + "<footer>Generated by <code>run_eval.py</code>. The same numbers are in summary.md "
        "and results.json.</footer>"
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Retrieval eval {_e(run['run_id'])}</title><style>{_CSS}</style></head>"
        f'<body><main class="viz-root">{body}</main>'
        f'<div id="tip" role="tooltip" hidden></div><script>{_JS}</script></body></html>\n'
    )


# Follows OpenRAG's IBM theme (frontend/app/globals.css, [data-theme="ibm"]),
# which is built on Carbon: IBM Plex, Gray 10/100 layers, Blue 60, square corners.
# Chart series use Carbon's data-viz categorical order: baseline Purple, current Cyan.
_CSS = """
:root{color-scheme:light;--page:#ffffff;--layer:#f4f4f4;--layer-accent:#e0e0e0;
--ink:#161616;--ink-2:#525252;--muted:#6f6f6f;--grid:#e0e0e0;--axis:#8d8d8d;
--border:#c6c6c6;--focus:#0f62fe;--link:#0f62fe;--current:#1192e8;--baseline:#6929c4;
--good:#24a148;--good-text:#198038;--bad:#da1e28;--bad-text:#da1e28;--same:#c6c6c6;
--tip-bg:#393939;--tip-ink:#f4f4f4;
--warning:#f1c21b;--warning-bg:#fcf4d6;--warning-glyph:#161616;
--info:#0043ce;--info-bg:#edf5ff;--info-glyph:#ffffff}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;
--page:#161616;--layer:#262626;--layer-accent:#393939;--ink:#f4f4f4;--ink-2:#c6c6c6;
--muted:#a8a8a8;--grid:#393939;--axis:#6f6f6f;--border:#393939;--focus:#ffffff;
--link:#78a9ff;--current:#1192e8;--baseline:#8a3ffc;--good:#42be65;--good-text:#42be65;--bad:#fa4d56;
--bad-text:#ff8389;--same:#525252;--tip-bg:#f4f4f4;--tip-ink:#161616;
--warning-bg:#262626;--info:#4589ff;--info-bg:#262626;--info-glyph:#161616}}
:root[data-theme="dark"]{color-scheme:dark;--page:#161616;--layer:#262626;
--layer-accent:#393939;--ink:#f4f4f4;--ink-2:#c6c6c6;--muted:#a8a8a8;--grid:#393939;
--axis:#6f6f6f;--border:#393939;--focus:#ffffff;--link:#78a9ff;--current:#1192e8;--baseline:#8a3ffc;
--good:#42be65;--good-text:#42be65;--bad:#fa4d56;--bad-text:#ff8389;--same:#525252;
--tip-bg:#f4f4f4;--tip-ink:#161616;--warning-bg:#262626;--info:#4589ff;--info-bg:#262626;
--info-glyph:#161616}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
font:14px/1.43 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:.16px}
main{max-width:1056px;margin:0 auto;padding:32px 16px 48px}
h1{font-size:28px;line-height:1.29;font-weight:400;margin:0 0 4px}
h2{font-size:20px;line-height:1.4;font-weight:400;margin:0 0 16px}
h3{font-size:14px;font-weight:600;margin:16px 0 8px}
code{font:12px/1.33 "IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.32px}
.lede{color:var(--ink-2);margin:0 0 16px}
header,section{padding:24px 0;border-bottom:1px solid var(--border)}
header{padding-top:0}
.run-details summary{color:var(--ink-2);cursor:pointer}
.run-details .meta{margin-top:12px}
.meta{display:grid;grid-template-columns:max-content 1fr;gap:4px 24px;margin:0}
.meta dt{color:var(--muted)}.meta dd{margin:0;overflow-wrap:anywhere}
.notifications{display:grid;gap:8px;padding-top:16px}
.notification{display:flex;align-items:flex-start;gap:16px;min-height:48px;padding:14px 16px 14px 13px;
border-left:3px solid;color:var(--ink)}
.notification.warning{border-color:var(--warning);background:var(--warning-bg)}
.notification.info{border-color:var(--info);background:var(--info-bg)}
.notification .notification-icon{flex:none;width:16px;height:16px;margin-top:2px}
.notification.warning .disc{fill:var(--warning)}.notification.warning .glyph{fill:var(--warning-glyph)}
.notification.info .disc{fill:var(--info)}.notification.info .glyph{fill:var(--info-glyph)}
.notification-text{margin:0}.notification-title{font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:2px}
.tile{background:var(--layer);padding:16px;min-height:120px}
.tile-label{color:var(--ink-2)}
.tile-value{font-size:32px;line-height:1.25;font-weight:300;margin:4px 0}
.was{color:var(--muted);font-size:12px}
.delta{font-size:14px;font-weight:600}.delta.good{color:var(--good-text)}
.delta.bad{color:var(--bad-text)}.delta.same{color:var(--muted);font-weight:400}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:32px}
.chart{margin:0;background:var(--layer);padding:16px}
figcaption{font-weight:600;margin-bottom:8px}
svg{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--grid);stroke-width:1}.grid.base{stroke:var(--axis)}
.tick,.count{fill:var(--muted);font-size:12px}.label{fill:var(--ink);font-size:13px}
.value{fill:var(--ink-2);font-size:12px;font-variant-numeric:tabular-nums}
.current{fill:var(--current)}.baseline{fill:var(--baseline)}
.baseline-halo{stroke:var(--layer);stroke-width:7}
.baseline-tick{stroke:var(--baseline);stroke-width:3;stroke-linecap:square}
.hit{fill:transparent}.mark{outline:none;cursor:default}
.mark:hover path,.mark:focus path,.mark:hover .seg,.mark:focus .seg{opacity:.8}
.mark:focus-visible .hit{stroke:var(--focus);stroke-width:2}
.seg.good{fill:var(--good)}.seg.bad{fill:var(--bad)}.seg.same{fill:var(--same)}
.inside{font-size:12px;font-weight:600;fill:#fff}.inside.same{fill:var(--ink)}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;list-style:none;margin:0 0 8px;padding:0;
font-size:12px;color:var(--ink-2)}
.legend li{display:flex;align-items:center;gap:6px}
.swatch{width:12px;height:12px;display:inline-block}
.swatch.current{background:var(--current)}.swatch.baseline{background:var(--baseline)}
.swatch.baseline-key{background:var(--baseline);width:4px}
.swatch.seg.good{background:var(--good)}.swatch.seg.bad{background:var(--bad)}
.swatch.seg.same{background:var(--same)}
.tabs{display:none;gap:0;border-bottom:1px solid var(--border);margin:16px 0 0}
.js .tabs{display:flex}
.tabs [role="tab"]{font:inherit;color:var(--ink-2);background:none;border:0;
border-bottom:2px solid transparent;margin-bottom:-1px;padding:10px 16px;cursor:pointer}
.tabs [role="tab"][aria-selected="true"]{color:var(--ink);font-weight:600;
border-bottom-color:var(--current)}
.tabs [role="tab"]:hover{color:var(--ink)}
.tabs [role="tab"]:focus-visible,[role="tabpanel"]:focus-visible{outline:2px solid var(--focus);
outline-offset:-2px}
[role="tabpanel"]{padding-top:8px}
.js .panel-title{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.changes{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.change summary{display:grid;grid-template-columns:16px max-content minmax(0,1fr) max-content;
gap:12px;align-items:center;padding:10px 16px;background:var(--layer);cursor:pointer;
list-style:none;font-weight:400}
.change summary::-webkit-details-marker{display:none}
.change summary::before{content:"";width:6px;height:6px;border-right:1.5px solid var(--ink-2);
border-bottom:1.5px solid var(--ink-2);transform:rotate(-45deg);justify-self:center;
transition:transform .15s}
.change[open] summary::before{transform:rotate(45deg)}
.change summary:hover{background:var(--layer-accent)}
.change-query{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.change-move{color:var(--ink-2);font-size:12px;font-variant-numeric:tabular-nums}
.change-body{background:var(--layer);padding:0 16px 12px 44px}
.change-full{margin:0 0 6px}
@media (max-width:640px){.change summary{grid-template-columns:16px 1fr}
.change-query,.change-move{grid-column:2}}
.fold>summary{list-style:none;display:flex;align-items:center;gap:8px}
.fold>summary::-webkit-details-marker{display:none}
.fold>summary h2,.fold>summary h3{margin:0}
.fold>summary::before{content:"";width:7px;height:7px;border-right:1.5px solid var(--ink-2);
border-bottom:1.5px solid var(--ink-2);transform:rotate(-45deg);transition:transform .15s}
.fold[open]>summary::before{transform:rotate(45deg)}
.fold[open]>summary{margin-bottom:12px}
.fold.sub{margin-top:16px}
.moves{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--ink-2)}
.ranks{margin:6px 0 0;padding-left:18px;font-size:12px;color:var(--ink-2)}
.empty{color:var(--muted);margin:0}
.table-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:8px 16px;border-bottom:1px solid var(--grid);vertical-align:top}
th{background:var(--layer-accent);font-weight:600}
td{background:var(--layer)}
.num{text-align:right;font-variant-numeric:tabular-nums}
details summary{cursor:pointer;font-weight:600}
summary:focus-visible,.mark:focus-visible{outline:2px solid var(--focus);outline-offset:-2px}
footer{color:var(--muted);font-size:12px;padding-top:24px}
.summary .verdict{font-size:20px;line-height:1.4;margin:0 0 8px}
/* The summary keeps changes bold but uncolored; direction is in the words and signs. */
.tone{font-weight:600;color:var(--ink)}
.points{margin:0;padding-left:20px;color:var(--ink-2)}.points li{margin:2px 0}
.summary-note{color:var(--muted);font-size:12px;margin:8px 0 0}
.axis-title{fill:var(--ink-2);font-size:12px}
#tip{position:fixed;pointer-events:none;background:var(--tip-bg);color:var(--tip-ink);
border-radius:2px;padding:8px 16px;font-size:14px;white-space:pre-line;z-index:10}
#tip::first-line{font-weight:600}
"""

# Tooltip text comes from data-tip and is set with textContent, never as HTML.
_JS = """
document.documentElement.classList.add("js");
document.querySelectorAll('[role="tablist"]').forEach((list) => {
  const tabs = [...list.querySelectorAll('[role="tab"]')];
  const select = (tab) => {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => select(tab));
    tab.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      const next = tabs[(i + step + tabs.length) % tabs.length];
      select(next);
      next.focus();
    });
  });
  select(tabs.find((t) => t.getAttribute("aria-selected") === "true") || tabs[0]);
});
(() => {
  const tip = document.getElementById("tip");
  const place = (x, y) => {
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 12)) + "px";
    tip.style.top = Math.max(8, y - h - 12) + "px";
  };
  const show = (el, x, y) => { tip.textContent = el.dataset.tip; tip.hidden = false; place(x, y); };
  const hide = () => { tip.hidden = true; };
  document.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("pointermove", (e) => show(el, e.clientX, e.clientY));
    el.addEventListener("pointerleave", hide);
    el.addEventListener("focus", () => {
      const r = el.getBoundingClientRect();
      show(el, r.left + r.width / 2, r.top);
    });
    el.addEventListener("blur", hide);
  });
})();
"""
