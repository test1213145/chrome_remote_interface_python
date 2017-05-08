import requests, base64, json, os, types, copy, collections, traceback
import base64

try:
    import websocket
except ImportError:
    pass

try:
    import asyncio
    import websockets
except ImportError:
    pass



class Protocol:
    '''
    Load and updates protocol
    '''
    BASE = 'https://chromium.googlesource.com'
    BROWSER_PROTOCOL = '/chromium/src/+/master/third_party/WebKit/Source/core/inspector/browser_protocol.json?format=TEXT'
    JS_PROTOCOL = '/v8/v8/+/master/src/inspector/js_protocol.json?format=TEXT'
    PROTOCOL_FILE_NAME = 'protocol.json'

    _protocol = None

    @classmethod
    def get_protocol(cls):
        cls._check()
        return cls._protocol

    @classmethod
    def update_protocol(cls):
        cls._protocol = cls._update_protocol()
        return cls._protocol

    @classmethod
    def _check(cls):
        if cls._protocol is None:
            cls._protocol = cls._load_protocol()

    @classmethod
    def _load_protocol(cls):
        try:
            with open (cls._get_protocol_file_path(), 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return cls._update_protocol()

    @classmethod
    def _update_protocol(cls):
        result = cls._download_protocol(cls.BASE + cls.BROWSER_PROTOCOL)
        result['domains'] += cls._download_protocol(cls.BASE + cls.JS_PROTOCOL)['domains']
        with open(cls._get_protocol_file_path(), 'w') as f:
            json.dump(result, f, indent=4, sort_keys=True)
        return result

    @classmethod
    def _download_protocol(cls, url):
        resp = requests.get(url)
        data = base64.b64decode(resp.text)
        return json.loads(data)

    @classmethod
    def _get_protocol_file_path(cls):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), cls.PROTOCOL_FILE_NAME)

class FailReponse(Exception):
    '''
    Raised if chrome doesn't like our request
    '''
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code

