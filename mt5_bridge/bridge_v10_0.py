"""Stable launcher with a verified fallback to bundled pure-Python HTTP dependencies."""
from __future__ import annotations
import importlib
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
VENDOR = BASE / '_vendor'
_HTTP_MODULES = ('flask','werkzeug','jinja2','markupsafe','itsdangerous','click','blinker','colorama')

def _clear_http_stack():
    for name in list(sys.modules):
        if any(name == root or name.startswith(root + '.') for root in _HTTP_MODULES):
            sys.modules.pop(name, None)

def _check_http_stack():
    import flask
    import colorama
    if not all(hasattr(flask, name) for name in ('Flask','jsonify','request')):
        raise ImportError('Flask installation is incomplete')
    if not hasattr(colorama, 'AnsiToWin32'):
        raise ImportError('Colorama installation is incomplete: AnsiToWin32 missing')

def _prepare_http_stack():
    try:
        _check_http_stack()
        return
    except Exception as installed_error:
        if not VENDOR.is_dir():
            raise RuntimeError('Cannot load Flask/Colorama and bundled _vendor is missing') from installed_error
    _clear_http_stack()
    vendor = str(VENDOR)
    while vendor in sys.path:
        sys.path.remove(vendor)
    sys.path.insert(0, vendor)
    importlib.invalidate_caches()
    try:
        _check_http_stack()
    except Exception as vendor_error:
        raise RuntimeError('Cannot load bundled Flask/Colorama. Restore the complete R7.1 Bridge package.') from vendor_error

_prepare_http_stack()
from event_core.server import main

if __name__ == '__main__':
    main()
