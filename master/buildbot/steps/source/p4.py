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

import re
import xml.dom.minidom
import xml.parsers.expat
import os


from twisted.python import log
from twisted.internet import defer

from buildbot.process import buildstep
from buildbot.steps.source import Source
from zope.interface import implements
from buildbot.interfaces import BuildSlaveTooOldError, IRenderable
from buildbot.process.properties import Interpolate
from buildbot.config import ConfigErrors
from types import StringType


"""
Notes:
    see 
    http://www.perforce.com/perforce/doc.current/manuals/cmdref/o.gopts.html#1040647 
    for getting p4 command to output marshalled python dictionaries as output for commands.
    Perhaps switch to using 'p4 -G' :  From URL above:
    -G Causes all output (and batch input for form commands with -i) to be formatted as marshalled Python dictionary objects. This is most often used when scripting.
    """
    

#class P4(buildbot.steps.slave.CompositeStepMixin,Source):

class P4(Source):
    """Perform Perforce checkout/update operations."""

    name = 'p4'

    renderables = [ 'p4base', 'p4client','p4viewspec', 'p4branch' ]
    possible_modes = ('incremental', 'full')
    
    def __init__(self, mode='incremental',
                 method=None,p4base=None, p4branch=None,
                 p4port=None, p4user=None,
                 p4passwd=None, p4extra_views=[], p4line_end='local',
                 p4viewspec=None,
                 p4client=Interpolate('buildbot_%(prop:slavename)s_%(prop:buildername)s'),
                 p4bin='p4',
                  **kwargs):
        """
        @type  p4base: string
        @param p4base: A view into a perforce depot, typically
                       "//depot/proj/"
                       
        @type  p4branch: string
        @param p4branch: A single string, which is appended to the p4base as follows
                        "<p4base><p4branch>/..." 
                        to form the first line in the viewspec

        @type  p4extra_views: list of tuples
        @param p4extra_views: Extra views to be added to the client that is being used.

        @type  p4viewspec: list of tuples
        @param p4viewspec: This will override any p4branch, p4base, and/or p4extra_views
                           specified.  The viewspec will be an array of tuples as follows
                           [('//depot/main/','')]  yields a viewspec with just
                           //depot/main/... //<p4client>/...

        @type  p4port: string
        @param p4port: Specify the perforce server to connection in the format
                       <host>:<port>. Example "perforce.example.com:1666"

        @type  p4user: string
        @param p4user: The perforce user to run the command as.

        @type  p4passwd: string
        @param p4passwd: The password for the perforce user.

        @type  p4line_end: string
        @param p4line_end: value of the LineEnd client specification property

        @type  p4client: string
        @param p4client: The perforce client to use for this buildslave.
        """

        self.method = method
        self.mode   = mode
        self.p4branch = p4branch
        self.p4bin  = p4bin
        self.p4base = p4base
        self.p4port = p4port
        self.p4user = p4user
        self.p4passwd = p4passwd
        self.p4extra_views = p4extra_views
        self.p4viewspec = p4viewspec
        self.p4line_end = p4line_end
        self.p4client = p4client
        
        # needs fix in Interpolate: __repr__ to handle no args or kwargs.