class API:
    '''
    Making magick with json data to create classes and functions
    '''
    def __init__(self):
        raw_type_handlers = []
        self._raw_protocol = copy.deepcopy(Protocol.get_protocol())
        self.events = self._empty_class()
        self._event_name_to_event = {}
        self._method_name_to_method = {}
        versions = self._raw_protocol['version']
        for value in self._raw_protocol['domains']:
            domain = value['domain']
            if not hasattr(self, domain):
                setattr(self, domain, self._repr_class(domain))
            current_child = getattr(self, domain)
            if 'description' in value:
                current_child.__doc__ = value['description']
            current_child.experimental = value['experimental'] if 'experimental' in value else False
            current_child.dependencies = value['dependencies'] if 'dependencies' in value else []
            raw_types = value['types'] if 'types' in value else []
            for raw_type in raw_types:
                self._connect_raw_type(raw_type, domain, raw_type_handlers, current_child, raw_type['id'], domain+'.'+raw_type['id'])
            raw_commands = value['commands'] if 'commands' in value else [] # DIR
            for raw_command in raw_commands:
                method = self._make_send_method(domain+'.'+raw_command['name'], domain+'.'+raw_command['name'])
                method.parameters = {}
                raw_parameters = raw_command['parameters'] if 'parameters' in raw_command else []
                for raw_parameter in raw_parameters:
                    self._connect_raw_parameter_or_result(raw_parameter, domain, raw_type_handlers, method.parameters)
                method.returns = {}
                raw_returns = raw_command['returns'] if 'returns' in raw_command else []
                for raw_return in raw_returns:
                    self._connect_raw_parameter_or_result(raw_return, domain, raw_type_handlers, method.returns)
                method.redirect = raw_command['redirect'] if 'redirect' in raw_command else None
                method.experimental = raw_command['experimental'] if 'experimental' in raw_command else False
                if 'description' in raw_command:
                    method.__doc__ = raw_command['description']
                pythonic_name = self._pythonic_method_name(raw_command['name'])
                self._method_name_to_method[domain + '.' + raw_command['name']] = method
                setattr(current_child, pythonic_name, method)
            raw_events = value['events'] if 'events' in value else [] # DOC?
            for raw_event in raw_events:
                callback_name = domain.lower() + '__' + self._pythonic_method_name(raw_event['name'])
                event_name = domain + '.' + raw_event['name']
                event = self._repr_class(callback_name)
                self._event_name_to_event[event_name] = event
                if 'description' in raw_event:
                    event.__doc__ = raw_event['description']
                event.experimental = raw_event['experimental'] if 'experimental' in raw_event else False
                raw_parameters = raw_event['parameters'] if 'parameters' in raw_event else []
                event.parameters = {}
                for raw_parameter in raw_parameters:
                    self._connect_raw_parameter_or_result(raw_parameter, domain, raw_type_handlers, event.parameters)
                setattr(self.events, callback_name, event)
        while len(raw_type_handlers) > 0:
            for parent, key, raw_type, connect_function, access_function, domain, class_repr, callbacks in raw_type_handlers:
                self._connect_raw_type(raw_type, domain, raw_type_handlers, parent, key, class_repr, connect_function, access_function, callbacks)

    def _connect_raw_type(self, raw_type, domain, raw_type_handlers, parent, key, class_repr=None, connect_function=setattr, access_function=getattr, callback=None):
        success_remove_tuple = parent, key, raw_type, connect_function, access_function, domain, class_repr, callback
        if '$ref' in raw_type:
            ref = raw_type['$ref']
            try:
                var1, var2 = ref.split('.', 1)
            except ValueError:
                var1 = domain
                var2 = ref
            try:
                if len(raw_type) == 1:
                    connect_function(parent, key, getattr(getattr(self, var1), var2))
                    if success_remove_tuple in raw_type_handlers:
                        raw_type_handlers.remove(success_remove_tuple)
                    if callback is not None:
                        callback()
                else:
                    connect_function(parent, key, copy.deepcopy(getattr(getattr(self, var1), var2)))
                    if success_remove_tuple in raw_type_handlers:
                        raw_type_handlers.remove(success_remove_tuple)
                    if callback is not None:
                        callback()
                    # print('kolobok', key, access_function(parent, key).optional)
                    obj = access_function(parent, key)
                    if 'optional' in raw_type:
                        obj.optional = raw_type['optional']
                    if 'experimental' in raw_type:
                        obj.experimental = raw_type['experimental']
                    if 'description' in raw_type:
                        obj.__doc__ = raw_type['description']
            except AttributeError:
                if success_remove_tuple not in raw_type_handlers:
                    raw_type_handlers.append(success_remove_tuple)
        elif 'type' in raw_type:
            t = raw_type['type']
            if t == 'array':
                class CoolType(list, metaclass=self.CustomClassReprType):
                    def __init__(slf, values):
                        if slf.min_items is not None and len(values) < slf.min_items:
                            raise ValueError('Min items is lower than')
                        if slf.max_items is not None and len(values) > slf.max_items:
                            raise ValueError('Max items is lower than')
                        if slf.type is None:
                            super().__init__(values)
                        else:
                            resulting_values = []
                            for value in values:
                                resulting_values.append(slf.type(value))
                            super().__init__(resulting_values)
                CoolType._class_repr = class_repr if class_repr is not None else list.__name__
                CoolType._type = list
                CoolType.max_items = raw_type['max_items'] if 'max_items' in raw_type else None
                CoolType.min_items = raw_type['min_items'] if 'min_items' in raw_type else None
                raw_items = raw_type['items'] if 'items' in raw_type else None
                if raw_items is None:
                    CoolType.type = None
                else:
                    self._connect_raw_type(raw_items, domain, raw_type_handlers, CoolType, 'type')
            elif t == 'object':
                if 'properties' in raw_type:
                    class CoolType(dict, metaclass=self.CustomClassReprType):
                        def __init__(slf, values=None, **kwargs):
                            if values is not None:
                                pass
                            elif len(kwargs) > 0:
                                values = kwargs
                            else:
                                raise TypeError('Need values or key-value arguments')
                            to_add = set(slf.property_names.keys())
                            for key in values:
                                if key not in slf.property_names:
                                    raise ValueError('there is no such property: {0}'.format(key))
                                else:
                                    slf[key] = slf.property_names[key].type(values[key])
                                    to_add.remove(key)
                            to_remove_from_add = set()
                            for key in to_add:
                                if slf.property_names[key].optional:
                                    slf[key] = None
                                    to_remove_from_add.add(key)
                            to_add = to_add.difference(to_remove_from_add)
                            if len(to_add) > 0:
                                raise ValueError('Not enough parameters: {0}'.format(', '.join(to_add)))
                        def __getattr__(self, name):
                            if name in self:
                                return self[name]
                            else:
                                return super().__getattr__(name)
                        def __repr__(self):
                            return '{0}({1})'.format(self._class_repr, super().__repr__())
                        def __dir__(self):
                            return super().__dir__() + list(self.keys())
                    CoolType._class_repr = class_repr
                    raw_properties = raw_type['properties'] if 'properties' in raw_type else []
                    CoolType.property_names = {}
                    for raw_property in raw_properties:
                        CoolType.property_names[raw_property['name']] = self._make_ppr(raw_property)
                        self._connect_raw_type(raw_property, domain, raw_type_handlers, CoolType.property_names[raw_property['name']], 'type')
                else:
                    CoolType = self._dummy_cool_type(class_repr, dict)
                    CoolType._type = dict
            elif t == 'string':
                enum = raw_type['enum'] if 'enum' in raw_type else None
                if enum is None:
                    CoolType = self._dummy_cool_type(class_repr, str)
                else:
                    class CoolType(str, metaclass=self.CustomClassReprType):
                        def __new__(cls, value):
                            if value not in cls.enum:
                                raise ValueError('string must be one of the following: {0}'.format(', '.join(cls.enum)))
                            return value
                    CoolType.enum = enum
                    CoolType._class_repr = class_repr
            elif t in ['integer', 'number', 'any', 'boolean']:
                name_to_class = {'integer': int, 'number': float, 'boolean': bool, 'any': None}
                CoolType = self._dummy_cool_type(class_repr, name_to_class[t])
                if name_to_class[t] is not None:
                    CoolType._class_repr = name_to_class[t].__name__
            else:
                raise ValueError('Unknown type: {0}'.format(t))
            if 'description' in raw_type:
                CoolType.__doc__ = raw_type['description']
            CoolType.experimental = raw_type['experimental'] if 'experimental' in raw_type else None
            CoolType.deprecated = raw_type['deprecated'] if 'deprecated' in raw_type else False
            CoolType.optional = raw_type['optional'] if 'optional' in raw_type else False
            connect_function(parent, key, CoolType)
            if success_remove_tuple in raw_type_handlers:
                raw_type_handlers.remove(success_remove_tuple)
            if callback is not None:
                callback()
        else:
            raise ValueError('There is no type or $ref {0}'.format(raw_type))

    def _connect_raw_parameter_or_result(self, raw_value, domain, raw_type_handlers, parent):
        value = self._empty_class()
        name = raw_value.pop('name')
        def callback():
            o = parent[name]
            if hasattr(o, '_type'):
                o._class_repr = o._type.__name__
        parent[name] = self._make_ppr(raw_value)
        self._connect_raw_type(raw_value, domain, raw_type_handlers, parent[name], 'type', callback=callback)

    def _make_send_method(self, original_name, class_repr):
        class result():
            def __call__(slf, **kwargs):
                for key, value in slf.parameters.items():
                    if not value.optional and key not in kwargs:
                        raise TypeError('Required argument \'{0}\' not found'.format(key))
                for key, arg in kwargs.items():
                    param = slf.parameters[key].type
                    potential_class = param._type if hasattr(param, '_type') else param
                    valid = (arg.__class__ == potential_class) or (potential_class == float and arg.__class__ == int)
                    if not valid:
                        raise ValueError('Param \'{0}\' must be {1}'.format(key, potential_class))
                return self.send_raw(slf._original_name, kwargs, slf.returns)
            def __repr__(self):
                return self._class_repr
        result._original_name = original_name
        result._class_repr = class_repr
        return result()

    def _unpack_event(self, event_name, values):
        domain, pidor = event_name.split('.')
        callback_name = domain.lower() + '__' + self._pythonic_method_name(pidor)
        try:
            parameters = self._event_name_to_event[event_name].parameters
            result = {}
            for key, value in values.items():
                if key in parameters:
                    result[key] = parameters[key].type(value)
            return result, callback_name
        except KeyError:
            return values, callback_name

    def _unpack_response(self, method_name, values):
        try:
            returns = self._method_name_to_method[method_name].returns
            result = {}
            for key, value in values.items():
                if key in returns:
                    result[key] = result[returns[key].type](value)
        except KeyError:
            result = values
        if len(result) == 0:
            return
        elif len(result) == 1:
            return next(iter(result.items()))[1]
        else:
            return result

    def _pythonic_method_name(self, old_name):
        old_one = list(old_name)
        new_one = []
        previous_was_low = False
        previous_was_underscore = False
        previous_was_first = True
        for i in reversed(range(len(old_one))):
            c = old_one[i]
            if c.isupper():
                if previous_was_low:
                    new_one.append('_'+c.lower())
                    previous_was_underscore = True
                else:
                    new_one.append(c.lower())
                    previous_was_underscore = False
                previous_was_low = False
            else:
                if previous_was_low:
                    new_one.append(c)
                else:
                    if previous_was_underscore or previous_was_first:
                        new_one.append(c)
                    else:
                        new_one.append(c+'_')
                previous_was_underscore = False
                previous_was_low = True
            previous_was_first = False
        return ''.join(reversed(new_one))

    def _dummy_cool_type(self, class_repr, t):
        class CoolType(metaclass=self.CustomClassReprType):
            def __new__(cls, obj):
                if cls._type == float and type(obj) == int:
                    obj = float(obj)
                if cls._type is not None and cls._type != type(obj):
                    raise ValueError('Type must be {0}, not {1}'.format(cls._type, type(obj)))
                return obj
        CoolType._type = t
        CoolType._class_repr = class_repr
        return CoolType

    class CustomClassReprType(type):
        def __repr__(self):
            if self._class_repr is not None:
                return self._class_repr
            else:
                return super().__repr__()

    def _make_ppr(self, raw_thing):
        result = self._empty_class()
        result.optional = raw_thing.pop('optional') if 'optional' in raw_thing else False
        result.deprecated = raw_thing.pop('deprecated') if 'deprecated' in raw_thing else False
        result.experimental =  raw_thing.pop('experimental') if 'experimental' in raw_thing else False
        if 'description' in raw_thing:
            result.__doc__ = raw_thing.pop('description')
        return result

    def _empty_class(self):
        class a: pass
        return a

    def _repr_class(self, class_repr):
        class a(metaclass=self.CustomClassReprType): pass
        a._class_repr = class_repr
        return a

