# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright 2011, Louis Opter <kalessin@kalessin.fr>

# Quite inspired from the github hook.

import hmac
import logging
import sys
import traceback

from twisted.python import log

from buildbot.util import json

class GoogleCodeAuthFailed(Exception):
    pass

class Payload(object):
    def __init__(self, headers, body):
        self._auth_code = headers['Google-Code-Project-Hosting-Hook-Hmac']
        self._body = body # we need to save it if we want to authenticate it

        payload = json.loads(body)
        self.project = payload['project_name']
        self.repository = payload['repository_path']
        self.revisions = payload['revisions']
        self.revision_count = payload['revision_count']

    def authenticate(self, secret_key):
        m = hmac.new(secret_key)
        m.update(self._body)
        digest = m.hexdigest()
        return digest == self._auth_code

    def changes(self):
        changes = []

        for r in self.revisions:
            files = set()
            files.update(r['added'], r['modified'], r['removed'])
            changes.append(dict(
                who=r['author'],
                files=list(files),
                comments=r['message'],
                links=[r['url']],
                revision=r['revision'],
                when=r['timestamp'],
                branch='default', # missing in the body
                revlink=r['url'],
                repository=self.repository,
                project=self.project
            ))

        return changes

def getChanges(request, options=None):
    try:
        headers = request.received_headers
        body = request.content.getvalue()
        #logging.error('headers = {0}, body = {1}'.format(headers, body))
        payload = Payload(headers, body)

        if 'secret_key' in options:
            if not payload.authenticate(options['secret_key']):
                raise GoogleCodeAuthFailed()
        else:
            log.msg('Missing secret_key in the Google Code WebHook options: cannot authenticate the request!')

        log.msg('Received {0} changes from Google Code'.format(payload.revision_count))
        changes = payload.changes()
    except:
        logging.error("Can't parse the Google Code WebHook:")
        for msg in traceback.format_exception(*sys.exc_info()):
            logging.error(msg.strip())
        # return something valid even if everything goes wrong:
        changes = []

    return changes, 'Google Code'
