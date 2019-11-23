from collections import MutableMapping

import os

from notebook.utils import url_path_join as ujoin

import requests

import TileStache as ts
# NB:  this uses a 'private' API for parsing the Config layer dictionary
from TileStache.Config import _parseConfigLayer as parseConfigLayer

from geonotebook.utils import get_kernel_id

from .handler import (KtileHandler,
                      KtileLayerHandler,
                      KtileTileHandler)


# Manage kernel_id => layer configuration section
# Note - when instantiated this is a notebook-wide class,
# it manages the configuration for all running geonotebook
# kernels. It lives inside the Tornado Webserver
class KtileConfigManager(MutableMapping):
    def __init__(self, default_cache, *args, **kwargs):
        self.default_cache = default_cache
        self._configs = {}

    def __getitem__(self, *args, **kwargs):
        return self._configs.__getitem__(*args, **kwargs)

    def __setitem__(self, _id, value):
        self._configs.__setitem__(_id, value)

    def __delitem__(self, *args, **kwargs):
        return self._configs.__delitem__(*args, **kwargs)

    def __iter__(self, *args, **kwargs):
        return self._configs.__iter__(*args, **kwargs)

    def __len__(self, *args, **kwargs):
        return self._configs.__len__(*args, **kwargs)

    def add_config(self, kernel_id, **kwargs):
        cache = kwargs.get("cache", self.default_cache)

        self._configs[kernel_id] = ts.parseConfig({
            "cache": cache,
            "layers": {}
        })

    def add_layer(self, kernel_id, layer_name, layer_dict, dirpath=''):
        # NB: dirpath is actually not used in _parseConfigLayer So dirpath
        # should have no effect regardless of its value.

        # Note: Needs error checking
        layer = parseConfigLayer(layer_dict, self._configs[kernel_id], dirpath)

        if layer_name not in self._configs[kernel_id].layers:
            self._configs[kernel_id].layers[layer_name] = layer

        return layer.provider.generate_vrt()
        try:
            layer.provider.generate_vrt()
        except AttributeError:
            pass
        return True


# Ktile vis_server,  this is not a persistent object
# It is brought into existence as a client to provide access
# to the KtileConfigManager through the Tornado webserver's
# REST API vi ingest/get_params. It is instantiated once inside
# the tornado app in order to call initialize_webapp.  This sets
# up the REST API that ingest/get_params communicate with. It also
# provides access points to start_kernel and shutdown_kernel for
# various initialization. NB: State CANNOT be shared across these
# different contexts!

class Ktile(object):
    def __init__(self, config, url=None, default_cache=None):
        self.config = config
        self.base_url = url
        self.default_cache_section = default_cache

    @property
    def default_cache(self):
        return dict(self.config.items(self.default_cache_section))

    def start_kernel(self, kernel):
        kernel_id = get_kernel_id(kernel)
        requests.post("{}/{}".format(self.base_url, kernel_id))
        # Error checking on response!

    def shutdown_kernel(self, kernel):
        kernel_id = get_kernel_id(kernel)
        requests.delete("{}/{}".format(self.base_url, kernel_id))

    # This function is caleld inside the tornado web app
    # from jupyter_load_server_extensions
    def initialize_webapp(self, config, webapp):
        base_url = webapp.settings['base_url']

        webapp.ktile_config_manager = KtileConfigManager(
            self.default_cache)

        webapp.add_handlers('.*$', [
            # kernel_name
            (ujoin(base_url, r'/ktile/([^/]*)'),
             KtileHandler,
             dict(ktile_config_manager=webapp.ktile_config_manager)),

            # kernel_name, layer_name
            (ujoin(base_url, r'/ktile/([^/]*)/([^/]*)'),
             KtileLayerHandler,
             dict(ktile_config_manager=webapp.ktile_config_manager)),

            # kernel_name, layer_name, x, y, z, extension
            (ujoin(base_url,
                   r'/ktile/([^/]*)/([^/]*)/([^/]*)/([^/]*)/([^/\.]*)\.(.*)'),
             KtileTileHandler,
             dict(ktile_config_manager=webapp.ktile_config_manager)),

        ])

    # get_params should take a generic list of parameters e.g. 'bands',
    # 'range', 'gamma' and convert these into a list of vis_server specific
    # parameters which will be passed along to the tile render handler in
    # add_layer. This is intended to allow the vis_server to include style
    # parameters and subsetting operations. select bands, set ranges
    # on a particular dataset etc.
    def get_params(self, name, data, **kwargs):
        # All paramater setup is handled on ingest
        return {}

    def _static_vrt_options(self, data, kwargs):
        options = {
            'vrt_path': kwargs['vrt_path'],
            'bands': data.band_indexes,
        }

        return options

    def _dynamic_vrt_options(self, data, kwargs):
        options = {
            'path': os.path.abspath(data.reader.path),
            'bands': data.band_indexes,

            'nodata': data.nodata,
            # TODO:  Needs to be moved into RasterData level API
            'raster_x_size': data.reader.width,
            'raster_y_size': data.reader.height,
            'transform': data.reader.dataset.profile['transform'],
            'dtype': data.reader.dataset.profile['dtype']
        }
        if 'map_srs' in kwargs:
            options['map_srs'] = kwargs['map_srs']

        return options

    def ingest(self, data, name=None, **kwargs):

        # Verify that a kernel_id is present otherwise we can't
        # post to the server extension to add the layer
        kernel_id = kwargs.pop('kernel_id', None)
        if kernel_id is None:
            raise Exception(
                "KTile vis server requires kernel_id as kwarg to ingest!")

        options = {
            'name': data.name if name is None else name
        }

        options.update(kwargs)

        # Note:
        # Check if the reader has defined a vrt_path
        #
        # This is mostly intended for the VRTReader so that it can communicate
        # that the VRT for reading data is also the VRT that should be used for
        # visualisation. Otherwise we wouild have to explicitly add a vrt_path
        # kwarg to the add_layer() call.
        #
        # A /different/ VRT can still be used for visualisation by passing
        # a path via vrt_path to add_layer.
        #
        # Finally, A dynamic VRT will ALWAYS be generated if vrt_path is
        # explicitly set to None via add_layer.
        if hasattr(data.reader, 'vrt_path'):
            if 'vrt_path' in kwargs and kwargs['vrt_path'] is None:
                # Explicitly set to None
                pass
            else:
                kwargs['vrt_path'] = data.reader.vrt_path

        # If we have a static VRT
        if 'vrt_path' in kwargs and kwargs['vrt_path'] is not None:
            options.update(self._static_vrt_options(data, kwargs))
        else:
            # We don't have a static VRT, set options for a dynamic VRT
            options.update(self._dynamic_vrt_options(data, kwargs))

        # Make the Request
        base_url = '{}/{}/{}'.format(self.base_url, kernel_id, name)

        r = requests.post(base_url, json={
            "provider": {
                "class": "geonotebook.vis.ktile.provider:MapnikPythonProvider",
                "kwargs": options
            }
            # NB: Other KTile layer options could go here
            #     See: http://tilestache.org/doc/#layers
        })

        if r.status_code == 200:
            return base_url
        else:
            raise RuntimeError(
                "KTile.ingest() returned {} error:\n\n{}".format(
                    r.status_code, ''.join(r.json()['error'])))