class helpers:
    '''
    I put here some helping tools.
    '''
    def unpack_response_body(packed):
        result = packed['body']
        if packed['base64Encoded']:
            result = base64.b64decode(result)
        return result

class TabsSync:
    '''
    These tabs can be used to work synchronously from terminal
    '''
    def __init__(self, host, port, callbacks=None):
        self._host = host
        self._port = port
        self._tabs = []
        self._callbacks = callbacks

    FailReponse = FailReponse
    helpers = helpers

    def __repr__(self):
        return '{0}({1}:{2})'.format(type(self).__name__, self._host, self._port)

    @property
    def host(self):
        return self._host

    @property
    def port(self):
        return self._port

    def add(self):
        tab = SocketClientSync(self._host, self._port, self)
        self._tabs.append(tab)
        return tab

    def __getitem__(self, pos):
        if isinstance(pos, int):
            return self._tabs[pos]
        else:
            raise TypeError('{0} indices must be integers'.format(type(self).__name__))

    def remove(self, value):
        if isinstance(value, int):
            pos = value
        else:
            pos = None
            for i in range(len(self._tabs)):
                if self._tabs[i] == value:
                    pos = tab_client
            if pos is None:
                raise ValueError('Tab not found')
        self._tabs[pos].close()

class SocketClientSync(API): 
    '''
    These tab client can be used to work synchronously from terminal
    '''
    def __init__(self, host, port, tabs=None):
        super().__init__()
        self._host = host
        self._port = port
        self._tab_info = json.loads(requests.get('http://{0}:{1}/json/new/'.format(self._host, self._port)).text)
        self._ws_url = self._tab_info['webSocketDebuggerUrl']
        self._soc = websocket.create_connection(self._ws_url)
        self._i = 0
        self._tabs = tabs

    @property
    def ws_url(self):
        return self._ws_url

    def __repr__(self):
        return 'SocketClientSync("{0}")'.format(self._ws_url)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self._soc.close()

    def send_raw(self, method, params=None, expectedTypes=None):
        self._i += 1
        self._soc.send(json.dumps({'id': self._i, 'method': method, 'params': params}))
        while 1:
            resp = json.loads(self._soc.recv())
            if 'id' in resp and 'result' in resp:
                i = resp['id']
                if i != self._i:
                    raise RuntimeError('ids are not the same {0} != {0}'.format(i, self._i))
                result = resp['result']
                if expectedTypes is not None:
                    return self._unpack_response(method, result)
                else:
                    return result
            elif 'method' in resp and 'params' in resp:
                method = resp['method']
                params = resp['params']
                self._handle_event(method, params)
            elif 'error' in resp:
                i = resp['id']
                if i != self._i:
                    raise RuntimeError('ids are not the same {0} != {0}'.format(i, self._i))
                raise FailReponse(resp['error']['message'], resp['error']['code'])
            else:
                raise RuntimeError('Unknown data came: {0}'.format(resp))

    def _handle_event(self, method, params):
        parameters, callback_name = self._unpack_event(method, params)
        if self._tabs is not None and self._tabs._callbacks is not None:
            callbacks = self._tabs._callbacks
            if hasattr(callbacks, callback_name):
                getattr(callbacks, callback_name)(**parameters)
            elif hasattr(callbacks, 'any'):
                callbacks.any(parameters)
            else:
                pass

    def recv(self):
        n = 0
        self._soc.settimeout(0.1)
        try:
            got = self._soc.recv()
            while 1:
                try:
                    val = json.loads(got)
                    self._handle_event(val['method'], val['params'])
                    n += 1
                    break
                except json.JSONDecodeError as e:
                    self._handle_event(got[:e.pos])
                    n += 1
                    got = got[e.pos:]
        except websocket.WebSocketTimeoutException:
            pass
        self._soc.settimeout(None)
        return n

    def close(self):
        if self._soc is not None:
            self._soc.close()
            self._soc = None
            requests.get('http://{0}:{1}/json/close/{2}'.format(self._host, self._port, self._tab_info['id']))

    def remove(self):
        self.close()
        if self._tabs is not None:
            self._tabs.remove(self)
            self._tabs = None

