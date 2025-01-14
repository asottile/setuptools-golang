from __future__ import annotations

from setuptools import Extension
from setuptools import setup


setup(
    name='sum_flag',
    ext_modules=[Extension('sum_flag', ['sum.go'])],
    build_golang={'root': 'github.com/asottile/fake', "extra_cflags":"-O3", "extra_ldflags":"-ldl"},
    # Would do this, but we're testing *our* implementation and this would
    # install from pypi.  We can rely on setuptools-golang being already
    # installed under test.
    # setup_requires=['setuptools-golang'],
)
