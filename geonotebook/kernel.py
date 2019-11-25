from inspect import getargspec, getmembers, isfunction, ismethod
from types import MethodType

from ipykernel.ipkernel import IPythonKernel
from promise import Promise

from . import jsonrpc
from .config import Config
from .jsonrpc import (is_request,
                      is_response,
                      json_rpc_request,
                      json_rpc_result)

from .layers import (AnnotationLayer,
                     GeonotebookLayerCollection,
                     NoDataLayer,
                     SimpleLayer,
                     TimeSeriesLayer,
                     VectorLayer)

from .utils import get_kernel_id
from .wrappers import RasterData, RasterDataCollection, VectorData


class Remote(object):
    """Provides an object that proxies procedures on a remote object.

    This takes a list of protocol definitions and dynamically generates methods
    on the object that reflect that protocol.  These methods wrap Promises
    which manage the reply and error callbacks of a remote proceedure call.
    Remote defines a '_promises' variable which is a dict of message id's to
    Promises.
    """

    def validate(self, protocol, *args, **kwargs):
        """Validate a protocol definition.

        :param protocol: Dict containing a single function's protocol
        :returns: Nothing
        :rtype: None

        """
        assert len(args) >= len(protocol["required"]), \
            "Protocol {} has an arity of {}. Called with {}".format(
                protocol['procedure'], len(protocol["required"]), len(args))

        assert len(args) <= len(protocol["required"]) + \
            len(protocol["optional"]), \
            "Protocol {} has an arity of {}. Called with {}".format(
                protocol['procedure'], len(protocol["required"]), len(args))

    def _make_protocol_method(self, protocol):
        """Make a method closure based on a protocol definition.

        This takes a protocol and generates a closure that has the same arity
        as the protocol. The closure is dynamically set as a method on the
        Remote object with the same name as protocol. This makes it possible
        to do:

        Geonotebook._remote.set_center(-74.25, 40.0, 4)

        which will validate the arguments, create a JSONRPC request object,
        generate a Promise and store it in the _promises dict.
        e.g:

        def handle_error(error):
            print "JSONError (%s): %s" % (error['code'], error['message'])

        def handle_reply(result):
            print(result)

        def handle_callback_error(error):
            print "Callback Error: %s" % error[0]

        Geonotebook._remote.set_center(-74.25, 40.0, 4).then(
            handle_reply, handle_error).catch(handle_callback_error)



        :param protocol: a protocol dict
        :returns: a closure that validates RPC arguments and returns a Promise
        :rtype: MethodType

        """
        assert 'required' in protocol, \
            "protocol {} must define required arguments".format(
                protocol['procedure'])
        assert 'optional' in protocol, \
            "protocol {} must define optional arguments".format(
                protocol['procedure'])

        for arg in protocol["required"]:
            assert 'key' in arg, \
                "protocol {} is malformed, argument {} " + \
                "does not have a key".format(
                    protocol['procedure'], arg)

        for arg in protocol["optional"]:
            assert 'key' in arg, \
                "protocol {} is malformed, argument {} " + \
                "does not have a key".format(
                    protocol['procedure'], arg)

        def _protocol_closure(self, *args, **kwargs):
            try:
                self.validate(protocol, *args, **kwargs)
            except Exception as e:
                # TODO: log something here
                raise e

            def make_param(key, value, required=True):
                return {'key': key, 'value': value, 'required': required}
            # Get the parameters
            params = [
                make_param(k['key'], v) for k, v in zip(
                    protocol['required'], args)
            ]
            # Not technically available until ES6
            params.extend([
                make_param(k['key'], kwargs[k['key']], required=False)
                for k in protocol['optional'] if k['key'] in kwargs
            ])

            # Create the message
            msg = json_rpc_request(protocol['procedure'], params)

            # Set up the callback
            self._promises[msg['id']] = Promise()
            self._send_msg(msg)

            # return the callback
            return self._promises[msg['id']]

        return MethodType(_protocol_closure, self)

    def resolve(self, msg):
        """Resolve an open JSONRPC request.

        Takes a JSONRPC result message and passes it to either the
        on_fulfilled handler or the on_rejected handler of the Promise.

        :param msg: JSONRPC result message
        :returns: Nothing
        :rtype: None

        """
        if msg['id'] in self._promises:
            try:
                if msg['error'] is not None:
                    self._promises[msg['id']].reject(Exception(msg['error']))
                else:
                    self._promises[msg['id']].fulfill(msg['result'])

            except Exception as e:
                raise e
        else:
            self.log.warn("Could not find promise with id %s" % msg['id'])

    def __init__(self, transport, protocol):
        """Initialize the Remote object.

        :param transport: function that takes a JSONRPC request message
        :param protocol: A list of protocol definitions for remote functions
        :returns: Nothing
        :rtype: None

        """
        self._promises = {}
        self._send_msg = transport
        self.protocol = protocol

        for p in self.protocol:
            assert 'procedure' in p, \
                ""

            setattr(self, p['procedure'], self._make_protocol_method(p))


