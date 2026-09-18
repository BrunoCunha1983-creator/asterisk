#!/usr/bin/env python3
from urllib.parse import urlparse

from ari_runtime import ARI
from ari_ui import augment_index as augment_ari_index


def install(app):
    """Install ARI diagnostics over the already assembled server_entry module."""
    app.server.INDEX = augment_ari_index(app.server.INDEX)

    base_handler = app.H

    class ManagementHandler(base_handler):
        def do_GET(self):
            path = urlparse(self.path).path.rstrip('/') or '/'
            if path == '/api/ari-status':
                if not self._guard_web():
                    return
                try:
                    out = ARI.status()
                    http_runtime = app.server.ast('http show status')
                    ari_runtime = app.server.ast('ari show status')
                    ari_users = app.server.ast('ari show users')
                    out['http_runtime'] = http_runtime.get('output', '')
                    out['ari_runtime'] = ari_runtime.get('output', '')
                    out['ari_users'] = ari_users.get('output', '')
                    module_reports = []
                    for module_name in (
                        'res_websocket_client.so',
                        'res_http_websocket.so',
                        'res_stasis.so',
                        'res_ari.so',
                        'res_ari_asterisk.so',
                    ):
                        result = app.server.ast(f'module show like {module_name}')
                        module_reports.append(
                            f'$ module show like {module_name}\n{result.get("output", "")}'.rstrip()
                        )
                    out['ari_modules'] = '\n\n'.join(module_reports)
                    self.sendj(out)
                except Exception as exc:
                    self.sendj({'connected': False, 'error': str(exc), 'password_exposed': False}, 500)
                return
            super().do_GET()

    app.H = ManagementHandler
