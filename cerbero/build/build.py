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

from cerbero.config import Platform, Architecture, Distro
from cerbero.utils import shell, add_system_libs
from cerbero.utils import messages as m
from cerbero.errors import FatalError
import shutil
import re


class Build (object):
    '''
    Base class for build handlers

    @ivar recipe: the parent recipe
    @type recipe: L{cerbero.recipe.Recipe}
    @ivar config: cerbero's configuration
    @type config: L{cerbero.config.Config}
    '''

    can_use_msvc_toolchain = False
    _properties_keys = []

    def configure(self):
        '''
        Configures the module
        '''
        raise NotImplemented("'configure' must be implemented by subclasses")

    def compile(self):
        '''
        Compiles the module
        '''
        raise NotImplemented("'make' must be implemented by subclasses")

    def install(self):
        '''
        Installs the module
        '''
        raise NotImplemented("'install' must be implemented by subclasses")

    def check(self):
        '''
        Runs any checks on the module
        '''
        pass


class CustomBuild(Build):

    def configure(self):
        pass

    def compile(self):
        pass

    def install(self):
        pass


def write_meson_cross_file(tpl, config, cross_file):
    contents = tpl.format(system=config.target_platform,
                          cpu=config.target_arch,
                          # Assume all ARM sub-archs are in little endian mode
                          endian='little',
                          # If the variable is not set, we assume we want MSVC
                          CC=os.environ.get('CC', 'cl.exe'),
                          CXX=os.environ.get('CXX', 'cl.exe'),
                          AR=os.environ.get('AR', 'lib.exe'),
                          # strip is not used on MSVC
                          STRIP=os.environ.get('STRIP', ''))
    with open(cross_file, 'w') as f:
        f.write(contents)

def modify_environment(func):
    ''' Decorator to modify the build environment '''
    def call(*args):
        self = args[0]
        append_env = self.append_env
        new_env = self.new_env.copy()
        if self.use_system_libs and self.config.allow_system_libs:
            self._add_system_libs(new_env)
        # If this recipe can be built with MSVC and we want it to be
        if self.can_use_msvc_toolchain and self.config.variants.visualstudio:
            # Unset variables pointing to the MinGW/GCC toolchain so that
            # the MSVC toolchain is auto-detected instead.
            if os.environ.has_key('CERBERO_MSVC_UNSET_VARS'):
                for var in os.environ['CERBERO_MSVC_UNSET_VARS'].split():
                    new_env[var] = None
        old_env = self._modify_env(append_env, new_env)
        res = func(*args)
        self._restore_env(old_env)
        return res

    call.func_name = func.func_name
    return call


