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
# Copyright Buildbot Team Members

import collections
import re
import weakref
from buildbot import util
from buildbot.interfaces import IRenderable, IProperties
from twisted.internet import defer
from twisted.python.components import registerAdapter
from zope.interface import implements

class Properties(util.ComparableMixin):
    """
    I represent a set of properties that can be interpolated into various
    strings in buildsteps.

    @ivar properties: dictionary mapping property values to tuples 
        (value, source), where source is a string identifing the source
        of the property.

    Objects of this class can be read like a dictionary -- in this case,
    only the property value is returned.

    As a special case, a property value of None is returned as an empty 
    string when used as a mapping.
    """

    compare_attrs = ('properties',)
    implements(IProperties)

    def __init__(self, **kwargs):
        """
        @param kwargs: initial property values (for testing)
        """
        self.properties = {}
        # Track keys which are 'runtime', and should not be
        # persisted if a build is rebuilt
        self.runtime = set()
        self.build = None # will be set by the Build when starting
        if kwargs: self.update(kwargs, "TEST")

    def __getstate__(self):
        d = self.__dict__.copy()
        d['build'] = None
        return d

    def __setstate__(self, d):
        self.__dict__ = d
        if not hasattr(self, 'runtime'):
            self.runtime = set()

    def __contains__(self, name):
        return name in self.properties

    def __getitem__(self, name):
        """Just get the value for this property."""
        rv = self.properties[name][0]
        return rv

    def __nonzero__(self):
        return not not self.properties

    def getPropertySource(self, name):
        return self.properties[name][1]

    def asList(self):
        """Return the properties as a sorted list of (name, value, source)"""
        l = [ (k, v[0], v[1]) for k,v in self.properties.iteritems() ]
        l.sort()
        return l

    def asDict(self):
        """Return the properties as a simple key:value dictionary"""
        return dict(self.properties)

    def __repr__(self):
        return ('Properties(**' +
                repr(dict((k,v[0]) for k,v in self.properties.iteritems())) +
                ')')

    def update(self, dict, source, runtime=False):
        """Update this object from a dictionary, with an explicit source specified."""
        for k, v in dict.items():
            self.properties[k] = (v, source)
            if runtime:
                self.runtime.add(k)

    def updateFromProperties(self, other):
        """Update this object based on another object; the other object's """
        self.properties.update(other.properties)
        self.runtime.update(other.runtime)

    def updateFromPropertiesNoRuntime(self, other):
        """Update this object based on another object, but don't
        include properties that were marked as runtime."""
        for k,v in other.properties.iteritems():
            if k not in other.runtime:
                self.properties[k] = v

    # IProperties methods

    def getProperty(self, name, default=None):
        return self.properties.get(name, (default,))[0]

    def hasProperty(self, name):
        return self.properties.has_key(name)

    has_key = hasProperty

    def setProperty(self, name, value, source, runtime=False):
        self.properties[name] = (value, source)
        if runtime:
            self.runtime.add(name)

    def getProperties(self):
        return self

    def getBuild(self):
        return self.build

    def render(self, value):
        renderable = IRenderable(value)
        return defer.maybeDeferred(renderable.getRenderingFor, self)


class PropertiesMixin:
    """
    A mixin to add L{IProperties} methods to a class which does not implement
    the interface, but which can be coerced to the interface via an adapter.

    This is useful because L{IProperties} methods are often called on L{Build}
    and L{BuildStatus} objects without first coercing them.

    @ivar set_runtime_properties: the default value for the C{runtime}
    parameter of L{setProperty}.
    """

    set_runtime_properties = False

    def getProperty(self, propname, default=None):
        props = IProperties(self)
        return props.getProperty(propname, default)

    def hasProperty(self, propname):
        props = IProperties(self)
        return props.hasProperty(propname)

    has_key = hasProperty

    def setProperty(self, propname, value, source='Unknown', runtime=None):
        # source is not optional in IProperties, but is optional here to avoid
        # breaking user-supplied code that fails to specify a source
        props = IProperties(self)
        if runtime is None:
            runtime = self.set_runtime_properties
        props.setProperty(propname, value, source, runtime=runtime)

    def getProperties(self):
        return IProperties(self)

    def render(self, value):
        props = IProperties(self)
        return props.render(value)



