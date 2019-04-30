import os
import sys
import getopt
import asyncio
import datetime
import functools
import collections.abc
import threading

import hexify

exe = os.path.basename(sys.argv[0])
usage_msg = f"""
Usage: {exe} -l listen_port -a host -p port [-c] [-b] [-h] [-?]

Options:
  -a host         - address/host to connect
  -p port         - remote port to connect
  -l listen_port  - local port to listen
  -c              - supress console output
  -b              - suppress binary logging
  -h              - supresss hexified data logging
  -?              - this help
  -v              - version
"""


def usage():
    print(usage_msg)
    sys.exit(1)


flag_remote_host = flag_remote_port = False
flag_listen_port = False

flag_log_binary = True
flag_log_hexify = True

try:
    opts, args = getopt.getopt(sys.argv[1:], "l:a:p:L:cbh?v")

    for opt, val in opts:
        if opt == "-l":
            flag_listen_port = int(val)
        elif opt == "-a":
            flag_remote_host = val
        elif opt == "-p":
            flag_remote_port = int(val)
        elif opt == "-c":
            flag_supress_console = False
        elif opt == "-b":
            flag_log_binary = False
        elif opt == "-h":
            flag_log_hexify = False
        elif opt == "-?":
            usage()
        elif opt == "-v":
            print(
                "Python TCP/IP Spy  Version 2.00  Copyright (c) 2019 by Alexander Demin"
            )
            sys.exit(1)
        else:
            usage()

    if not flag_listen_port:
        raise Exception("listen port is not given")

    if not flag_remote_host:
        raise Exception("remote host is not given")

    if not flag_remote_port:
        raise Exception("remote port is not given")

except Exception as e:
    print(f"error: {e}\n")
    usage()

connections_n = 0


def format_peer_info(peer):
    ip, port = peer.get_extra_info('peername')
    return f"{ip}({port})"


def now_prefix():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


async def transfer_logger(conn_n, from_writer_stream, to_writer_stream, queue):
    to_writer_info = format_peer_info(to_writer_stream)
    from_writer_info = format_peer_info(from_writer_stream)

    thread_id = threading.get_ident()

    now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_name = f"log-{now}-{conn_n:04}.{thread_id}-{from_writer_info}-{to_writer_info}.log"

    hexifier = hexify.Hexify(16)

    with open(log_name, 'w') as log:
        async for msg in queue:
            if isinstance(msg, str):
                log.write(msg)
                log.write('\n')
            elif isinstance(msg, list):
                bytes, offset = msg
                log.writelines(hexifier.hexify(bytes, offset))


async def transfer_raw_logger(conn_n, writer_stream, queue):
    now = datetime.datetime.now().strftime('%Y.%m.%d-%H-%M-%S')
    thread_id = threading.get_ident()
    log_name = f"log-raw-{now}-{conn_n:04}.{thread_id}-{format_peer_info(writer_stream)}.log"
    with open(log_name, 'wb') as log:
        async for msg in queue:
            log.write(msg)


async def stream_transfer(prefix, from_reader_stream, to_writer_stream,
                          logger_queue, raw_logger_queue,
                          transfer_completion_queue):
    global flag_log_hexify

    started = datetime.datetime.now()

    from_reader_info = format_peer_info(from_reader_stream._transport)
    to_writer_info = format_peer_info(to_writer_stream)

    direction_prefix = f"{from_reader_info} to {to_writer_info} {prefix}"

    async def log(msg):
        await logger_queue.put(f"{now_prefix()} {direction_prefix} {msg}")

    thread_id = threading.get_ident()
    await log(
        f"Transfer ({thread_id}) form {from_reader_info} to {to_writer_info} started"
    )

    offset = 0
    packet_n = 0

    try:
        async for bytes, n in from_reader_stream:
            await log(
                f"Received (packet {packet_n}, offset {offset}) {n} byte(s) from {from_reader_info}"
            )
            if flag_log_hexify:
                await logger_queue.put([bytes, offset])
            if raw_logger_queue:
                await raw_logger_queue.put(bytes)

            try:
                to_writer_stream.write(bytes)
            except Exception as e:
                await log(f"WRITE ERROR: {e}")
                break

            await log(f"Sent (packet {packet_n}) to {to_writer_info}")

            offset += n
            packet_n += 1
    except Exception as e:
        await log(f"READ ERROR: {e}")

    await log(f"Transfer is finished, reading is exhausted")

    to_writer_stream.close()
    await log(f"Closed writer stream to {to_writer_info}")

    duration = datetime.datetime.now() - started
    await transfer_completion_queue.put(
        f"{direction_prefix} Transfter task is finished, duration {duration}")