class MakefilesBase (Build):
    '''
    Base class for makefiles build systems like autotools and cmake
    '''

    config_sh = ''
    configure_tpl = ''
    configure_options = ''
    make = 'make'
    make_install = 'make install'
    make_check = None
    make_clean = 'make clean'
    use_system_libs = False
    allow_parallel_build = True
    autodetect_jobs = True
    srcdir = '.'
    append_env = None
    new_env = None
    requires_non_src_build = False

    def __init__(self):
        Build.__init__(self)
        if self.append_env is None:
            self.append_env = {}
        if self.new_env is None:
            self.new_env = {}
        self.config_src_dir = os.path.abspath(os.path.join(self.build_dir,
                                                           self.srcdir))
        if self.requires_non_src_build:
            self.make_dir = os.path.join (self.config_src_dir, "cerbero-build-dir")
        else:
            self.make_dir = self.config_src_dir
        if self.config.allow_parallel_build and self.allow_parallel_build:
            if self.config.num_of_cpus > 1 and self.autodetect_jobs:
                self.make += ' -j%d' % self.config.num_of_cpus
        elif not self.allow_parallel_build:
            # Set it explicitly because ninja's default is a parallel build,
            # but ignore the global default because that's only for make.
            self.make += ' -j1'
        self._old_env = None

    @modify_environment
    def configure(self):
        if not os.path.exists(self.make_dir):
            os.makedirs(self.make_dir)
        if self.requires_non_src_build:
            self.config_sh = os.path.join('../', self.config_sh)

        shell.call(self.configure_tpl % {'config-sh': self.config_sh,
            'prefix': self.config.prefix,
            'libdir': self.config.libdir,
            'host': self.config.host,
            'target': self.config.target,
            'build': self.config.build,
            'options': self.configure_options},
            self.make_dir)

    @modify_environment
    def compile(self):
        shell.call(self.make, self.make_dir)

    @modify_environment
    def install(self):
        shell.call(self.make_install, self.make_dir)

    @modify_environment
    def clean(self):
        shell.call(self.make_clean, self.make_dir)

    @modify_environment
    def check(self):
        if self.make_check:
            shell.call(self.make_check, self.build_dir)

    def _modify_env(self, append_env, new_env):
        '''
        Modifies the build environment appending the values in
        append_env or replacing the values in new_env
        '''
        if self._old_env is not None:
            return None

        self._old_env = {}
        for var in append_env.keys() + new_env.keys():
            self._old_env[var] = os.environ.get(var, None)

        for var, val in append_env.iteritems():
            if not os.environ.has_key(var):
                os.environ[var] = val
            else:
                os.environ[var] = '%s %s' % (os.environ[var], val)

        for var, val in new_env.iteritems():
            if val is None:
                if var in os.environ:
                    del os.environ[var]
            else:
                os.environ[var] = val
        return self._old_env

    def _restore_env(self, old_env):
        ''' Restores the old environment '''
        if old_env is None:
            return

        for var, val in old_env.iteritems():
            if val is None:
                if var in os.environ:
                    del os.environ[var]
            else:
                os.environ[var] = val
        self._old_env = None

    def _add_system_libs(self, new_env):
        '''
        Add /usr/lib/pkgconfig to PKG_CONFIG_PATH so the system's .pc file
        can be found.
        '''
        add_system_libs(self.config, new_env)


class Autotools (MakefilesBase):
    '''
    Build handler for autotools project
    '''

    autoreconf = False
    autoreconf_sh = 'autoreconf -f -i'
    config_sh = './configure'
    configure_tpl = "%(config-sh)s --prefix %(prefix)s "\
                    "--libdir %(libdir)s %(options)s"
    make_check = 'make check'
    add_host_build_target = True
    can_use_configure_cache = True
    supports_cache_variables = True
    disable_introspection = False

    def configure(self):
        # Only use --disable-maintainer mode for real autotools based projects
        if os.path.exists(os.path.join(self.config_src_dir, 'configure.in')) or\
                os.path.exists(os.path.join(self.config_src_dir, 'configure.ac')):
            self.configure_tpl += " --disable-maintainer-mode "
            self.configure_tpl += " --disable-silent-rules "

        if self.config.variants.gi and not self.disable_introspection:
            self.configure_tpl += " --enable-introspection "
        else:
            self.configure_tpl += " --disable-introspection "

        if self.autoreconf:
            shell.call(self.autoreconf_sh, self.config_src_dir)

        files = shell.check_call('find %s -type f -name config.guess' %
                                 self.config_src_dir).split('\n')
        files.remove('')
        for f in files:
            o = os.path.join(self.config._relative_path('data'), 'autotools',
                             'config.guess')
            m.action("copying %s to %s" % (o, f))
            shutil.copy(o, f)

        files = shell.check_call('find %s -type f -name config.sub' %
                                 self.config_src_dir).split('\n')
        files.remove('')
        for f in files:
            o = os.path.join(self.config._relative_path('data'), 'autotools',
                             'config.sub')
            m.action("copying %s to %s" % (o, f))
            shutil.copy(o, f)

        if self.config.platform == Platform.WINDOWS and \
                self.supports_cache_variables:
            # On windows, environment variables are upperscase, but we still
            # need to pass things like am_cv_python_platform in lowercase for
            # configure and autogen.sh
            for k, v in os.environ.iteritems():
                if k[2:6] == '_cv_':
                    self.configure_tpl += ' %s="%s"' % (k, v)

        if self.add_host_build_target:
            if self.config.host is not None:
                self.configure_tpl += ' --host=%(host)s'
            if self.config.build is not None:
                self.configure_tpl += ' --build=%(build)s'
            if self.config.target is not None:
                self.configure_tpl += ' --target=%(target)s'

        use_configure_cache = self.config.use_configure_cache
        if self.use_system_libs and self.config.allow_system_libs:
            use_configure_cache = False

        if self.new_env or self.append_env:
            use_configure_cache = False

        if use_configure_cache and self.can_use_configure_cache:
            cache = os.path.join(self.config.sources, '.configure.cache')
            self.configure_tpl += ' --cache-file=%s' % cache

        MakefilesBase.configure(self)


