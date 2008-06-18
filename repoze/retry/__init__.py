# repoze retry-on-conflict-error behavior
import itertools
import os
import traceback
from tempfile import TemporaryFile

try:
    from ZODB.POSException import ConflictError
except ImportError:
    class ConflictError(Exception):
        pass

class Retry:
    def __init__(self, application, tries, retryable=None):
        """ WSGI Middlware which retries a configurable set of exception types.

        o 'application' is the RHS in the WSGI "pipeline".

        o 'retries' is the maximun number of times to retry a request.

        o 'retryable' is a sequence of one or more exception types which,
          if raised, indicate that the request should be retried.
        """
        self.application = application
        self.tries = tries

        if retryable is None:
            retryable = ConflictError

        if not isinstance(retryable, (list, tuple)):
            retryable = [retryable]

        self.retryable = tuple(retryable)

    def __call__(self, environ, start_response):
        catch_response = []
        written = []
        original_wsgi_input = environ.get('wsgi.input')
        new_wsgi_input = None

        if original_wsgi_input is not None:
            cl = environ.get('CONTENT_LENGTH', '0')
            cl = int(cl)
            new_wsgi_input = environ['wsgi.input'] = TemporaryFile('w+b')
            rest = cl
            chunksize = 1<<20
            while rest:
                if rest <= chunksize:
                    chunk = original_wsgi_input.read(rest)
                    rest = 0
                else:
                    chunk = original_wsgi_input.read(chunksize)
                    rest = rest - chunksize
                new_wsgi_input.write(chunk)
            new_wsgi_input.seek(0)

        def replace_start_response(status, headers, exc_info=None):
            catch_response[:] = [status, headers, exc_info]
            return written.append

        i = 0
        while 1:
            try:
                app_iter = self.application(environ, replace_start_response)
            except self.retryable, e:
                i += 1
                if environ.get('wsgi.errors'):
                    errors = environ['wsgi.errors']
                    errors.write('repoze.retry retrying, count = %s\n' % i)
                    traceback.print_exc(environ['wsgi.errors'])
                if i < self.tries:
                    if new_wsgi_input is not None:
                        new_wsgi_input.seek(0)
                    continue
                if catch_response:
                    start_response(*catch_response)
                raise
            else:
                if catch_response:
                    start_response(*catch_response)
                return itertools.chain(written, app_iter)

def make_retry(app, global_conf, **local_conf):
    from pkg_resources import EntryPoint
    tries = int(local_conf.get('tries', 3))
    retryable = local_conf.get('retryable')
    if retryable is not None:
        retryable = [EntryPoint.parse('x=%s' % x).load(False)
                      for x in retryable.split(' ')]
    return Retry(app, tries, retryable=retryable)