class Tabs:
    '''
    Tabs here
    '''
    def __init__(self, host, port, callbacks=None):
        self._host = host
        self._port = port
        self._tabs = []
        self._callbacks = callbacks
        self._terminate_lock = asyncio.Lock()

    FailReponse = FailReponse
    helpers = helpers

    def __repr__(self):
        return '{0}({1}:{2})'.format(type(self).__name__, self._host, self._port)

    async def __aenter__(self):
        await self._terminate_lock.acquire()
        return self

    async def __aexit__(self, type, value, traceback):
        for tab in self._tabs:
            await tab.close()

    @property
    def host(self):
        return self._host

    @property
    def port(self):
        return self._port

    async def add(self):
        tab = await SocketClient(self._host, self._port, self).__aenter__()
        self._tabs.append(tab)
        return tab

    def __getitem__(self, pos):
        if isinstance(pos, int):
            return self._tabs[pos]

    @classmethod
    async def run(cls, host, port, callbacks):
        async with Tabs(host, port, callbacks) as tabs:
            try:
                await callbacks.start(tabs)
                await tabs._terminate_lock.acquire()
            except websockets.ConnectionClosed:
                pass

    def terminate(self):
        self._terminate_lock.release()

    async def remove(self, value):
        if isinstance(value, int):
            pos = value
        else:
            pos = None
            for i in range(len(self._tabs)):
                if self._tabs[i] == value:
                    pos = i
            if pos is None:
                raise ValueError('Tab not found')
        await self._tabs[pos].__aexit___()
        del self._tabs[pos]
        requests.get('http://{0}:{1}/json/close/{2}'.format(self._host, self._port, self._tab_info['id']))

