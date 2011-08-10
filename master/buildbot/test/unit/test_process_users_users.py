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

import mock
from twisted.trial import unittest

from buildbot.process.users import users
from buildbot.test.fake import fakedb


class UsersTests(unittest.TestCase):

    def setUp(self):
        self.master = mock.Mock()
        self.master.db = self.db = fakedb.FakeDBConnector(self)

    def test_createUserObject_no_src(self):
        d = users.createUserObject(self.master, "Tyler Durden", None)
        def check(_):
            self.assertEqual(self.db.users.users, {})
            self.assertEqual(self.db.users.users_info, {})
        d.addCallback(check)
        return d

    def test_createUserObject_unrecognized_src(self):
        d = users.createUserObject(self.master, "Tyler Durden", 'blah')
        def check(_):
            self.assertEqual(self.db.users.users, {})
            self.assertEqual(self.db.users.users_info, {})
        d.addCallback(check)
        return d

    def test_createUserObject_git(self):
        d = users.createUserObject(self.master,
                                   "Tyler Durden <tyler@mayhem.net>", 'git')
        def check(_):
            self.assertEqual(self.db.users.users,
                     { 1: dict(identifier='Tyler Durden <tyler@mayhem.net>') })
            self.assertEqual(self.db.users.users_info,
                     { 1: dict(attr_type="git",
                               attr_data="Tyler Durden <tyler@mayhem.net>") })
        d.addCallback(check)
        return d

    def test_createUserObject_svn(self):
        d = users.createUserObject(self.master, "tdurden", 'svn')
        def check(_):
            self.assertEqual(self.db.users.users,
                             { 1: dict(identifier='tdurden') })
            self.assertEqual(self.db.users.users_info,
                             { 1: dict(attr_type="svn",
                                       attr_data="tdurden") })
        d.addCallback(check)
        return d

    def test_createUserObject_hg(self):
        d = users.createUserObject(self.master,
                                   "Tyler Durden <tyler@mayhem.net>", 'hg')
        def check(_):
            self.assertEqual(self.db.users.users,
                     { 1: dict(identifier='Tyler Durden <tyler@mayhem.net>') })
            self.assertEqual(self.db.users.users_info,
                     { 1: dict(attr_type="hg",
                               attr_data="Tyler Durden <tyler@mayhem.net>") })
        d.addCallback(check)
        return d

    def test_createUserObject_cvs(self):
        d = users.createUserObject(self.master, "tdurden", 'cvs')
        def check(_):
            self.assertEqual(self.db.users.users,
                             { 1: dict(identifier='tdurden') })
            self.assertEqual(self.db.users.users_info,
                             { 1: dict(attr_type="cvs",
                                       attr_data="tdurden") })
        d.addCallback(check)
        return d

    def test_createUserObject_darcs(self):
        d = users.createUserObject(self.master, "tyler@mayhem.net", 'darcs')
        def check(_):
            self.assertEqual(self.db.users.users,
                     { 1: dict(identifier='tyler@mayhem.net') })
            self.assertEqual(self.db.users.users_info,
                     { 1: dict(attr_type="darcs",
                               attr_data="tyler@mayhem.net") })
        d.addCallback(check)
        return d

    def test_createUserObject_bzr(self):
        d = users.createUserObject(self.master, "Tyler Durden", 'bzr')
        def check(_):
            self.assertEqual(self.db.users.users,
                     { 1: dict(identifier='Tyler Durden') })
            self.assertEqual(self.db.users.users_info,
                     { 1: dict(attr_type="bzr",
                               attr_data="Tyler Durden") })
        d.addCallback(check)
        return d