class CMake (MakefilesBase):
    '''
    Build handler for cmake projects
    '''

    config_sh = 'cmake'
    configure_tpl = '%(config-sh)s -DCMAKE_INSTALL_PREFIX=%(prefix)s '\
                    '-DCMAKE_LIBRARY_OUTPUT_PATH=%(libdir)s %(options)s '\
                    '-DCMAKE_BUILD_TYPE=Release '\
                    '-DCMAKE_FIND_ROOT_PATH=$CERBERO_PREFIX '

    @modify_environment
    def configure(self):
        cc = os.environ.get('CC', 'gcc')
        cxx = os.environ.get('CXX', 'g++')
        cflags = os.environ.get('CFLAGS', '')
        cxxflags = os.environ.get('CXXFLAGS', '')
        # FIXME: CMake doesn't support passing "ccache $CC"
        if self.config.use_ccache:
            cc = cc.replace('ccache', '').strip()
            cxx = cxx.replace('ccache', '').strip()
        cc = cc.split(' ')[0]
        cxx = cxx.split(' ')[0]

        if self.config.target_platform == Platform.WINDOWS:
            self.configure_options += ' -DCMAKE_SYSTEM_NAME=Windows '
        elif self.config.target_platform == Platform.ANDROID:
            self.configure_options += ' -DCMAKE_SYSTEM_NAME=Linux '
        if self.config.platform == Platform.WINDOWS:
            self.configure_options += ' -G\\"Unix Makefiles\\"'

        # FIXME: Maybe export the sysroot properly instead of doing regexp magic
        if self.config.target_platform in [Platform.DARWIN, Platform.IOS]:
            r = re.compile(r".*-isysroot ([^ ]+) .*")
            sysroot = r.match(cflags).group(1)
            self.configure_options += ' -DCMAKE_OSX_SYSROOT=%s' % sysroot

        self.configure_options += ' -DCMAKE_C_COMPILER=%s ' % cc
        self.configure_options += ' -DCMAKE_CXX_COMPILER=%s ' % cxx
        self.configure_options += ' -DCMAKE_C_FLAGS="%s"' % cflags
        self.configure_options += ' -DCMAKE_CXX_FLAGS="%s"' % cxxflags
        self.configure_options += ' -DLIB_SUFFIX=%s ' % self.config.lib_suffix
        cmake_cache = os.path.join(self.build_dir, 'CMakeCache.txt')
        cmake_files = os.path.join(self.build_dir, 'CMakeFiles')
        if os.path.exists(cmake_cache):
            os.remove(cmake_cache)
        if os.path.exists(cmake_files):
            shutil.rmtree(cmake_files)
        MakefilesBase.configure(self)


# Keep [binaries] as the last section
MESON_CROSS_FILE_TPL = \
'''
[host_machine]
system = '{system}'
cpu_family = '{cpu}'
cpu = '{cpu}'
endian = '{endian}'

[properties]

[binaries]
c = '{CC}'
cpp = '{CXX}'
ar = '{AR}'
strip = '{STRIP}'
pkgconfig = 'pkg-config'
'''

