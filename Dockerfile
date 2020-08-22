FROM archlinux/base:latest

RUN set -ex \
    && pacman -Sy --noconfirm archlinux-keyring \
    && pacman -Syu --noconfirm \
    && pacman-db-upgrade \
    && pacman -S --noconfirm \
         ca-certificates \
         ca-certificates-utils

RUN set -ex \
    && pacman -S --noconfirm \
         git \
         openssh \
         npm \
         autoconf \
         automake \
         gcc \
         python3 \
         pip3 \
         cffi \
         lxml \
         pillow \
         numpy \
         scipy \
         pandas \
         matplotlib \
         seaborn \
         statsmodels \
         scikit-learn \
         cython \
         futures \
         gdal \
         mapnik \
         sed


RUN set -ex \
    && pip3 install \
         notebook \
         mapnik \
         pyproj \
         ipywidgets \
         scikit-image

RUN jupyter nbextension enable --py widgetsnbextension --sys-prefix

# Generate default config and disable authentication
RUN /usr/sbin/jupyter-notebook --generate-config \
    && sed -i s/#c.NotebookApp.token\ \=\ \'\'/c.NotebookApp.token\ \=\ \'\'/g \
           /root/.jupyter/jupyter_notebook_config.py

RUN pip3 install https://github.com/OpenGeoscience/KTile/archive/master.zip

ADD . /opt/geonotebook
ADD devops/docker/jupyter.sh /jupyter.sh

RUN pushd /opt/geonotebook \
    && pip3 install . \
    && jupyter serverextension enable --py geonotebook --sys-prefix \
    && jupyter nbextension enable --py geonotebook --sys-prefix

VOLUME /notebooks
WORKDIR /notebooks
CMD ../jupyter.sh
