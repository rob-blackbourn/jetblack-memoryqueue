# DEVELOPMENT

To build and install on Ubuntu 26.04 I needed to install `patchelf`
which was required by `auditwheel`.

The `Makefile` automates the process of building and creating the
wheels.

The workflow is as follows.

```bash
# Create a virtual environment for a specific version and activate it.
pyenv local 3.12
python -m venv .venv-3.12
source .venv/bin/activate
# Install the project and the build tools.
python -m pip install --update pip
python -m pip install --editable '.[build]'
# Build the source distribution and wheel
python -m build
# Upload the source distribution.
twine upload dist/*.tar.gz
# Repair the wheel and upload.
auditwheel repair dist/*.whl
twine upload wheelhouse/*.whl
```