class Geonotebook(object):
    msg_types = ['get_protocol', 'set_center', 'add_annotation_from_client',
                 'get_map_state']

    _protocol = None
    _remote = None

    @classmethod
    def class_protocol(cls):
        """Initialize the RPC protocol description.

        Provides a static, lazy loaded description of the functions that
        are available to be called by the RPC mechanism.

        :param cls: The class (e.g. Geonotebook)
        :returns: the protocol description
        :rtype: dict

        """
        if cls._protocol is None:
            def _method_protocol(fn, method):
                spec = getargspec(method)
                # spec.args[1:] so we don't include 'self'
                params = spec.args[1:]
                # The number of optional arguments
                d = len(spec.defaults) if spec.defaults is not None else 0
                # The number of required arguments
                r = len(params) - d

                def make_param(p, default=False):
                    return {'key': p, 'default': default}

                # Would be nice to include whether or to expect a reply, or
                # If this is just a notification function
                return {'procedure': fn,
                        'required': [make_param(p) for p in params[:r]],
                        'optional': [make_param(p, default=dd) for p, dd
                                     in zip(params[r:], spec.defaults)]
                        if spec.defaults is not None else []}

            # Note:  for the predicate we do ismethod or isfunction for
            # PY2/PY3 support
            # See: https://docs.python.org/3.0/whatsnew/3.0.html
            # "The concept of "unbound methods" has been removed from the
            # language.
            # When referencing a method as a class attribute, you now get a
            # plain function object."
            cls._protocol = {
                fn: _method_protocol(fn, method) for fn, method in
                getmembers(
                    cls,
                    predicate=lambda x: ismethod(x) or isfunction(x)
                ) if fn in cls.msg_types}

        return list(cls._protocol.values())

    def _send_msg(self, msg):
        """Send a message to the client.

        'msg' should be a well formed RPC message.

        :param msg: The RPC message
        :returns: Nothing
        :rtype: None

        """
        self._kernel.comm.send(msg)

    def _reconcile_parameters(self, method, params):
        param_hash = {p['key']: p for p in params}

        # Loop through protocol reconciling parameters
        # from out of the param_hash.  Note - does not do
        # any error checking - exceptions will be caught
        # and transformed into RPC errors
        try:
            args = [param_hash[p['key']]['value']
                    for p in self._protocol[method]['required']]
        except KeyError:
            raise jsonrpc.InvalidParams(
                u"missing required params for method: %s" % method
            )

        kwargs = {p['key']: param_hash[p['key']]['value']
                  for p in self._protocol[method]['optional']
                  if p['key'] in param_hash}

        return args, kwargs

    def _recv_msg(self, msg):
        """Recieve an RPC message from the client.

        :param msg: An RPC message
        :returns: Nothing
        :rtype: None

        """
        # If this is a response,  pass it along to the Remote object to be
        # processesd by the correct reply/error handler
        if is_response(msg):
            self._remote.resolve(msg)

        # Otherwise process the request from the remote RPC client.
        elif is_request(msg):
            method, params = msg['method'], msg['params']
            if method in self._protocol.keys():
                try:
                    args, kwargs = self._reconcile_parameters(method, params)

                    result = getattr(self, method)(*args, **kwargs)
                    self._send_msg(json_rpc_result(result, None, msg['id']))
                except Exception as e:
                    if isinstance(e, jsonrpc.JSONRPCError):
                        raise e
                    else:
                        raise jsonrpc.ServerError(str(e))
            else:
                raise jsonrpc.MethodNotFound("Method not allowed")
        else:
            raise jsonrpc.ParseError("Could not parse msg: %s" % msg)

    @property
    def log(self):
        return self._kernel.log

    def __init__(self, kernel, *args, **kwargs):

        self.view_port = None
        self.x = None
        self.y = None
        self.z = None
        self.layers = GeonotebookLayerCollection([])

        self._kernel = kernel

    @property
    def kernel_id(self):
        return get_kernel_id(self._kernel)

    def serialize(self):
        ret = {}

        if self.x and self.y and self.z:
            ret['center'] = [self.x, self.y, self.z]

        ret['layers'] = self.layers.serialize()

        return ret

    def rpc_error(self, error):
        try:
            self.log.error(
                "JSONRPCError (%s): %s" % (error['code'], error['message'])
            )
        except Exception:
            self.log.error(
                "JSONRPCError: Malformed error message: {}".format(error)
            )

    def callback_error(self, exception):
        import sys
        import traceback
        t, v, tb = sys.exc_info()
        self.log.error('Callback Error: \n%s' %
                       ''.join(traceback.format_exception(t, v, tb)))

    # Remote RPC wrappers #

    def set_center(self, x, y, z):
        """Set the center of the map.

        :param x:
        :param y:
        :param z:
        :returns:
        :rtype:

        """
        def _set_center(result):
            self.x, self.y, self.z = result

        return self._remote.set_center(x, y, z)\
            .then(_set_center, self.rpc_error).catch(self.callback_error)

    def get_map_state(self):
        """Get the state of the map.

        :returns: JSON serializable dictionary.
        :rtype: dict
        """
        return self.serialize()

    def add_layer(self, data, name=None, vis_url=None, **kwargs):
        """Create the GeonotebookLayer.

        If vis_url is none,  this will take data_path and upload it to the
        configured vis_server, this will make the visualization url available
        through the 'vis_url' attribute on the layer object.

        :param data:
        :param name:
        :param vis_url:
        :returns:
        :rtype:
        """
        # Make sure we pass in kernel_id to the layer,  then to the vis_server
        # Otherwise we cant generate the coorect vis_url.

        layer_type = kwargs.get('layer_type', None)

        kwargs['kernel_id'] = self.kernel_id

        if layer_type != 'annotation':
            kwargs['zIndex'] = len(self.layers)

        # HACK:  figure out a way to do this without so many conditionals
        if isinstance(data, RasterData):
            # TODO verify layer exists in geoserver?
            name = data.name if name is None else name

            layer = SimpleLayer(
                name, self._remote, data=data, vis_url=vis_url, **kwargs
            )
        elif isinstance(data, RasterDataCollection):
            assert name is not None, \
                RuntimeError("RasterDataCollection layers require a 'name'")

            layer = TimeSeriesLayer(
                name, self._remote, data=data, vis_url=vis_url, **kwargs
            )
        elif isinstance(data, VectorData):
            layer = VectorLayer(
                name, self._remote, self.layers, data=data, **kwargs
            )
        else:
            assert name is not None, \
                RuntimeError("Non data layers require a 'name'")
            if layer_type == 'annotation':
                layer = AnnotationLayer(
                    name, self._remote, self.layers, **kwargs
                )
            else:
                layer = NoDataLayer(
                    name, self._remote, vis_url=vis_url, **kwargs
                )

        def _add_layer(layer_name):
            self.layers.append(layer)

        return self._remote.add_layer(layer.name, layer.vis_url,
                                      layer.vis_options.serialize(),
                                      layer.query_params) \
                           .then(_add_layer, self.rpc_error) \
                           .catch(self.callback_error)

    def remove_layer(self, layer_name):
        # If layer_name is an object with a 'name' attribute we assume
        # thats the layer you want removed.  This allows us to pass in
        # GeonotebookLayer objects,  as well as regular string layer names
        if hasattr(layer_name, 'name'):
            layer_name = layer_name.name

        def _remove_layer(layer_name):
            self.layers.remove(layer_name)

        cb = self._remote.remove_layer(layer_name).then(
            _remove_layer, self.rpc_error).catch(self.callback_error)

        return cb

    # RPC endpoints #
    def get_protocol(self):
        return self.__class__.class_protocol()

    def add_annotation(self, ann_type, coords, meta=None):
        """Add an annotation to the annotation layer.

        :param str ann_type: 'point', 'rectangle', or 'polygon'
        :param list[dict] coords: A list of coordinates defining the annotation
        :param dict meta: Extra metadata stored with the annotation
        """
        def _add_annotation(response):
            meta.update(response)
            self.add_annotation_from_client(ann_type, coords, meta)
            return True

        meta = meta or {}
        return self._remote.add_annotation(
            ann_type, [coords], meta
        ).then(
            _add_annotation,
            self.rpc_error
        ).catch(self.callback_error)

    def add_annotation_from_client(self, ann_type, coords, meta):
        """Add an existing annotation to the map state.

        This method is not intended to be called by the user.  It
        exists to append an annotation initialized on the client
        to the server map state.
        """
        self.layers.annotation.add_annotation(ann_type, coords, meta)
        return True


