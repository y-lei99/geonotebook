FROM ubuntu:18.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update -y && apt-get upgrade -y --assume-yes apt-utils
RUN apt-get install -y gcc g++ make curl wget
RUN apt-get -y install nodejs npm

RUN apt-get install -y libgeos-dev

RUN wget https://pypi.python.org/packages/source/s/setuptools/setuptools-19.6.tar.gz
RUN tar -zxvf setuptools-19.6.tar.gz

WORKDIR setuptools-19.6

RUN python3 -U setup.py build && python3 -U setup.py install
RUN ldconfig

RUN curl -O http://download.osgeo.org/gdal/2.1.3/gdal-2.1.3.tar.gz
RUN tar -xzf gdal-2.1.3.tar.gz

WORKDIR gdal-2.1.3

RUN ./configure
RUN make -j$(nproc)
RUN make install
RUN ldconfig

RUN apt-get install -y git \
                       ssh \
                       libffi-dev \
                       libssl-dev \
                       libproj-dev \
                       python-pip \
                       python3-pip \
                       python3-cffi \
                       python3-lxml \
                       python3-pil \
                       python3-numpy \
                       python3-scipy \
                       python3-pandas \
                       python3-matplotlib \
                       python3-seaborn \
                       python-concurrent.futures \
                       cython \
                       python-scikits-learn \
                       python-statsmodels \
                       python-statsmodels-lib \
                       python-skimage-lib

# Generates pip2.7
RUN pip install -U pip


RUN pip3 install -U jupyter notebook \
                   pyproj \
                   ipywidgets \
                   scikit-image \
                   pyOpenSSL
RUN pip2.7 install -U mapnik
RUN jupyter nbextension enable --py widgetsnbextension --sys-prefix

# Generate default config and disable authentication
RUN jupyter-notebook --generate-config --allow-root
RUN sed -i "s/#c.NotebookApp.token = '<generated>'/c.NotebookApp.token = ''/" /root/.jupyter/jupyter_notebook_config.py

# Install/setup NVM
RUN curl -o- https://raw.githubusercontent.com/creationix/nvm/v0.33.1/install.sh | bash \
    && . /root/.bashrc && nvm install v6.10.1 && ln -s /root/.nvm/versions/node/v6.10.1/bin/npm /usr/bin/npm

RUN pip3 install https://github.com/OpenGeoscience/KTile/archive/master.zip


ADD . /opt/geonotebook
ADD ./devops/docker/jupyter.sh /jupyter.sh

WORKDIR /opt/geonotebook
 

RUN pip3 install -r prerequirements.txt
RUN pip3 install -r requirements.txt
RUN pip3 install .
RUN jupyter serverextension enable --py geonotebook --sys-prefix
RUN jupyter nbextension enable --py geonotebook --sys-prefix

VOLUME /notebooks
WORKDIR /notebooks

ENTRYPOINT ["/jupyter.sh"]
