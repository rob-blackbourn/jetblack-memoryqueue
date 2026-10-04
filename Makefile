PYTHON_VERSIONS ?= 3.11-dev 3.12-dev 3.13-dev 3.14-dev 3.14t-dev
VENVS := $(addprefix .venv-,$(PYTHON_VERSIONS))
INSTALL_TARGETS := $(addprefix install-,$(PYTHON_VERSIONS))
BUILD_TARGETS := $(addprefix build-,$(PYTHON_VERSIONS))

.PHONY: install build clean $(INSTALL_TARGETS) $(BUILD_TARGETS)
# Builds and editable installs share generated files in the source tree.
.NOTPARALLEL:

install: $(INSTALL_TARGETS)
	@echo "Install complete."

$(INSTALL_TARGETS): install-%: .venv-%
	@echo "Installing for Python $*..."
	$</bin/python -m pip install -e '.[dev]'

build: $(BUILD_TARGETS)
	auditwheel repair dist/*.whl
	@echo "Build complete."

$(BUILD_TARGETS): build-%: .venv-%
	@echo "Building for Python $*..."
	$</bin/python -m pip install --upgrade build
	$</bin/python -m build

$(VENVS): .venv-%:
	PYENV_VERSION=$* pyenv exec python -m venv $@
	$@/bin/python -m pip install --upgrade pip

clean:
	rm -rf \
		.venv* \
		.mypy_cache \
		.pytest_cache \
		.python-version \
		build \
		dist \
		wheelhouse \
		src/*.egg-info \
		src/jetblack_memoryqueue/__pycache__ \
		tests/__pycache__ \
		src/jetblack_memoryqueue/*.so
