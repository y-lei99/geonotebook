#!/bin/bash
# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.

set -e

wrapper=""
if [[ "${RESTARTABLE}" == "yes" ]]; then
    wrapper="run-one-constantly"
fi

if [[ ! -z "${JUPYTERHUB_API_TOKEN}" ]]; then
    # launched by JupyterHub, use single-user entrypoint
    exec /opt/conda/geonotebook/jupyter.sh "$@"
elif [[ ! -z "${JUPYTER_ENABLE_LAB}" ]]; then
    . /opt/conda/geonotebook/jupyter.sh $wrapper jupyter lab "$@"
else
    . /opt/conda/geonotebook/jupyter.sh $wrapper jupyter notebook "$@"
fi
