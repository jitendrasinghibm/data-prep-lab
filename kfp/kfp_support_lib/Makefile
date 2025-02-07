# Define the root of the local git clone for the common rules to be able
# know where they are running from.
REPOROOT=../..
include ${REPOROOT}/.make.versions


IGNORE := $(shell bash -c "sed -n /=/p  ${REPOROOT}/kfp/requirements.env | sed 's/=/:=/' | sed 's/^/export /' > makeenv")

include makeenv
# Include the common rules.
# Use "make help" to see them.
include ../../.make.defaults

PYTHON=python
PIP=$(PYTHON) -m pip
# Command to run pytest
PYTEST=pytest -s
PYTHON_VERSION=$(shell $(PYTHON) --version)
VENV_ACTIVATE=venv/bin/activate

DEPLOY_KUBEFLOW ?=0

clean::
	@# Help: Clean up the distribution build and the venv 
	rm -r dist venv || true
	rm -rf src/*egg-info || true
	rm makeenv || true

.check-env:: .check_python_version
	@echo "Checks passed"

update-toml:: .check-env
	@# Help: Copy the Makefile distribution version into the pyproject.toml
	sed -i.back 's/^version[ ]*=.*/version = "'${DPL_LIB_KFP_VERSION}'"/' pyproject.toml
	sed -i.back 's/data-prep-lab==[0-9].*/data-prep-lab==${DPL_LIB_VERSION}",/' pyproject.toml
	sed -i.back 's/kfp==[0-9].*/kfp==${KFP}",/' pyproject.toml

build:: update-toml venv
	@# Help: Build the distribution for publishing to a pypi 
	rm -r dist || true
	rm -rf src/*egg-info || true
	${PYTHON} -m pip install --upgrade build
	${PYTHON} -m build

publish:: .check-env
publish::
	@# Help: Publish the wheel to testpypi
	if [ -d "dist"]; then rm -r dist; fi
	${PYTHON} -m pip install --upgrade build
	${PYTHON} -m twine check dist/*
	${PYTHON} -m twine upload --verbose --non-interactive dist/*

venv::	pyproject.toml .check-env
	@# Help: Create the virtual environment using pyproject.toml 
	sed -i.back "s/data-prep-lab-kfp==[0-9].*/data-prep-lab-kfp==${DPL_LIB_KFP_VERSION}/" ../kfp_ray_components/requirements.txt
	rm -rf venv
	$(PYTHON) -m venv venv
	. ${VENV_ACTIVATE};     \
        pip install -r ../kfp_ray_components/requirements.txt ;\
	pip install -e .;		\
	pip install ray==${RAY} \
	pip install pytest pytest-cov 

test:: 	
	@# Help: Use the already-built virtual environment to run pytest on the test directory.
	. ${VENV_ACTIVATE}; export PYTHONPATH=../src; cd test;  $(PYTEST) api_params_test.py;
	. ${VENV_ACTIVATE}; export PYTHONPATH=../src; cd test;  $(PYTEST) kuberay_api_test.py;
ifeq ($(DEPLOY_KUBEFLOW),1)
	. ${VENV_ACTIVATE}; export PYTHONPATH=../src; cd test;  $(PYTEST) ray_remote_jobs_test.py;
	. ${VENV_ACTIVATE}; export PYTHONPATH=../src; cd test;  $(PYTEST) pipeline_utils_test.py;
endif
