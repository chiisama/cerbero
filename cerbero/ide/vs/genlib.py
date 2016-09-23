# cerbero - a multi-platform build system for Open Source software
# Copyright (C) 2012 Andoni Morales Alastruey <ylatuya@gmail.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Library General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Library General Public License for more details.
#
# You should have received a copy of the GNU Library General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

import os
import re

from cerbero.config import Architecture
from cerbero.utils import shell, to_unixpath


class GenLib(object):
    '''
    Generates an import library that can be used in Visual Studio from a DLL,
    using 'gendef' to create a .def file and then libtool to create the import
    library (.lib)
    '''

    DLLTOOL_TPL = '$DLLTOOL -d %s -l %s -D %s'
    LIB_TPL = '%s /DEF:%s /OUT:%s /MACHINE:%s'

    def create(self, libname, dllpath, arch, outputdir):
        bindir, dllname = os.path.split(dllpath)

        # Create the .def file
        shell.call('gendef %s' % dllpath, outputdir)

        defname = dllname.replace('.dll', '.def')
        if libname.startswith('lib'):
            implib = libname[3:] + '.lib'
        else:
            implib = libname + '.lib'

        # Create the import library
        vc_path = self._get_vc_tools_path()

        # Prefer LIB.exe over dlltool:
        # http://sourceware.org/bugzilla/show_bug.cgi?id=12633
        if vc_path is not None:
            # Spaces msys and shell are a beautiful combination
            lib_path = to_unixpath(os.path.join(vc_path, 'lib.exe'))
            lib_path = lib_path.replace('\\', '/')
            lib_path = lib_path.replace('(', '\\\(').replace(')', '\\\)')
            lib_path = lib_path.replace(' ', '\\\\ ')
            if arch == Architecture.X86:
                arch = 'x86'
            else:
                arch = 'x64'
            shell.call(self.LIB_TPL % (lib_path, defname, implib, arch), outputdir)
        else:
            shell.call(self.DLLTOOL_TPL % (defname, implib, dllname), outputdir)
        return os.path.join(outputdir, implib)

    def _get_vc_tools_path(self):
        if 'VS100COMNTOOLS' in os.environ:
            path = os.path.join(os.environ['VS100COMNTOOLS'], '..', '..',
                'VC', 'bin', 'amd64')
            if os.path.exists (path):
                return path
        return None

class GenGnuLib(GenLib):
    '''
    Generates an import library (libfoo.dll.a; not foo.lib) that is in a format
    that allows GNU ld to resolve all symbols exported by a DLL created by MSVC.

    Usually everything works fine even if you pass a .lib import library created
    by MSVC to GNU GCC/LD, but it can't find any exported DATA (variable)
    symbols from the import library, but it can find them if you pass it the DLL
    directly. Since that's a terrible idea and breaks how library searching
    works, we create a GNU-compatible import library which works.
    '''

    def create(self, dllpath, arch, outputdir):
        dllname = os.path.basename(dllpath)
        # Create the .def file
        shell.call('gendef ' + dllpath, outputdir)
        defname = dllname.replace('.dll', '.def')
        # foo.dll, libfoo.dll, libfoo-x.dll, foo-x.dll all need libfoo.dll.a
        libname = re.match(r'(lib)?(.*?)(-[0-9]+)?\.dll', dllname).groups()[1]
        gnuimplib = 'lib{0}.dll.a'.format(libname)
        shell.call(self.DLLTOOL_TPL % (defname, gnuimplib, dllname), outputdir)
        return os.path.join(outputdir, gnuimplib)
