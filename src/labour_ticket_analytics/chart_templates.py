"""Trusted Vega-Lite templates for Explore charts (PRD section 7, decision-log entries 59, 77 and 79).

A plan never carries a specification: the executor fills one of these
templates with the computed values, so the chart's data is inline, its value
axis starts at zero, every bar is labelled at its tip and its description is
the chart's accessible name. Bars draw categories, a single total or ordered
periods; a line draws ordered periods only; a histogram draws equal-width
bins the service counted; a scatterplot draws one point per Ticket; a table
draws no graphic. The templates write no expressions, transforms,
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


# What a chart can draw (decision-log entry 79): categories or one total, ordered periods, a distribution
# of per-ticket values, or a pair of per-ticket values.
FORMS = ("total", "categories", "dates", "distribution", "pair")


@dataclass(frozen=True)
class Template:
    id: str
    label: str
    # The plan forms the template draws; a table draws every form as rows and no graphic.
    forms: tuple[str, ...]
    orientation: str | None = None

    @property
    def draws(self) -> bool:
        return self.id != "table"


TEMPLATES: dict[str, Template] = {
    "bar_horizontal": Template("bar_horizontal", "Horizontal bars", ("total", "categories", "dates"), "horizontal"),
    "bar_vertical": Template("bar_vertical", "Vertical bars", ("total", "categories", "dates"), "vertical"),
    # Lines join points in date order only, never unordered categories (PRD section 7).
    "line": Template("line", "Line over time", ("dates",)),
    "histogram": Template("histogram", "Histogram", ("distribution",)),
    "scatter": Template("scatter", "Scatterplot", ("pair",)),
    "table": Template("table", "Table only", FORMS),
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


@dataclass(frozen=True)
class Point:
    """One point of a line: a period's id, its full label, a short axis label and a non-negative value."""

    id: str
    label: str
    tick: str
    value: float | int
    tip: str


def line_chart(description: str, category_title: str, value_title: str, points: list[Point]) -> dict[str, Any]:
    """A line through the periods in the order given (date order, every period present), with a zero baseline.

    The x axis is ordinal over the server's filled periods, so equal steps are
    equal spans of time and nothing is parsed from a date string in the browser.
    """
    values = []
    for point in points:
        if point.value < 0:
            raise ValueError(f"point {point.id!r} needs a non-negative value")
        values.append({"key": point.id, "label": point.label, "tick": point.tick, "value": point.value, "tip": point.tip})
    largest = max([1, *(point.value for point in points)])
    scale = {"zero": True, "nice": True, "domainMin": 0, "domainMax": largest * 1.15}
    x = {
        "field": "tick", "type": "ordinal", "sort": None, "title": category_title,
        "axis": {"labelColor": INK, "labelFontSize": 12, "labelAngle": 0 if len(points) <= 12 else -45, "titleColor": MUTED},
    }
    y = {
        "field": "value", "type": "quantitative", "scale": scale, "title": value_title,
        "axis": {"labelColor": INK, "titleColor": MUTED, "gridColor": "#e7e4de", "tickCount": 5},
    }
    tooltip = [
        {"field": "label", "type": "nominal", "title": category_title},
        {"field": "value", "type": "quantitative", "title": value_title, "format": ","},
    ]
    spec = {
        "$schema": VEGA_LITE_SCHEMA,
        "usermeta": {"template": "line"},
        "description": description,
        "width": "container",
        "height": 260,
        "background": "transparent",
        "data": {"values": values},
        "layer": [
            {"mark": {"type": "line", "color": ACCENT, "strokeWidth": 2, "aria": False}, "encoding": {"x": x, "y": y}},
            {
                "mark": {"type": "point", "filled": True, "size": 60, "color": ACCENT},
                "encoding": {"x": x, "y": y, "tooltip": tooltip},
            },
            {
                "mark": {"type": "text", "dy": -10, "fontSize": 12, "color": INK, "aria": False},
                "encoding": {"x": x, "y": y, "text": {"field": "tip", "type": "nominal"}},
            },
        ],
        "config": {"font": FONT, "view": {"stroke": None}, "axis": {"labelFont": FONT, "titleFont": FONT}},
    }
    assert_trusted(spec)
    return spec


@dataclass(frozen=True)
class Bin:
    """One histogram bin: its id and label, the half-open value range [start, end) and the tickets in it."""

    id: str
    label: str
    start: float | int
    end: float | int
    value: int


def histogram(description: str, axis_title: str, bins: list[Bin]) -> dict[str, Any]:
    """Adjacent bars over equal-width bins already counted by the service, with a zero baseline."""
    values = [
        {"key": item.id, "label": item.label, "start": item.start, "end": item.end, "value": item.value}
        for item in bins
    ]
    largest = max([1, *(item.value for item in bins)])
    scale = {"zero": True, "nice": True, "domainMin": 0, "domainMax": largest * 1.1}
    x = {
        "field": "start", "type": "quantitative", "bin": "binned", "title": axis_title,
        "scale": {"zero": False, "nice": False},
        "axis": {"labelColor": INK, "titleColor": MUTED, "tickCount": 12, "labelOverlap": True},
    }
    y = {
        "field": "value", "type": "quantitative", "scale": scale, "title": "Tickets",
        "axis": {"labelColor": INK, "titleColor": MUTED, "gridColor": "#e7e4de", "tickCount": 5},
    }
    tooltip = [
        {"field": "label", "type": "nominal", "title": axis_title},
        {"field": "value", "type": "quantitative", "title": "Tickets", "format": ","},
    ]
    spec = {
        "$schema": VEGA_LITE_SCHEMA,
        "usermeta": {"template": "histogram"},
        "description": description,
        "width": "container",
        "height": 260,
        "background": "transparent",
        "data": {"values": values},
        "mark": {"type": "bar", "color": ACCENT, "stroke": "#ffffff", "strokeWidth": 1},
        "encoding": {"x": x, "x2": {"field": "end"}, "y": y, "tooltip": tooltip},
        "config": {"font": FONT, "view": {"stroke": None}, "axis": {"labelFont": FONT, "titleFont": FONT}},
    }
    assert_trusted(spec)
    return spec


@dataclass(frozen=True)
class Dot:
    """One scatterplot point: a Ticket's id, its label and its two values."""

    id: str
    label: str
    x: float | int
    y: float | int


def scatter(description: str, x_title: str, y_title: str, dots: list[Dot]) -> dict[str, Any]:
    """One point per Ticket, both axes from zero; points are translucent so stacked tickets read as darker."""
    values = [{"key": dot.id, "label": dot.label, "x": dot.x, "y": dot.y} for dot in dots]
    axis = {"labelColor": INK, "titleColor": MUTED, "gridColor": "#e7e4de", "tickCount": 6}
    spec = {
        "$schema": VEGA_LITE_SCHEMA,
        "usermeta": {"template": "scatter"},
        "description": description,
        "width": "container",
        "height": 320,
        "background": "transparent",
        "data": {"values": values},
        "mark": {"type": "point", "filled": True, "size": 36, "opacity": 0.45, "color": ACCENT},
        "encoding": {
            "x": {"field": "x", "type": "quantitative", "title": x_title, "scale": {"zero": True}, "axis": axis},
            "y": {"field": "y", "type": "quantitative", "title": y_title, "scale": {"zero": True}, "axis": axis},
            "tooltip": [
                {"field": "label", "type": "nominal", "title": "Ticket"},
                {"field": "x", "type": "quantitative", "title": x_title, "format": ","},
                {"field": "y", "type": "quantitative", "title": y_title, "format": ",.2f"},
            ],
        },
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