# We derive from MakefilesBase even though we don't use make
# because we use the same overall structure
class Meson (MakefilesBase):
    '''
    Base class for the Meson build system
    http://mesonbuild.com

    '''
    configure_tpl = '%(config-sh)s --prefix=%(prefix)s --libdir=%(libdir)s \
            --default-library=%(default-library)s --buildtype=%(buildtype)s \
            --backend=%(backend)s ..'
    make = None
    make_install = None
    make_check = None
    make_clean = None
    autodetect_jobs = False
    default_library = 'shared'
    meson_backend = 'ninja'
    requires_non_src_build = True
    can_use_msvc_toolchain = True

    def __init__(self):
        super(Meson, self).__init__()

    def find_build_tools(self):
        '''
        We can't do this in __init__ because that is called from the user's
        shell environment, not our Cerbero environment which contains the
        build-tools prefix where meson and ninja-build might be installed.

        We also need to do this for every step because when Cerbero continues
        a build it does not go through the previous steps.
        '''
        # Find Meson
        if not self.config_sh:
            self.config_sh = shell.which('meson') or None
        # Find ninja
        if not self.make:
            self.make = shell.which('ninja-build') or shell.which('ninja') or None
            self.make += ' -v'
        if not self.make_install:
            self.make_install = self.make + ' install'
        if not self.make_check:
            self.make_check = self.make + ' test'
        if not self.make_clean:
            self.make_clean = self.make + ' clean'

    @modify_environment
    def configure(self):
        self.find_build_tools()
        if not self.config_sh:
            raise Exception("The 'meson' build system was not found")

        if os.path.exists(self.make_dir):
            # Only remove if it's not empty
            if os.listdir(self.make_dir):
                shutil.rmtree(self.make_dir)
                os.makedirs(self.make_dir)
        else:
            os.makedirs(self.make_dir)

        if self.config.variants.debug:
            buildtype = 'debug'
        elif self.config.variants.nodebug:
            buildtype = 'release'
        else:
            buildtype = 'debugoptimized'
        prefix = self.config.prefix
        libdir = 'lib' + self.config.lib_suffix
        options = {'config-sh': self.config_sh,
                   'prefix': prefix,
                   'libdir': libdir,
                   'default-library': self.default_library,
                   'buildtype': buildtype,
                   'backend': self.meson_backend,}
        shell_cmd = self.configure_tpl % options
        if self.config.target_arch != self.config.arch or \
           self.config.target_platform != self.config.platform:
            cross_file = os.path.join(self.make_dir, 'meson-cross-file.txt')
            write_meson_cross_file(MESON_CROSS_FILE_TPL, self.config, cross_file)
            shell_cmd += ' --cross-file=' + cross_file
        # With LD_LIBRARY_PATH, Meson and Ninja pick up the Cerbero libraries
        # which can sometimes cause a segfault at weird times
        shell.call(shell_cmd, self.make_dir, unset_env=['LD_LIBRARY_PATH'])

    @modify_environment
    def compile(self):
        self.find_build_tools()
        if not self.make:
            raise Exception("The 'ninja' build system was not found")
        shell.call(self.make, self.make_dir, unset_env=['LD_LIBRARY_PATH'])

    @modify_environment
    def install(self):
        self.find_build_tools()
        if not self.make_install:
            raise Exception("The 'ninja' build system was not found")
        shell.call(self.make_install, self.make_dir, unset_env=['LD_LIBRARY_PATH'])

    @modify_environment
    def clean(self):
        self.find_build_tools()
        shell.call(self.make_clean, self.make_dir, unset_env=['LD_LIBRARY_PATH'])

    @modify_environment
    def check(self):
        self.find_build_tools()
        shell.call(self.make_check, self.make_dir, unset_env=['LD_LIBRARY_PATH'])


class BuildType (object):

    CUSTOM = CustomBuild
    MAKEFILE = MakefilesBase
    AUTOTOOLS = Autotools
    CMAKE = CMake
    MESON = Meson
