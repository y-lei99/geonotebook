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
         python3-pip \
         python3-cffi \
         python3-lxml \
         python3-pillow \
         python3-numpy \
         python3-scipy \
         python3-pandas \
         python3-matplotlib \
         python3-seaborn \
         python3-statsmodels \
         python3-scikit-learn \
         cython \
         python3-futures \
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