#        log.msg(format="P4:__init__(): p4client:%(p4client)s",p4client=self.p4client)
#        print "P4:__init__(): p4client:%s"%p4client
        Source.__init__(self, **kwargs)
        
        self.addFactoryArguments(mode = mode,
                                 method = method,
                                 p4bin = p4bin,
                                 p4base = p4base,
                                 defaultBranch = p4branch,
                                 p4branch = p4branch,
                                 p4port = p4port,
                                 p4user = p4user,
                                 p4passwd = p4passwd,
                                 p4extra_views = p4extra_views,
                                 p4viewspec = p4viewspec,
                                 p4line_end = p4line_end,
                                 p4client = p4client,
                                 )
        self.p4client = p4client
        
        errors = []
        if self.mode not in self.possible_modes:
            errors.append("mode %s is not one of %s" % (self.mode, self.possible_modes))

        if not p4viewspec and p4base is None:
            errors.append("You must provide p4base or p4viewspec")
            
        if p4viewspec and (p4base or p4branch or p4extra_views):
            errors.append("Either provide p4viewspec or p4base and p4branch (and optionally p4extra_views")
            
        if p4viewspec and type(p4viewspec) is StringType:
            errors.append("p4viewspec must not be a string, and should be a sequence of 2 element sequences")
            
        if p4base and p4base.endswith('/'):
            errors.append('p4base should not end with a trailing / [p4base = %s]'%p4base)
        
        if p4branch and p4branch.endswith('/'):
            errors.append('p4branch should not end with a trailing / [p4branch = %s]'%p4branch)
            
        if (p4branch or p4extra_views) and not p4base:
            errors.append('If you specify either p4branch or p4extra_views you must also specify p4base')

        if errors:
            raise ConfigErrors(errors)

    def startVC(self, branch, revision, patch):

        log.msg('in startVC')
        self.revision = revision
        self.method = self._getMethod()
        self.stdio_log = self.addLog("stdio")

        d = self.checkP4()
        def checkInstall(p4Installed):
            if not p4Installed:
                raise BuildSlaveTooOldError("p4 is not installed on slave")
            return 0
        d.addCallback(checkInstall)

        if self.mode == 'full':
            d.addCallback(self.full)
        elif self.mode == 'incremental':
            d.addCallback(self.incremental)

        d.addCallback(self.parseGotRevision)
        d.addCallback(self.finish)
        d.addErrback(self.failed)
        return d

    
    @defer.inlineCallbacks
    def full(self, _):
        log.msg("P4:full()..")
        
        # First we need to create the client
        yield self._createClientSpec()

        # Then p4 sync #none
        yield self._dovccmd(['sync','#none'],collectStdout=True)

        # Then remove directory.
        # NOTE: Not using CompositeStepMixin's runRmdir() as it requires self.rc_log
        #       to be defined and ran into issues where setting that in _dovccmd would
        #       yield multiple logs named 'stdio' in the waterfall report..
        yield self._rmdir(self.workdir)

        # Then we need to sync the client
        if self.revision:
            log.msg("P4: full() sync command based on :base:%s changeset:%d",self.p4base,int(self.revision))
            yield self._dovccmd(['sync','%s...@%d'%(self.p4base,int(self.revision))], collectStdout=True)
        else:
            log.msg("P4: full() sync command based on :base:%s no revision",self.p4base)
            yield self._dovccmd(['sync'], collectStdout=True)

        log.msg("P4: full() sync done.")



    @defer.inlineCallbacks
    def incremental(self, _):
        log.msg("P4:incremental()")
        updatable = yield self._sourcedirIsUpdatable()
            
        # First we need to create the client
        yield self._createClientSpec()
        
        # and plan to do a checkout
        command = ['sync',]

        if self.revision:
            command.extend(['%s...@%d'%(self.p4base,int(self.revision))])

        log.msg("P4:incremental() command:%s",command)
        yield self._dovccmd(command)



    def finish(self, res):
        d = defer.succeed(res)
        def _gotResults(results):
            self.setStatus(self.cmd, results)
            return results
        d.addCallback(_gotResults)
        d.addCallbacks(self.finished, self.checkDisconnect)
        return d

    def _buildVCCommand(self,doCommand):
        assert doCommand, "No command specified"

        command = [self.p4bin,]

        if self.p4port:
            command.extend(['-p', self.p4port])
        if self.p4user:
            command.extend(['-u', self.p4user])
        if self.p4passwd:
            # Need to find out if there's a way to obfuscate this
            command.extend(['-P', self.p4passwd]) 
        if self.p4client:
            command.extend(['-c', self.p4client])
            
        command.extend(doCommand)
        
        command = [c.encode('utf-8') for c in command]
        return command


    def _dovccmd(self, command, collectStdout=False,initialStdin=None):

        command = self._buildVCCommand(command)

        log.msg("P4:_dovccmd():workdir->%s"%self.workdir)
        cmd = buildstep.RemoteShellCommand(self.workdir, command,
                                           env=self.env,
                                           logEnviron=self.logEnviron,
                                           collectStdout=collectStdout,
                                           initialStdin=initialStdin,)
        cmd.useLog(self.stdio_log, False)
        log.msg("Starting p4 command : p4 %s" % (" ".join(command), ))

        d = self.runCommand(cmd)
        def evaluateCommand(cmd):
            if cmd.rc != 0:
                log.msg("P4:_dovccmd():Source step failed while running command %s" % cmd)
                raise buildstep.BuildStepFailed()
            if collectStdout:
                return cmd.stdout
            else:
                return cmd.rc
        d.addCallback(lambda _: evaluateCommand(cmd))
        return d

    def _getMethod(self):
        if self.method is not None and self.mode != 'incremental':
            return self.method
        elif self.mode == 'incremental':
            return None
        elif self.method is None and self.mode == 'full':
            return 'fresh'

    def _sourcedirIsUpdatable(self):
        # In general you should always be able to write to the directory
        # You just specified as the root of your client
        # So just return.
        # If we find a case where this is no longer true, then this 
        # needs to be implemented
        # in which case add : @defer.inlineCallbacks decorator above this
        return defer.succeed(True)
    
    @defer.inlineCallbacks
    def _createClientSpec(self):
        builddir=self.getProperty('builddir')
        
        log.msg("P4:_createClientSpec() builddir:%s"%builddir)
        log.msg("P4:_createClientSpec() SELF.workdir:%s"%self.workdir)
        
        prop_dict=self.getProperties().asDict()
        prop_dict['p4client'] = self.p4client
        
        client_spec = ''
        client_spec += "Client: %s\n\n" % self.p4client
        client_spec += "Owner: %s\n\n" % self.p4user
        client_spec += "Description:\n\tCreated by %s\n\n" % self.p4user
        
