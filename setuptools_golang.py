from __future__ import annotations

import argparse
import contextlib
import copy
import errno
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from types import TracebackType
from typing import Any
from typing import Callable
from typing import Generator
from typing import Sequence

from distutils.ccompiler import CCompiler
from distutils.dist import Distribution
from setuptools import Extension
from setuptools.command.build_ext import build_ext as _build_ext


def rmtree(path: str) -> None:
    """Newer golang uses readonly dirs & files for module cache."""
    def handle_remove_readonly(
            func: Callable[..., Any],
            path: str,
            exc: tuple[type[OSError], OSError, TracebackType],
    ) -> None:
        excvalue = exc[1]
        if (
                func in (os.rmdir, os.remove, os.unlink) and
                excvalue.errno == errno.EACCES
        ):
            for p in (path, os.path.dirname(path)):
                os.chmod(p, os.stat(p).st_mode | stat.S_IWUSR)
            func(path)
        else:
            raise
    shutil.rmtree(path, ignore_errors=False, onerror=handle_remove_readonly)


@contextlib.contextmanager
def _tmpdir() -> Generator[str, None, None]:
    tempdir = tempfile.mkdtemp()
    try:
        yield tempdir
    finally:
        rmtree(tempdir)


def _get_cflags(
        compiler: CCompiler,
        macros: Sequence[tuple[str, str | None]],
) -> str:
    args = [f'-I{p}' for p in compiler.include_dirs]
    for macro_name, macro_value in macros:
        if macro_value is None:
            args.append(f'-D{macro_name}')
        else:
            args.append(f'-D{macro_name}={macro_value}')
    return ' '.join(args)


LFLAG_CLANG = '-Wl,-undefined,dynamic_lookup'
LFLAG_GCC = '-Wl,--unresolved-symbols=ignore-all'
LFLAGS = (LFLAG_CLANG, LFLAG_GCC)


def _get_ldflags() -> str:
    """Determine the correct link flags.  This attempts compiles similar
    to how autotools does feature detection.
    """
    # windows gcc does not support linking with unresolved symbols
    if sys.platform == 'win32':  # pragma: win32 cover
        libs = os.path.join(sys.base_prefix, 'libs')
        return f'-L{libs} -lpython{sys.version_info[0]}'
    else:  # pragma: win32 no cover
        cc = subprocess.check_output(('go', 'env', 'CC')).decode().strip()

        with _tmpdir() as tmpdir:
            testf = os.path.join(tmpdir, 'test.c')
            with open(testf, 'w') as f:
                f.write('int f(int); int main(void) { return f(0); }\n')

            for lflag in LFLAGS:  # pragma: no cover (platform specific)
                try:
                    subprocess.check_call((cc, testf, lflag), cwd=tmpdir)
                    return lflag
                except subprocess.CalledProcessError:
                    pass
            else:  # pragma: no cover (platform specific)
                # wellp, none of them worked, fall back to gcc and they'll get
                # a hopefully reasonable error message
                return LFLAG_GCC


def _check_call(cmd: tuple[str, ...], cwd: str, env: dict[str, str]) -> None:
    envparts = [f'{k}={shlex.quote(v)}' for k, v in sorted(tuple(env.items()))]
    print(f'$ {" ".join(envparts)} {shlex.join(cmd)}', file=sys.stderr)
    subprocess.check_call(cmd, cwd=cwd, env=dict(os.environ, **env))


