"""Trusted Vega-Lite templates for Explore charts (PRD section 7, decision-log entry 59).

A plan never carries a specification: the executor fills one of these
templates with the computed bars, so the chart's data is inline, its value
axis starts at zero, every bar is labelled at its tip and its description is
the chart's accessible name. The templates write no expressions, transforms,
parameters or data URLs, and `assert_trusted` refuses a specification that
holds one; the frontend's chart module (`frontend/src/charts`) checks again
before drawing. Colours and sizes match that module's own templates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"

# The PRD section 6 palette, as frontend/src/charts/templates.ts declares it.
INK = "#1f2328"
MUTED = "#5f6b73"
ACCENT = "#0f7b7b"
OTHER = "#7d8a91"
FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
BAR_STEP = 30
BAR_THICKNESS = 18
COLUMN_STEP = 84

# Keys a trusted specification never holds: data URLs, expressions, filters, parameters and transforms.
FORBIDDEN_KEYS = frozenset({"url", "expr", "calculate", "signal", "test", "filter", "params", "transform"})


@dataclass(frozen=True)
class Template:
    id: str
    label: str
    orientation: str


TEMPLATES: dict[str, Template] = {
    "bar_horizontal": Template("bar_horizontal", "Horizontal bars", "horizontal"),
    "bar_vertical": Template("bar_vertical", "Vertical bars", "vertical"),
}


@dataclass(frozen=True)
class Bar:
    """One drawn bar: a stable id, its label, a non-negative value and whether it is the Other bar."""

    id: str
    label: str
    value: float | int
    tip: str
    other: bool = False


def bar_chart(template_id: str, description: str, category_title: str, value_title: str, bars: list[Bar]) -> dict[str, Any]:
    """A bar specification from the named template, in the bars' order, with a zero baseline."""
    template = TEMPLATES[template_id]
    values = []
    for bar in bars:
        if bar.value < 0:
            raise ValueError(f"bar {bar.id!r} needs a non-negative value")
        values.append({"key": bar.id, "label": bar.label, "value": bar.value, "tone": "other" if bar.other else "base", "tip": bar.tip})
    largest = max([1, *(bar.value for bar in bars)])
    # Room past the longest bar for its label; the baseline is always zero.
    scale = {"zero": True, "nice": False, "domainMin": 0, "domainMax": largest * 1.3}
    category = {
        "field": "label",
        "type": "nominal",
        "sort": None,
        "title": None,
        "axis": {"ticks": False, "domain": False, "labelColor": INK, "labelFontSize": 13, "labelPadding": 8,
                 "labelLimit": 160},
    }
    value = {"field": "value", "type": "quantitative", "scale": scale, "axis": None, "title": value_title}
    colour = {
        "field": "tone",
        "type": "nominal",
        "scale": {"domain": ["base", "other"], "range": [ACCENT, OTHER]},
        "legend": None,
    }
    tooltip = [
        {"field": "label", "type": "nominal", "title": category_title},
        {"field": "value", "type": "quantitative", "title": value_title, "format": ","},
    ]
    if template.orientation == "horizontal":
        position = {"y": category, "x": value}
        baseline = {"x": {"datum": 0, "type": "quantitative", "scale": scale, "axis": None}}
        text_mark = {"type": "text", "align": "left", "baseline": "middle", "dx": 6}
        sizing = {"width": "container", "height": {"step": BAR_STEP}}
        bar_mark = {"type": "bar", "size": BAR_THICKNESS, "cornerRadiusEnd": 4}
    else:
        # Short category names read level; longer ones slant rather than overlap.
        angle = 0 if all(len(bar.label) <= 10 for bar in bars) else -30
        category = {**category, "axis": {**category["axis"], "labelAngle": angle, "labelLimit": 140}}
        position = {"x": category, "y": value}
        baseline = {"y": {"datum": 0, "type": "quantitative", "scale": scale, "axis": None}}
        text_mark = {"type": "text", "align": "center", "baseline": "bottom", "dy": -4}
        sizing = {"width": {"step": COLUMN_STEP}, "height": 240}
        bar_mark = {"type": "bar", "size": BAR_THICKNESS * 2, "cornerRadiusEnd": 4}
    spec = {
        "$schema": VEGA_LITE_SCHEMA,
        "usermeta": {"template": template.id},
        "description": description,
        **sizing,
        "background": "transparent",
        "data": {"values": values},
        "layer": [
            {"mark": {"type": "rule", "color": MUTED, "strokeWidth": 1, "aria": False}, "encoding": baseline},
            {"mark": bar_mark, "encoding": {**position, "color": colour, "tooltip": tooltip}},
            {
                "mark": {**text_mark, "fontSize": 13, "color": INK, "aria": False},
                "encoding": {**position, "text": {"field": "tip", "type": "nominal"}},
            },
        ],
        "config": {"font": FONT, "view": {"stroke": None}, "axis": {"labelFont": FONT, "titleFont": FONT}},
    }
    assert_trusted(spec)
    return spec


def assert_trusted(spec: Any, path: str = "spec") -> None:
    """Refuse a specification naming a data URL, an expression, a filter, a parameter or a transform."""
    if isinstance(spec, list):
        for index, item in enumerate(spec):
            assert_trusted(item, f"{path}[{index}]")
        return
    if not isinstance(spec, dict):
        return
    for key, value in spec.items():
        # Row values are data, never read as specification.
        if key == "values" and path.endswith(".data"):
            continue
        if key in FORBIDDEN_KEYS:
            raise ValueError(f"untrusted chart specification: {path}.{key} is not allowed")
        assert_trusted(value, f"{path}.{key}")
