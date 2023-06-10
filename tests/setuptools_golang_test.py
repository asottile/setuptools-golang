from __future__ import annotations

import collections
import os
import shlex
import subprocess
import sys

import pytest
from setuptools.dist import Distribution

import setuptools_golang


@pytest.fixture(autouse=True, scope='session')
def enable_coverage_subprocesses():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ['COVERAGE_PROCESS_START'] = os.path.join(here, 'setup.cfg')


def auto_namedtuple(**kwargs):
    return collections.namedtuple('auto_namedtuple', kwargs.keys())(**kwargs)


def run(*cmd, **kwargs):
    returncode = kwargs.pop('returncode', 0)
    proc = subprocess.Popen(cmd, **kwargs)
    out, err = proc.communicate()
    out = out.decode('UTF-8').replace('\r', '') if out is not None else None
    err = err.decode('UTF-8').replace('\r', '') if err is not None else None
    if returncode is not None:
        if proc.returncode != returncode:
            raise AssertionError(
                f'{cmd!r} returned {proc.returncode} (expected {returncode})\n'
                f'out:\n{out}\nerr:\n{err}\n',
            )
    return auto_namedtuple(returncode=proc.returncode, out=out, err=err)


def run_output(*cmd, **kwargs):
    return run(*cmd, stdout=subprocess.PIPE, **kwargs).out


def test_sets_cmdclass():
    dist = Distribution()
    assert not dist.cmdclass.get('build_ext')
    setuptools_golang.set_build_ext(
        dist, 'build_golang', {'root': 'github.com/asottile/fake'},
    )
    assert dist.cmdclass['build_ext']


@pytest.fixture(scope='session')
def venv(tmpdir_factory):
    """A shared virtualenv fixture, be careful not to install two of the same
    package into this -- or sadness...
    """
    bin = 'Scripts' if sys.platform == 'win32' else 'bin'
    venv = tmpdir_factory.mktemp('venv').join('venv')
    pip = venv.join(bin, 'pip').strpath
    python = venv.join(bin, 'python').strpath
    # Make sure this virtualenv has the same executable
    run('virtualenv', venv.strpath, '-p', sys.executable)
    # Install this so we can get coverage
    run(pip, 'install', 'covdefaults>=1.2.0', 'coverage-enable-subprocess')
    # Install wheel as well so we can non-pep517
    run(pip, 'install', 'wheel')
    # Install us!
    run(pip, 'install', '-e', '.')
    yield auto_namedtuple(venv=venv, pip=pip, python=python)


SUM = 'import {0}; print({0}.sum(1, 2))'


@pytest.mark.parametrize(
    ('pkg', 'mod'),
    (
        (os.path.join('testing', 'sum'), 'sum'),
        (os.path.join('testing', 'sum_pure_go'), 'sum_pure_go'),
        (os.path.join('testing', 'sum_sub_package'), 'sum_sub_package.sum'),
    ),
)
def test_sum_integration(venv, pkg, mod):
    run(venv.pip, 'install', '-v', pkg)
    out = run_output(venv.python, '-c', SUM.format(mod))
    assert out == '3\n'


HELLO_WORLD = 'import project_with_c; print(project_with_c.hello_world())'


def test_integration_project_with_c(venv):
    test_sum_integration(
        venv,
        os.path.join('testing', 'project_with_c'), 'project_with_c_sum.sum',
    )
    out = run_output(venv.python, '-c', HELLO_WORLD)
    assert out == 'hello world\n'


RED = 'import red; print(red.red(u"ohai"))'


def test_integration_imports_gh(venv):
    run(venv.pip, 'install', os.path.join('testing', 'imports_gh'))
    out = run_output(venv.python, '-c', RED)
    assert out == '\x1b[0;31mohai\x1b[0m\n'


GOMOD = 'import gomodules; gomodules.reversemsg()'


def test_integration_gomodules(venv):
    run(venv.pip, 'install', os.path.join('testing', 'gomodules'))
    out = run_output(venv.python, '-c', GOMOD)
    assert out == 'test example'


def test_integration_notfound(venv):
    ret = run(
        venv.pip, 'install', os.path.join('testing', 'notfound'),
        returncode=None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    assert ret.returncode != 0
    assert (
        'Error building extension `notfound`: notfound.go does not exist' in
        ret.out
    )


def test_integration_multidir(venv):
    ret = run(
        venv.pip, 'install', os.path.join('testing', 'multidir'),
        returncode=None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    assert ret.returncode != 0
    assert (
        'Error building extension `multidir`: '
        'sources must be a single file in the `main` package.' in ret.out
    )


OHAI = 'import hello_lib; print(hello_lib.ohai(u"Anthony"))'


def test_integration_internal_imports(venv):
    run(venv.pip, 'install', os.path.join('testing', 'internal_imports'))
    out = run_output(venv.python, '-c', OHAI)
    assert out == 'ohai, Anthony\n'


def test_integration_user_gopath(venv, tmpdir):
    testdir = os.path.join('testing', 'gomodules')

    gopath = str(tmpdir.join('gopath'))
    env = {**os.environ, 'SETUPTOOLS_GOLANG_GOPATH': gopath}
    ret = run(
        venv.pip, 'install', '-v', testdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert f'$ GOPATH={shlex.quote(gopath)} go get -d' in ret.out


def test_integration_defines(venv):
    run(venv.pip, 'install', os.path.join('testing', 'defines'))
    out = run_output(venv.python, '-c', SUM.format('sum'))
    assert out == '3\n'


def test_regression_dangling_symlink(venv):
    # this raises an error because of a dangling symlink
    run(venv.pip, 'install', os.path.join('testing', 'dangling_symlink'))