#        print "builddir:%s"%builddir
#        print "self.workdir:%s"%self.workdir
        
        client_spec += "Root:\t%s\n\n" % os.path.join(builddir,self.workdir)
        client_spec += "Options:\tallwrite rmdir\n\n"
        if self.p4line_end:
            client_spec += "LineEnd:\t%s\n\n" % self.p4line_end
        else:
            client_spec += "LineEnd:\tlocal\n\n"

        # Setup a view
        client_spec += "View:\n"
        
        
        if self.p4viewspec:
            # uses only p4viewspec array of tuples to build view
            # If the user specifies a viewspec via an array of tuples then
            # Ignore any specified p4base,p4branch, and/or p4extra_views
            for k,v in self.p4viewspec:
                log.msg('P4:_createClientSpec():key:%s value:%s'%(k,v))
                client_spec += '\t%s... //%s/%s...\n'%(k,self.p4client,v)
        else:
            # Uses p4base, p4branch, p4extra_views
            client_spec += "\t%s" % (self.p4base)

            if self.p4branch:
                client_spec += "/%s" % (self.p4branch)
            
            client_spec += "/... //%s/...\n" % (self.p4client)
                
            if self.p4extra_views:
                for k, v in self.p4extra_views:
                    client_spec += "\t%s/... //%s/%s/...\n" % (k, self.p4client, v)
                    
        client_spec = client_spec.encode('utf-8') # resolve unicode issues
        log.msg(client_spec)
        
        stdout = yield self._dovccmd(['client','-i'], collectStdout=True, initialStdin=client_spec)
        mo = re.search(r'Client (\S+) (.+)$',stdout,re.M)
        defer.returnValue(mo and (mo.group(2) == 'saved.' or mo.group(2) == 'not changed.'))


#    @defer.inlineCallbacks
    def parseGotRevision(self, _):
        command = self._buildVCCommand(['changes','-m1','#have'])
        
        cmd = buildstep.RemoteShellCommand(self.workdir, command,
                                           env=self.env,
                                           logEnviron=self.logEnviron,
                                           collectStdout=True)
        cmd.useLog(self.stdio_log, False)
        d = self.runCommand(cmd)
        def _setrev(_):
            stdout = cmd.stdout.strip()
            # Example output from p4 changes -m1 #have
            #     Change 212798 on 2012/04/13 by user@user-unix-bldng2 'change to pickup build'
            revision = stdout.split()[1]
            try:
                int(revision)
            except ValueError:
                msg =("p4.parseGotRevision unable to parse output "
                      "of 'p4 changes -m1 \"#have\"': '%s'" % stdout)
                log.msg(msg)
                raise buildstep.BuildStepFailed()

            log.msg("Got p4 revision %s" % (revision, ))
            self.updateSourceProperty('got_revision', revision)
            return 0
        d.addCallback(lambda _: _setrev(cmd.rc))
        return d

    def purge(self, ignore_ignores):
        """Delete everything that shown up on status."""
        command = ['sync', '#none']
        if ignore_ignores:
            command.append('--no-ignore')
        d = self._dovccmd(command, collectStdout=True)
        
        # add deferred to rm tree
        
        # then add defer to sync to revision
        return d


    def checkP4(self):
        cmd = buildstep.RemoteShellCommand(self.workdir, ['p4', '-V'],
                                           env=self.env,
                                           logEnviron=self.logEnviron)
        cmd.useLog(self.stdio_log, False)
        d = self.runCommand(cmd)
        def evaluate(cmd):
            if cmd.rc != 0:
                return False
            return True
        d.addCallback(lambda _: evaluate(cmd))
        return d

    def computeSourceRevision(self, changes):
        if not changes or None in [c.revision for c in changes]:
            return None
        lastChange = max([int(c.revision) for c in changes])
        return lastChange
    
    @defer.inlineCallbacks
    def _rmdir(self, dir):
        cmd = buildstep.RemoteCommand('rmdir',
                {'dir': dir, 'logEnviron': self.logEnviron })
        cmd.useLog(self.stdio_log, False)
        yield self.runCommand(cmd)
        if cmd.rc != 0:
            raise buildstep.BuildStepFailed()