async def process_connection(local_reader, local_writer):
    global flag_log_binary
    global connections_n

    thread_id = threading.get_ident()

    current_connection_n, connections_n = connections_n, connections_n + 1

    local_reader_info = format_peer_info(local_reader._transport)
    local_writer_info = format_peer_info(local_writer)
    print(
        f"Accepted local connection #{current_connection_n}.{thread_id}: r={local_reader_info} w={local_writer_info}"
    )

    started = datetime.datetime.now()

    remote_host, remote_port = flag_remote_host, flag_remote_port

    print(
        f"Connecting #{current_connection_n}.{thread_id} to {remote_host}:{remote_port} at {started}"
    )

    remote_reader, remote_writer = await asyncio.open_connection(
        remote_host, remote_port)
    remote_reader_info = format_peer_info(remote_reader._transport)
    remote_writer_info = format_peer_info(remote_writer)
    print(
        f"Connected #{current_connection_n}.{thread_id} to {remote_host}:{remote_port}: r={remote_reader_info} w={remote_writer_info}"
    )

    logger_queue = asyncio.Queue()
    logger = asyncio.create_task(
        transfer_logger(current_connection_n, local_writer, remote_writer,
                        logger_queue))

    async def log(msg):
        await logger_queue.put(f"{now_prefix()} || {msg}")

    transfer_completion_queue = asyncio.Queue()

    remote_raw_logger_queue, local_raw_logger_queue = None, None
    remote_raw_logger, local_raw_logger = None, None
    if flag_log_binary:
        remote_raw_logger_queue = asyncio.Queue()
        local_raw_logger_queue = asyncio.Queue()
        remote_raw_logger = asyncio.create_task(
            transfer_raw_logger(current_connection_n, remote_writer,
                                remote_raw_logger_queue))
        local_raw_logger = asyncio.create_task(
            transfer_raw_logger(current_connection_n, local_writer,
                                local_raw_logger_queue))

    local_to_remote = asyncio.create_task(
        stream_transfer(">>", local_reader, remote_writer, logger_queue,
                        remote_raw_logger_queue, transfer_completion_queue))
    remote_to_local = asyncio.create_task(
        stream_transfer("<<", remote_reader, local_writer, logger_queue,
                        local_raw_logger_queue, transfer_completion_queue))

    try:
        await local_to_remote
        await log(
            f"Transfer from {local_reader_info} to {remote_writer_info} is awaited"
        )
    except Exception as e:
        await log(
            f"Transfer from {local_reader_info} to {remote_writer_info} FAILED {e}"
        )

    try:
        await remote_to_local
        await log(
            f"Transfer from {remote_reader_info} to {local_writer_info} is awaited"
        )
    except Exception as e:
        await log(
            f"Transfer from {remote_reader_info} to {local_writer_info} FAILED {e}"
        )

    ack = await transfer_completion_queue.get()
    await log(f"{ack}")

    ack = await transfer_completion_queue.get()
    await log(f"{ack}")

    async def wrapup_logger(queue, logger, logger_name, trace=True):
        prefix = f"Awaiting {logger_name}:"
        await log(f"{prefix} put 'None' to the queue")
        await queue.put(None)
        if trace:
            await log(f"{prefix} joining the queue")
        await queue.join()
        if trace:
            await log(f"{prefix} awaiting")
        await logger
        if trace:
            await log(f"{prefix} awaited")

    if remote_raw_logger_queue:
        await wrapup_logger(remote_raw_logger_queue, remote_raw_logger,
                            f"raw logger for {remote_writer_info}")

    if local_raw_logger_queue:
        await wrapup_logger(local_raw_logger_queue, local_raw_logger,
                            f"raw logger for {local_writer_info}")

    duration = datetime.datetime.now() - started
    final_msg = f"Finished connection #{current_connection_n}.{thread_id} from {remote_host}:{remote_port}, duration {duration}"

    await log(final_msg)

    await wrapup_logger(logger_queue, logger, f"hexify logger", False)

    print(final_msg)


async def main():
    server = await asyncio.start_server(process_connection, '0.0.0.0',
                                        flag_listen_port)

    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()


# Experimental monkey patching for async iterators.


async def asyncio_streamreader_fast_anext(self):
    val = await self.read(1024 * 1000)
    if val == b'':
        raise StopAsyncIteration
    return val, len(val)


def asyncio_queue_aiter(self):
    return self


async def asyncio_queue_anext(self):
    msg = await self.get()
    self.task_done()
    if msg is None:
        raise StopAsyncIteration
    return msg


asyncio.Queue.__aiter__ = asyncio_queue_aiter
asyncio.Queue.__anext__ = asyncio_queue_anext

asyncio.StreamReader.__anext__ = asyncio_streamreader_fast_anext

asyncio.run(main())