class _PropertyMap(object):
    """
    Privately-used mapping object to implement WithProperties' substitutions,
    including the rendering of None as ''.
    """
    colon_minus_re = re.compile(r"(.*):-(.*)")
    colon_tilde_re = re.compile(r"(.*):~(.*)")
    colon_plus_re = re.compile(r"(.*):\+(.*)")
    def __init__(self, properties):
        # use weakref here to avoid a reference loop
        self.properties = weakref.ref(properties)
        self.temp_vals = {}

    def __getitem__(self, key):
        properties = self.properties()
        assert properties is not None

        def colon_minus(mo):
            # %(prop:-repl)s
            # if prop exists, use it; otherwise, use repl
            prop, repl = mo.group(1,2)
            if prop in self.temp_vals:
                return self.temp_vals[prop]
            elif properties.has_key(prop):
                return properties[prop]
            else:
                return repl

        def colon_tilde(mo):
            # %(prop:~repl)s
            # if prop exists and is true (nonempty), use it; otherwise, use repl
            prop, repl = mo.group(1,2)
            if prop in self.temp_vals and self.temp_vals[prop]:
                return self.temp_vals[prop]
            elif properties.has_key(prop) and properties[prop]:
                return properties[prop]
            else:
                return repl

        def colon_plus(mo):
            # %(prop:+repl)s
            # if prop exists, use repl; otherwise, an empty string
            prop, repl = mo.group(1,2)
            if properties.has_key(prop) or prop in self.temp_vals:
                return repl
            else:
                return ''

        for regexp, fn in [
            ( self.colon_minus_re, colon_minus ),
            ( self.colon_tilde_re, colon_tilde ),
            ( self.colon_plus_re, colon_plus ),
            ]:
            mo = regexp.match(key)
            if mo:
                rv = fn(mo)
                break
        else:
            # If explicitly passed as a kwarg, use that,
            # otherwise, use the property value.
            if key in self.temp_vals:
                rv = self.temp_vals[key]
            else:
                rv = properties[key]

        # translate 'None' to an empty string
        if rv is None: rv = ''
        return rv

    def add_temporary_value(self, key, val):
        'Add a temporary value (to support keyword arguments to WithProperties)'
        self.temp_vals[key] = val

class WithProperties(util.ComparableMixin):
    """
    This is a marker class, used fairly widely to indicate that we
    want to interpolate build properties.
    """

    implements(IRenderable)
    compare_attrs = ('fmtstring', 'args')

    def __init__(self, fmtstring, *args, **lambda_subs):
        self.fmtstring = fmtstring
        self.args = args
        if not self.args:
            self.lambda_subs = lambda_subs
            for key, val in self.lambda_subs.iteritems():
                if not callable(val):
                    raise ValueError('Value for lambda substitution "%s" must be callable.' % key)
        elif lambda_subs:
            raise ValueError('WithProperties takes either positional or keyword substitutions, not both.')

    def getRenderingFor(self, build):
        pmap = _PropertyMap(build.getProperties())
        if self.args:
            strings = []
            for name in self.args:
                strings.append(pmap[name])
            s = self.fmtstring % tuple(strings)
        else:
            for k,v in self.lambda_subs.iteritems():
                pmap.add_temporary_value(k, v(build))
            s = self.fmtstring % pmap
        return s