def _get_build_extension_method(
        base: type[_build_ext],
        root: str,
        strip: bool,
) -> Callable[[_build_ext, Extension], None]:
    def build_extension(self: _build_ext, ext: Extension) -> None:
        # If there are no .go files then the parent should handle this
        if not any(source.endswith('.go') for source in ext.sources):
            # the base class may mutate `self.compiler`
            compiler = copy.deepcopy(self.compiler)
            self.compiler, compiler = compiler, self.compiler
            try:
                return base.build_extension(self, ext)
            finally:
                self.compiler, compiler = compiler, self.compiler

        if len(ext.sources) != 1:
            raise OSError(
                f'Error building extension `{ext.name}`: '
                f'sources must be a single file in the `main` package.\n'
                f'Received: {ext.sources!r}',
            )

        main_file, = ext.sources
        if not os.path.exists(main_file):
            raise OSError(
                f'Error building extension `{ext.name}`: '
                f'{main_file} does not exist',
            )
        main_dir = os.path.dirname(main_file)

        # Copy the package into a temporary GOPATH environment
        with _tmpdir() as tempdir:
            root_path = os.path.join(tempdir, 'src', root)
            # Make everything but the last directory (copytree interface)
            os.makedirs(os.path.dirname(root_path))
            shutil.copytree('.', root_path, symlinks=True)
            pkg_path = os.path.join(root_path, main_dir)

            gopath = os.environ.get('SETUPTOOLS_GOLANG_GOPATH', tempdir)
            env = {'GOPATH': gopath}
            cmd_get = ('go', 'get', '-d')
            _check_call(cmd_get, cwd=pkg_path, env=env)

            env.update({
                'CGO_CFLAGS': _get_cflags(
                    self.compiler, ext.define_macros or (),
                ),
                'CGO_LDFLAGS': _get_ldflags(),
            })

            cmd_build: tuple[str, ...] = (
                'go', 'build', '-buildmode=c-shared',
                '-o', os.path.abspath(self.get_ext_fullpath(ext.name)),
            )
            # "-s" omits the symbol table and debug information
            # "-w" omits DWARF debugging information
            if strip:
                cmd_build = (*cmd_build, '-ldflags=-s -w')

            _check_call(cmd_build, cwd=pkg_path, env=env)

    return build_extension


def _get_build_ext_cls(
        base: type[_build_ext],
        root: str,
        strip: bool = True,
) -> type[_build_ext]:
    attrs = {'build_extension': _get_build_extension_method(base, root, strip)}
    return type('build_ext', (base,), attrs)


def set_build_ext(
        dist: Distribution,
        attr: str,
        value: dict[str, Any],
) -> None:
    base = dist.cmdclass.get('build_ext', _build_ext)
    dist.cmdclass['build_ext'] = _get_build_ext_cls(base, **value)


GOLANG = 'https://storage.googleapis.com/golang/go{}.linux-amd64.tar.gz'
SCRIPT = '''\
cd /tmp
curl {golang} --silent --location | tar -xz
export PATH="/tmp/go/bin:$PATH" HOME=/tmp
for py in {pythons}; do
    "/opt/python/$py/bin/pip" wheel --no-deps --wheel-dir /tmp /dist/*.tar.gz
done
ls *.whl | xargs -n1 --verbose auditwheel repair --wheel-dir /dist
ls -al /dist
'''


def build_manylinux_wheels(
        argv: Sequence[str] | None = None,
) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--golang', default='1.17.1',
        help='Override golang version (default %(default)s)',
    )
    parser.add_argument(
        '--pythons', default='cp37-cp37m',
        help='Override pythons to build (default %(default)s)',
    )
    args = parser.parse_args(argv)

    golang = GOLANG.format(args.golang)
    pythons = ' '.join(args.pythons.split(','))

    assert os.path.exists('setup.py')
    if os.path.exists('dist'):
        shutil.rmtree('dist')
    os.makedirs('dist')
    _check_call(('python', 'setup.py', 'sdist'), cwd='.', env={})
    _check_call(
        (
            'docker', 'run', '--rm',
            '--volume', f'{os.path.abspath("dist")}:/dist:rw',
            '--user', f'{os.getuid()}:{os.getgid()}',
            'quay.io/pypa/manylinux1_x86_64:latest',
            'bash', '-o', 'pipefail', '-euxc',
            SCRIPT.format(golang=golang, pythons=pythons),
        ),
        cwd='.', env={},
    )
    print('*' * 79)
    print('Your wheels have been built into ./dist')
    print('*' * 79)
    return 0
