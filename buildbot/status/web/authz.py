from buildbot.status.web.auth import IAuth

# Programming against Authz
#
# There are two times to check authorization in a web app:
#  1. do I advertise the activity (show the form, link, etc.)
#  2. is this request authorized?
#
# The first is accomplished via advertiseAction.  In general, this
# is used in a Jinja template:
#
#   {{ if authz.advertiseAction('myNewTrick') }}
#     <form action="{{ myNewTrick_url }}"> ...
#
# this requires that the template's context include 'authz'.  This
# object is available from any HtmlResource subclass as
#
#   cxt['authz'] = self.getAuthz(req)
#
# Actions can optionally require authentication, so use needAuthForm
# to determine whether to require a 'username' and 'passwd' field in
# the generated form.  These fields are usually generated by the auth()
# form:
#
#   {% if authz.needAuthForm('myNewTrick') %}
#     {{ auth() }}
#   {% endif %}
#
# Once the POST request comes in, it's time to check authorization again.
# This usually looks something like
#
#  if not self.getAuthz(req).actionAllowed('myNewTrick', req, someExtraArg):
#      return Redirect("../../authfail") # double-check this path!
#
# the someExtraArg is optional (it's handled with *args, so you can have
# several if you want), and is given to the user's authorization function.
# For example, a build-related action should pass the build status, so that
# the user's authorization function could ensure that devs can only operate
# on their own builds.

class Authz(object):
    """Decide who can do what."""

    knownActions = [
    # If you add a new action here, be sure to also update the documentation
            'gracefulShutdown',
            'forceBuild',
            'forceAllBuilds',
            'pingBuilder',
            'stopBuild',
            'stopAllBuilds',
            'cancelPendingBuild',
    ]

    def __init__(self,
            default_action=False,
            auth=None,
            **kwargs):
        self.auth = auth
        if auth:
            assert IAuth.providedBy(auth)

        self.config = dict( (a, default_action) for a in self.knownActions )
        for act in self.knownActions:
            if act in kwargs:
                self.config[act] = kwargs[act]
                del kwargs[act]

        if kwargs:
            raise ValueError("unknown authorization action(s) " + ", ".join(kwargs.keys()))

    def advertiseAction(self, action):
        """Should the web interface even show the form for ACTION?"""
        if action not in self.knownActions:
            raise KeyError("unknown action")
        cfg = self.config.get(action, False)
        if cfg:
            return True
        return False

    def needAuthForm(self, action):
        """Does this action require an authentication form?"""
        if action not in self.knownActions:
            raise KeyError("unknown action")
        cfg = self.config.get(action, False)
        if cfg == 'auth' or callable(cfg):
            return True
        return False

    def actionAllowed(self, action, request, *args):
        """Is this ACTION allowed, given this http REQUEST?"""
        if action not in self.knownActions:
            raise KeyError("unknown action")
        cfg = self.config.get(action, False)
        if cfg:
            if cfg == 'auth' or callable(cfg):
                if not self.auth:
                    return False
                user = request.args.get("username", ["<unknown>"])[0]
                passwd = request.args.get("passwd", ["<no-password>"])[0]
                if user == "<unknown>" or passwd == "<no-password>":
                    return False
                if self.auth.authenticate(user, passwd):
                    if callable(cfg) and not cfg(user, *args):
                        return False
                    return True
                return False
            else:
                return True # anyone can do this..