_notHasKey = object() ## Marker object for _Lookup(..., hasKey=...) default
class _Lookup(util.ComparableMixin):
    implements(IRenderable)

    def __init__(self, value, index, default=None,
            defaultWhenFalse=True, hasKey=_notHasKey,
            elideNoneAs=None):
        self.value = value
        self.index = index
        self.default = default
        self.defaultWhenFalse = defaultWhenFalse
        self.hasKey = hasKey
        self.elideNoneAs = elideNoneAs

    @defer.inlineCallbacks
    def getRenderingFor(self, build):
        value = build.render(self.value)
        index = build.render(self.index)
        value, index = yield defer.gatherResults([value, index])
        if not value.has_key(index):
           rv = yield build.render(self.default)
        else:
            if self.defaultWhenFalse:
                rv = yield build.render(value[index])
                if not rv:
                    rv = yield build.render(self.default)
                elif self.hasKey is not _notHasKey:
                    rv = yield build.render(self.hasKey)
            elif self.hasKey is not _notHasKey:
                rv = yield build.render(self.hasKey)
            else:
                rv = yield build.render(value[index])
        if rv is None:
            rv = yield build.render(self.elideNoneAs)
        defer.returnValue(rv)


def _getInterpolationList(fmtstring):
    # TODO: Verify that no positial substitutions are requested
    dd = collections.defaultdict(str)
    fmtstring % dd
    return dd.keys()


class _PropertyDict(object):
    implements(IRenderable)
    def getRenderingFor(self, build):
        return build.getProperties()
_thePropertyDict = _PropertyDict()

class _SourceStampDict(object):
    implements(IRenderable)
    def __init__(self, codebase):
        self.codebase = codebase
    def getRenderingFor(self, build):
        ss = build.getBuild().getSourceStamp(self.codebase)
        if ss:
            return ss.asDict()
        else:
            return {}


class _Lazy(object):
    implements(IRenderable)
    def __init__(self, value):
        self.value = value
    def getRenderingFor(self, build):
        return self.value
 

class Interpolate(util.ComparableMixin): 
    """ 
    This is a marker class, used fairly widely to indicate that we 
    want to interpolate build properties. 
    """ 
 
    implements(IRenderable) 
    compare_attrs = ('fmtstring', 'args', 'kwargs') 
 
    def __init__(self, fmtstring, *args, **kwargs): 
        global config
        from buildbot import config
        self.fmtstring = fmtstring 
        self.args = args
        self.kwargs = kwargs 
        if not self.args:
            self.interpolations = {}
            self._parse(fmtstring)
        if self.args and self.kwargs:
            raise ValueError('Interpolate takes either positional or keyword substitutions, not both.')

    @staticmethod
    def _parse_prop(arg):
        try:
            prop, repl = arg.split(":", 1)
        except ValueError:
            prop, repl = arg, None
        return _thePropertyDict, prop, repl

    @staticmethod
    def _parse_src(arg):
        ## TODO: Handle changes
        try:
            codebase, attr, repl = arg.split(":", 2)
        except ValueError:
            try:
                codebase, attr = arg.split(":",1)
                repl = None
            except ValueError:
                config.error("Must specify both codebase and attribute for src Interpolation '%s'" % arg)
                codebase = attr = repl = None
        return _SourceStampDict(codebase), attr, repl

    def _parse_kw(self, arg):
        try:
            kw, repl = arg.split(":", 1)
        except ValueError:
            kw, repl = arg, None
        return _Lazy(self.kwargs), kw, repl

    def _parseSubstitution(self, fmt):
        try:
            key, arg = fmt.split(":", 1)
        except ValueError:
            config.error("invalid Interpolate substitution without selector '%s'" % fmt)
            return

        fn = getattr(self, "_parse_" + key, None)
        if not fn:
            config.error("invalid Interpolate selector '%s'" % key)
            return None
        else:
            return fn(arg)

    def _parseColon_minus(self, d, kw, repl):
        return _Lookup(d, kw,
               default=Interpolate(repl, **self.kwargs),
               defaultWhenFalse=False,
               elideNoneAs='')

    def _parseColon_tilde(self, d, kw, repl):
        return _Lookup(d, kw,
               default=Interpolate(repl, **self.kwargs),
               defaultWhenFalse=True,
               elideNoneAs='')

    def _parseColon_plus(self, d, kw, repl):
        return _Lookup(d, kw,
               hasKey=Interpolate(repl, **self.kwargs),
               default='',
               defaultWhenFalse=False,
               elideNoneAs='')

    def _parse(self, fmtstring):
        keys = _getInterpolationList(fmtstring)
        for key in keys:
            if not self.interpolations.has_key(key):
                d, kw, repl = self._parseSubstitution(key)
                if repl is None:
                    repl = '-'
                for char, fn in [
                    ( "-", self._parseColon_minus ),
                    ( "~", self._parseColon_tilde ),
                    ( "+", self._parseColon_plus ),
                    ]:
                    if repl[0] == char:
                        self.interpolations[key] = fn(d, kw, repl[1:])
                if not self.interpolations.has_key(key):
                    config.error("invalid Interpolate default type '%s'" % repl[0])

    def getRenderingFor(self, props): 
        props = props.getProperties() 
        if self.args:
            d = props.render(self.args)
            d.addCallback(lambda args:
                self.fmtstring % tuple(args))
            return d
        else:
            d = props.render(self.interpolations)
            d.addCallback(lambda res:
                self.fmtstring % res)
            return d

