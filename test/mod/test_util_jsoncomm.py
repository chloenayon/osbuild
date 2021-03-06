#
# Tests for the 'osbuild.util.jsoncomm' module.
#

import asyncio
import os
import tempfile
import unittest

from osbuild.util import jsoncomm


class TestUtilJsonComm(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.address = os.path.join(self.dir.name, "listener")
        self.server = jsoncomm.Socket.new_server(self.address)
        self.client = jsoncomm.Socket.new_client(self.address)

    def tearDown(self):
        self.client.close()
        self.server.close()
        self.dir.cleanup()

    def test_fdset(self):
        #
        # Test the FdSet implementation. Create a simple FD array and verify
        # that the FdSet correctly indexes them. Furthermore, verify that a
        # close actually closes the Fds so a following FdSet will get the same
        # FD numbers assigned.
        #

        v1 = [os.dup(0), os.dup(0), os.dup(0), os.dup(0)]
        s = jsoncomm.FdSet.from_list(v1)
        assert len(s) == 4
        for i in range(4):
            assert s[i] == v1[i]
        with self.assertRaises(IndexError):
            _ = s[128]
        s.close()

        v2 = [os.dup(0), os.dup(0), os.dup(0), os.dup(0)]
        assert v1 == v2
        s = jsoncomm.FdSet.from_list(v2)
        s.close()

    def test_fdset_init(self):
        #
        # Test FdSet initializations. This includes common edge-cases like empty
        # initializers, invalid array values, or invalid types.
        #

        s = jsoncomm.FdSet.from_list([])
        s.close()

        with self.assertRaises(ValueError):
            v1 = [-1]
            s = jsoncomm.FdSet.from_list(v1)

        with self.assertRaises(ValueError):
            v1 = ["foobar"]
            s = jsoncomm.FdSet(rawfds=v1)

    def test_ping_pong(self):
        #
        # Test sending messages through the client/server connection.
        #

        data = {"key": "value"}
        self.client.send(data)
        msg = self.server.recv()
        assert msg[0] == data
        assert len(msg[1]) == 0

        self.server.send(data, destination=msg[2])
        msg = self.client.recv()
        assert msg[0] == data
        assert len(msg[1]) == 0

    def test_scm_rights(self):
        #
        # Test FD transmission. Create a file, send a file-descriptor through
        # the communication channel, and then verify that the file-contents
        # can be read.
        #

        with tempfile.TemporaryFile() as f1:
            f1.write(b"foobar")
            f1.seek(0)

            self.client.send({}, fds=[f1.fileno()])

            msg = self.server.recv()
            assert msg[0] == {}
            assert len(msg[1]) == 1
            with os.fdopen(msg[1].steal(0)) as f2:
                assert f2.read() == "foobar"

    def test_listener_cleanup(self):
        #
        # Verify that only a single server can listen on a specified address.
        # Then make sure closing a server will correctly unlink its socket.
        #

        addr = os.path.join(self.dir.name, "foobar")
        srv1 = jsoncomm.Socket.new_server(addr)
        with self.assertRaises(OSError):
            srv2 = jsoncomm.Socket.new_server(addr)
        srv1.close()
        srv2 = jsoncomm.Socket.new_server(addr)
        srv2.close()

    def test_contextlib(self):
        #
        # Verify the context-manager of sockets. Make sure they correctly close
        # the socket, and they correctly propagate exceptions.
        #

        assert self.client.fileno() >= 0
        with self.client as client:
            assert client == self.client
            assert client.fileno() >= 0
        with self.assertRaises(AssertionError):
            self.client.fileno()

        assert self.server.fileno() >= 0
        with self.assertRaises(SystemError):
            with self.server as server:
                assert server.fileno() >= 0
                raise SystemError
            raise AssertionError
        with self.assertRaises(AssertionError):
            self.server.fileno()

    def test_asyncio(self):
        #
        # Test integration with asyncio-eventloops. Use a trivial echo server
        # and test a simple ping/pong roundtrip.
        #

        loop = asyncio.new_event_loop()

        def echo(socket):
            msg = socket.recv()
            socket.send(msg[0], destination=msg[2])
            loop.stop()

        self.client.send({})

        loop.add_reader(self.server, echo, self.server)
        loop.run_forever()
        loop.close()

        msg = self.client.recv()
        assert msg[0] == {}
