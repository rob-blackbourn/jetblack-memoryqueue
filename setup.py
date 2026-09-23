"""Supply the free-threaded ABI macro, including on Windows."""
import sysconfig

from setuptools import setup
from setuptools.command.build_ext import build_ext


class BuildExt(build_ext):
    def build_extensions(self):
        if sysconfig.get_config_var('Py_GIL_DISABLED'):
            for extension in self.extensions:
                extension.define_macros.append(('Py_GIL_DISABLED', '1'))
        super().build_extensions()


setup(cmdclass={'build_ext': BuildExt})