class GeonotebookKernel(IPythonKernel):
    def _unwrap(self, msg):
        """Unwrap a Comm message.

        Remove the Comm envolpe and return an RPC message

        :param msg: the Comm message
        :returns: An RPC message
        :rtype: dict
        """
        return msg['content']['data']

    def handle_comm_msg(self, message):
        """Handle incomming comm messages.

        :param msg: a Comm message
        :returns: Nothing
        :rtype: None
        """
        msg = self._unwrap(message)

        try:
            self.geonotebook._recv_msg(msg)

        except jsonrpc.JSONRPCError as e:
            self.geonotebook._send_msg(
                json_rpc_result(None, e.tojson(), msg['id'])
            )
            self.log.error(u"JSONRPCError (%s): %s" % (e.code, e.message))

        except Exception as e:
            self.log.error(u"Error processing msg: {}".format(str(e)))

    def handle_comm_open(self, comm, msg):
        """Handle opening a comm.

        :param comm: The comm to open
        :param msg: The initial comm_open message
        :returns: Nothing
        :rtype: None
        """
        self.comm = comm
        self.comm.on_msg(self.handle_comm_msg)

        # TODO: Check if the msg is empty - no protocol - die
        self.geonotebook._remote = Remote(self.comm.send, self._unwrap(msg))
        # Reply to the open comm,  this should probably be set up on
        # self.geonotebook._remote as an actual proceedure call

        self.comm.send({
            "method": "set_protocol",
            "data": self.geonotebook.get_protocol()
        })

        # THis should be handled in a callback that is fired off
        # When set protocol etc is complete.
        if self.initializing:
            basemap = Config().basemap
            self.geonotebook.add_layer(
                None, name="osm_base", layer_type="osm",
                vis_url=basemap["url"],
                system_layer=True,
                attribution=basemap["attribution"])

            self.geonotebook.add_layer(
                None, name="annotation",
                layer_type="annotation", vis_url=None,
                system_layer=True, expose_as="annotation")

            self.initializing = False

    def do_shutdown(self, restart):
        self.geonotebook = None

        super(GeonotebookKernel, self).do_shutdown(restart)

        config = Config()
        config.vis_server.shutdown_kernel(self)

        if restart:
            self.geonotebook = Geonotebook(self)
            self.shell.user_ns.update({'M': self.geonotebook})

    def start(self):
        self.geonotebook = Geonotebook(self)
        self.shell.user_ns.update({'M': self.geonotebook})
        super(GeonotebookKernel, self).start()

        config = Config()
        self.log.setLevel(config.log_level)

        config.vis_server.start_kernel(self)

    def __init__(self, **kwargs):
        self.log = kwargs['log']
        self.initializing = True

        super(GeonotebookKernel, self).__init__(**kwargs)

        self.comm_manager.register_target('geonotebook', self.handle_comm_open)