class Property(util.ComparableMixin):
    """
    An instance of this class renders a property of a build.
    """

    implements(IRenderable)

    compare_attrs = ('key','default', 'defaultWhenFalse')

    def __init__(self, key, default=None, defaultWhenFalse=True):
        """
        @param key: Property to render.
        @param default: Value to use if property isn't set.
        @param defaultWhenFalse: When true (default), use default value
            if property evaluates to False. Otherwise, use default value
            only when property isn't set.
        """
        self.key = key
        self.default = default
        self.defaultWhenFalse = defaultWhenFalse

    def getRenderingFor(self, props):
        if self.defaultWhenFalse:
            d = props.render(props.getProperty(self.key))
            @d.addCallback
            def checkDefault(rv):
                if rv:
                    return rv
                else:
                    return props.render(self.default)
            return d
        else:
            if props.hasProperty(self.key):
                return props.render(props.getProperty(self.key))
            else:
                return props.render(self.default)

class _DefaultRenderer(object):
    """
    Default IRenderable adaptor. Calls .getRenderingFor if availble, otherwise
    returns argument unchanged.
    """

    implements(IRenderable)

    def __init__(self, value):
        try:
            self.renderer = value.getRenderingFor
        except AttributeError:
            self.renderer = lambda _: value

    def getRenderingFor(self, build):
        return self.renderer(build)

registerAdapter(_DefaultRenderer, object, IRenderable)


class _ListRenderer(object):
    """
    List IRenderable adaptor. Maps Build.render over the list.
    """

    implements(IRenderable)

    def __init__(self, value):
        self.value = value

    def getRenderingFor(self, build):
        return defer.gatherResults([ build.render(e) for e in self.value ])

registerAdapter(_ListRenderer, list, IRenderable)


class _TupleRenderer(object):
    """
    Tuple IRenderable adaptor. Maps Build.render over the tuple.
    """

    implements(IRenderable)

    def __init__(self, value):
        self.value = value

    def getRenderingFor(self, build):
        d = defer.gatherResults([ build.render(e) for e in self.value ])
        d.addCallback(tuple)
        return d

registerAdapter(_TupleRenderer, tuple, IRenderable)


class _DictRenderer(object):
    """
    Dict IRenderable adaptor. Maps Build.render over the keya and values in the dict.
    """

    implements(IRenderable)

    def __init__(self, value):
        self.value = _ListRenderer([ _TupleRenderer((k,v)) for k,v in value.iteritems() ])

    def getRenderingFor(self, build):
        d = self.value.getRenderingFor(build)
        d.addCallback(dict)
        return d

registerAdapter(_DictRenderer, dict, IRenderable)
