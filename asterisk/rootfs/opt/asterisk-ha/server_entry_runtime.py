#!/usr/bin/env python3
from http.server import ThreadingHTTPServer

import server_entry as app
from ivr_return import install as install_ivr_return


install_ivr_return(app.server)


if __name__ == '__main__':
    startup = app.server.load_pbx_state()
    app.server.render_managed(startup)
    app.server.render_sipcord(app.server.CONF, startup)
    app.server.render_ivrs(app.server.CONF, startup)
    ThreadingHTTPServer(('0.0.0.0', 8099), app.H).serve_forever()
