import pytest
import six
import struct

import asyncio
import consul
import consul.aio


@pytest.fixture
def loop():
    asyncio.set_event_loop(None)
    loop = asyncio.new_event_loop()
    return loop


class TestAsyncioConsul(object):

    def test_kv(self, loop, consul_port):

        @asyncio.coroutine
        def main():
            c = consul.aio.Consul(port=consul_port, loop=loop)
            print(c)
            index, data = yield from c.kv.get('foo')

            print(index, data)
            assert data is None
            response = yield from c.kv.put('foo', 'bar')
            assert response is True
            index, data = yield from c.kv.get('foo')
            assert data['Value'] == six.b('bar')

        loop.run_until_complete(main())

    def test_consul_ctor(self, loop, consul_port):
        # same as previous but with global event loop
        @asyncio.coroutine
        def main():
            c = consul.aio.Consul(port=consul_port)
            assert c._loop is loop
            yield from c.kv.put('foo', struct.pack('i', 1000))
            index, data = yield from c.kv.get('foo')
            assert struct.unpack('i', data['Value']) == (1000,)

        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())

    def test_kv_binary(self, loop, consul_port):
        @asyncio.coroutine
        def main():
            c = consul.aio.Consul(port=consul_port, loop=loop)
            yield from c.kv.put('foo', struct.pack('i', 1000))
            index, data = yield from c.kv.get('foo')
            assert struct.unpack('i', data['Value']) == (1000,)

        loop.run_until_complete(main())

    def test_kv_missing(self, loop, consul_port):
        c = consul.aio.Consul(port=consul_port, loop=loop)

        @asyncio.coroutine
        def main():
            fut = asyncio.async(put(), loop=loop)
            yield from c.kv.put('index', 'bump')
            index, data = yield from c.kv.get('foo')
            assert data is None
            index, data = yield from c.kv.get('foo', index=index)
            assert data['Value'] == six.b('bar')
            yield from fut

        @asyncio.coroutine
        def put():
            yield from asyncio.sleep(2.0/100, loop=loop)
            yield from c.kv.put('foo', 'bar')

        loop.run_until_complete(main())

    def test_kv_put_flags(self, loop, consul_port):
        @asyncio.coroutine
        def main():
            c = consul.aio.Consul(port=consul_port, loop=loop)
            yield from c.kv.put('foo', 'bar')
            index, data = yield from c.kv.get('foo')
            assert data['Flags'] == 0

            response = yield from c.kv.put('foo', 'bar', flags=50)
            assert response is True
            index, data = yield from c.kv.get('foo')
            assert data['Flags'] == 50

        loop.run_until_complete(main())

    def test_kv_delete(self, loop, consul_port):
        @asyncio.coroutine
        def main():
            c = consul.aio.Consul(port=consul_port, loop=loop)
            yield from c.kv.put('foo1', '1')
            yield from c.kv.put('foo2', '2')
            yield from c.kv.put('foo3', '3')
            index, data = yield from c.kv.get('foo', recurse=True)
            assert [x['Key'] for x in data] == ['foo1', 'foo2', 'foo3']

            response = yield from c.kv.delete('foo2')
            assert response is True
            index, data = yield from c.kv.get('foo', recurse=True)
            assert [x['Key'] for x in data] == ['foo1', 'foo3']
            response = yield from c.kv.delete('foo', recurse=True)
            assert response is True
            index, data = yield from c.kv.get('foo', recurse=True)
            assert data is None

        loop.run_until_complete(main())

    def test_kv_subscribe(self, loop, consul_port):
        c = consul.aio.Consul(port=consul_port, loop=loop)

        @asyncio.coroutine
        def get():
            fut = asyncio.async(put(), loop=loop)
            index, data = yield from c.kv.get('foo')
            assert data is None
            index, data = yield from c.kv.get('foo', index=index)
            assert data['Value'] == six.b('bar')
            yield from fut

        @asyncio.coroutine
        def put():
            yield from asyncio.sleep(1.0/100, loop=loop)
            response = yield from c.kv.put('foo', 'bar')
            assert response is True

        loop.run_until_complete(get())

    def test_agent_services(self, loop, consul_port):
        @asyncio.coroutine
        def main():
            c = consul.aio.Consul(port=consul_port, loop=loop)
            services = yield from c.agent.services()
            del services['consul']
            assert services == {}
            response = yield from c.agent.service.register('foo')
            assert response is True
            services = yield from c.agent.services()
            del services['consul']
            assert services == {
                'foo': {
                    'Port': 0,
                    'ID': 'foo',
                    'Service': 'foo',
                    'Tags': None,
                    'Address': ''}, }
            response = yield from c.agent.service.deregister('foo')
            assert response is True
            services = yield from c.agent.services()
            del services['consul']
            assert services == {}
        loop.run_until_complete(main())

    def test_catalog(self, loop, consul_port):
        c = consul.aio.Consul(port=consul_port, loop=loop)

        @asyncio.coroutine
        def nodes():
            fut = asyncio.async(register(), loop=loop)
            index, nodes = yield from c.catalog.nodes()
            assert len(nodes) == 1
            current = nodes[0]

            index, nodes = yield from c.catalog.nodes(index=index)
            nodes.remove(current)
            assert [x['Node'] for x in nodes] == ['n1']

            index, nodes = yield from c.catalog.nodes(index=index)
            nodes.remove(current)
            assert [x['Node'] for x in nodes] == []
            yield from fut

        @asyncio.coroutine
        def register():
            yield from asyncio.sleep(1.0/100, loop=loop)
            response = yield from c.catalog.register('n1', '10.1.10.11')
            assert response is True
            yield from asyncio.sleep(50/1000.0, loop=loop)
            response = yield from c.catalog.deregister('n1')
            assert response is True

        loop.run_until_complete(nodes())

    def test_health_service(self, loop, consul_port):
        @asyncio.coroutine
        def main():
            c = consul.aio.Consul(port=consul_port, loop=loop)

            # check there are no nodes for the service 'foo'
            index, nodes = yield from c.health.service('foo')
            assert nodes == []

            # register two nodes, one with a long ttl, the other shorter
            yield from c.agent.service.register(
                'foo', service_id='foo:1', ttl='10s')
            yield from c.agent.service.register(
                'foo', service_id='foo:2', ttl='100ms')

            yield from asyncio.sleep(30/1000.0, loop=loop)

            # check the nodes show for the /health/service endpoint
            index, nodes = yield from c.health.service('foo')
            assert [node['Service']['ID'] for node in nodes] == \
                ['foo:1', 'foo:2']

            # but that they aren't passing their health check
            index, nodes = yield from c.health.service('foo', passing=True)
            assert nodes == []

            # ping the two node's health check
            yield from c.health.check.ttl_pass('service:foo:1')
            yield from c.health.check.ttl_pass('service:foo:2')

            yield from asyncio.sleep(50/1000.0, loop=loop)

            # both nodes are now available
            index, nodes = yield from c.health.service('foo', passing=True)
            assert [node['Service']['ID'] for node in nodes] == \
                ['foo:1', 'foo:2']

            # wait until the short ttl node fails
            yield from asyncio.sleep(120/1000.0, loop=loop)

            # only one node available
            index, nodes = yield from c.health.service('foo', passing=True)
            assert [node['Service']['ID'] for node in nodes] == ['foo:1']

            # ping the failed node's health check
            yield from c.health.check.ttl_pass('service:foo:2')

            yield from asyncio.sleep(30/1000.0, loop=loop)

            # check both nodes are available
            index, nodes = yield from c.health.service('foo', passing=True)
            assert [node['Service']['ID'] for node in nodes] == \
                ['foo:1', 'foo:2']

            # deregister the nodes
            yield from c.agent.service.deregister('foo:1')
            yield from c.agent.service.deregister('foo:2')

            yield from asyncio.sleep(30/1000.0, loop=loop)

            index, nodes = yield from c.health.service('foo')
            assert nodes == []

        loop.run_until_complete(main())

    def test_health_service_subscribe(self, loop, consul_port):
        c = consul.aio.Consul(port=consul_port, loop=loop)

        class Config(object):
            pass

        config = Config()

        @asyncio.coroutine
        def monitor():
            yield from c.agent.service.register(
                'foo', service_id='foo:1', ttl='40ms')
            index = None
            while True:
                index, nodes = yield from c.health.service(
                    'foo', index=index, passing=True)
                config.nodes = [node['Service']['ID'] for node in nodes]

        @asyncio.coroutine
        def keepalive():
            # run monitor as background task
            fut = asyncio.async(monitor(), loop=loop)
            # give the monitor a chance to register the service
            yield from asyncio.sleep(50/1000.0, loop=loop)
            assert config.nodes == []

            # ping the service's health check
            yield from c.health.check.ttl_pass('service:foo:1')
            yield from asyncio.sleep(30/1000.0, loop=loop)
            assert config.nodes == ['foo:1']

            # the service should fail
            yield from asyncio.sleep(60/1000.0, loop=loop)
            assert config.nodes == []

            yield from c.agent.service.deregister('foo:1')
            # all done kill background task
            fut.cancel()

        loop.run_until_complete(keepalive())

    def test_agent_register_check_no_service_id(self, loop, consul_port):
        @asyncio.coroutine
        def main():
            c = consul.aio.Consul(port=consul_port, loop=loop)
            index, nodes = yield from c.health.service("foo1")
            assert nodes == []

            result = yield from c.agent.check.register(
                'foo', service_id='foo1', ttl="100ms")
            assert result is False

        loop.run_until_complete(main())

    def test_session(self, loop, consul_port):
        c = consul.aio.Consul(port=consul_port, loop=loop)

        @asyncio.coroutine
        def monitor():
            fut = asyncio.async(register(), loop=loop)
            index, services = yield from c.session.list()
            assert services == []
            yield from asyncio.sleep(20/1000.0, loop=loop)

            index, services = yield from c.session.list(index=index)
            assert len(services)

            index, services = yield from c.session.list(index=index)
            assert services == []
            yield from fut

        @asyncio.coroutine
        def register():
            yield from asyncio.sleep(1.0/100, loop=loop)
            session_id = yield from c.session.create()
            yield from asyncio.sleep(50/1000.0, loop=loop)
            response = yield from c.session.destroy(session_id)
            assert response is True

        loop.run_until_complete(monitor())

    def test_acl(self, loop, acl_consul):
        @asyncio.coroutine
        def main():
            c = consul.aio.Consul(
                port=acl_consul.port, token=acl_consul.token, loop=loop)

            rules = """
                key "" {
                    policy = "read"
                }
                key "private/" {
                    policy = "deny"
                }
            """
            token = yield from c.acl.create(rules=rules)

            try:
                yield from c.acl.list(token=token)
            except consul.ACLPermissionDenied:
                raised = True
            assert raised

            destroyed = yield from c.acl.destroy(token)
            assert destroyed is True

        loop.run_until_complete(main())
