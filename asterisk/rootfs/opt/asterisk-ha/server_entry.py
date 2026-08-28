#!/usr/bin/env python3
from http.server import ThreadingHTTPServer

import server
from ht503 import augment_index as augment_ht503_index, ensure_ht503_state, validate_ht503_state


# Apply the HT503 UI after the base server has already applied SIPcord + IVR.
server.INDEX = augment_ht503_index(server.INDEX)

_base_normalize_pbx = server.normalize_pbx


def normalize_pbx(data):
    """Extend the existing PBX normalizer with HT503 FXS metadata/validation."""
    data, changed, removed = _base_normalize_pbx(data)
    data, ht_changed = ensure_ht503_state(data)
    validate_ht503_state(data)
    return data, bool(changed or ht_changed), removed


# Functions in server.py resolve globals dynamically, so replacing this module
# attribute also updates load/save requests handled by server.H.
server.normalize_pbx = normalize_pbx


if __name__ == '__main__':
    startup = server.load_pbx_state()
    server.render_managed(startup)
    server.render_sipcord(server.CONF, startup)
    server.render_ivrs(server.CONF, startup)
    ThreadingHTTPServer(('0.0.0.0', 8099), server.H).serve_forever()
