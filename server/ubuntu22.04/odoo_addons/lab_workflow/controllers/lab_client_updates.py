"""Only approved immutable client releases; separate from inventory operations."""
import json
from pathlib import Path
from odoo import http, tools
from odoo.http import request
from werkzeug.wrappers import Response
from werkzeug.wsgi import wrap_file
from .lab_api_common import require_lab_access, LabApiError
from ..tools.client_release import ReleaseStore


def store():
    return ReleaseStore(Path(tools.config['data_dir']) / 'lab-client-updates')


class ClientUpdates(http.Controller):
    @http.route('/lab/client/updates/manifest', type='http', auth='none',
                methods=['GET'], csrf=False, save_session=False)
    def manifest(self, platform='', arch='', channel='stable', **kwargs):
        try:
            result = store().manifest(platform, arch, channel)
        except (ValueError, KeyError, OSError):
            return Response(status=404)
        if result is None:
            return Response(status=204)
        return Response(json.dumps(result), content_type='application/json',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @http.route('/lab/client/updates/assets/<string:release_id>/<string:filename>',
                type='http', auth='user', methods=['GET'], csrf=False)
    def artifact(self, release_id, filename, **kwargs):
        try:
            require_lab_access()
        except LabApiError:
            return Response(status=403)
        try:
            path, data = store().asset(release_id, filename)
            stream = path.open('rb')
        except (ValueError, KeyError, OSError):
            return Response(status=404)
        result = Response(wrap_file(request.httprequest.environ, stream),
                          direct_passthrough=True, content_type='application/octet-stream')
        result.content_length = data['size']
        result.headers['Content-Disposition'] = 'attachment; filename="%s"' % filename
        result.headers['Cache-Control'] = 'private, no-store'
        result.headers['X-Content-Type-Options'] = 'nosniff'
        result.set_etag(data['sha256'])
        result.call_on_close(stream.close)
        return result
