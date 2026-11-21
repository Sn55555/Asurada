"""Load the packaged offline dashboard, preserving standalone HTML output."""
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_dashboard_template() -> str:
    root = Path(__file__).with_name('dashboard_templates')
    return (root.joinpath('dashboard.html').read_text(encoding='utf-8')
            .replace('__DASHBOARD_STYLE__', root.joinpath('dashboard.css').read_text(encoding='utf-8'))
            .replace('__DASHBOARD_SCRIPT__', root.joinpath('dashboard.js').read_text(encoding='utf-8')))