class SocketClient(API):
    '''
    this client is cool
    '''
    def __init__(self, host, port, tabs=None):
        super().__init__()
        self._host = host
        self._port = port
        self._tab_info = json.loads(requests.get('http://{0}:{1}/json/new/'.format(self._host, self._port)).text)
        self._ws_url = self._tab_info['webSocketDebuggerUrl']
        self._i = 0
        self._tabs = tabs
        self._method_responses = {}
        self._recv_data_lock = {}

    @property
    def ws_url(self):
        return self._ws_url

    def __repr__(self):
        return '{0}("{1}")'.format(type(self).__name__, self._ws_url)

    async def __aenter__(self):
        self._soc = await websockets.connect(self._ws_url)
        async def loop():
            try:
                while self._soc is not None:
                    resp = json.loads(await self._soc.recv())
                    if 'id' in resp:
                        self._method_responses[resp['id']] = resp
                        self._recv_data_lock[resp['id']].release()
                    elif 'method' in resp:
                        asyncio.ensure_future(self._handle_event(resp['method'], resp['params']))
                    else:
                        raise RuntimeError('Unknown data came: {0}'.format(resp))
            except websockets.ConnectionClosed:
                pass
            except Exception as e:
                traceback.print_exc()
        asyncio.ensure_future(loop())
        return self

    async def __aexit__(self, type, value, traceback):
        await self._soc.close()

    async def send_raw(self, method, params=None, expectedTypes=None):
        self._i += 1
        i = self._i
        self._recv_data_lock[i] = asyncio.Lock()
        await self._recv_data_lock[i].acquire()
        await self._soc.send(json.dumps({'id': i, 'method': method, 'params': params}))
        await self._recv_data_lock[i].acquire()
        del self._recv_data_lock[i]
        resp = self._method_responses.pop(i)
        if 'result' in resp:
            result = resp['result']
            if expectedTypes is not None:
                return self._unpack_response(method, result)
            else:
                return result
        elif 'error' in resp:
            raise FailReponse(resp['error']['message'], resp['error']['code'])
        else:
            raise RuntimeError('Unknown data came: {0}'.format(resp))

    async def _handle_event(self, method, params):
        try:
            parameters, callback_name = self._unpack_event(method, params)
            if self._tabs is not None and self._tabs._callbacks is not None:
                callbacks = self._tabs._callbacks
                if hasattr(callbacks, callback_name):
                    await getattr(callbacks, callback_name)(self._tabs, self, **parameters)
                elif hasattr(callbacks, 'any'):
                    await callbacks.any(self._tabs, self, callback_name, parameters)
                else:
                    pass
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            traceback.print_exc()

    async def close(self):
        if self._soc is not None:
            await self._soc.close()
            self._soc = None
            requests.get('http://{0}:{1}/json/close/{2}'.format(self._host, self._port, self._tab_info['id']))

    async def remove(self):
        await self.close()
        if self._tabs is not None:
            self._tabs.remove(self)
            self._tabs = None




