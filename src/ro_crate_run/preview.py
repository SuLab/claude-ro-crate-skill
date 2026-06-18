from __future__ import annotations

import html
from pathlib import Path
from string import Template

from .materialize.run_model import build_run_model
from .state import load_state

_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "templates" / "preview.html.j2"


def render(state_dir: Path) -> str:
    """Render an HTML preview of the run state using string.Template substitution."""
    state = load_state(state_dir)
    model = build_run_model(state_dir, state.sequence)
    command_rows = "".join(
        "<tr><td>{cmd}</td><td>{status}</td></tr>".format(
            cmd=html.escape(c.display_command or "command"),
            status=html.escape(c.terminal_status or "started"),
        )
        for c in model.commands
    ) or "<tr><td colspan='2'>No commands recorded</td></tr>"
    output_items = "".join(
        "<li>{p}</li>".format(p=html.escape(str(o.get("path", "")))) for o in model.outputs
    ) or "<li>No declared outputs</li>"
    template = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.substitute(
        title=html.escape(model.title),
        profile=html.escape(model.selected_profile),
        run_id=html.escape(model.run_id),
        command_rows=command_rows,
        output_items=output_items,
    )


def render_preview_html(summary: dict[str, object]) -> str:
    """Backwards-compatible shim for callers passing a summary dict."""
    title = html.escape(str(summary.get("title", "RO-Crate Run")))
    return (
        f"<!doctype html><html><head><title>{title}</title></head>"
        f"<body><h1>RO-Crate Run Preview</h1><h2>{title}</h2></body></html>"
    )
