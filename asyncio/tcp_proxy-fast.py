import sys
import asyncio
import datetime
import functools

def printable(ch):
   if ch < 32 or ch > 127:
       return '.'
   return chr(ch)

printables = [printable(x) for x in range(256)]

async def log_dump(bytes, queue):
    width = 16
    header = functools.reduce(lambda x, y: x + ("%02X-" % y), range(width), "")[0:-1]
    lines = [
        f"------  {header}\n",
        f"        {'-' * width * 3}+\n",
    ]
    i = 0
    while True:
        line = bytes[i:i+width]
        if len(line) == 0: 
            break
        dump = functools.reduce(lambda x, y: x + ("%02X " % y), line, "")
        char = functools.reduce(lambda x, y: x + printables[y], line, "")
        lines.append("%06X: %-*s| %-*s\n" % (i, width*3, dump, width, char))
        i = i + width
    await queue.put("".join(lines))

connections_n = 0

def format_peer_info(peer):
    ip, port = peer.get_extra_info('peername')
    return f"{ip}({port})"

async def passthrough_raw_logger(conn_n, writer_stream, queue):
    now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_name = f"log-raw-{now}-{conn_n:04}-{format_peer_info(writer_stream)}.log"
    await passthrough_logger_loop(queue, log_name, 'b')

async def passthrough_logger(conn_n, from_writer_stream, to_writer_stream, queue):
    now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_name = f"log-{now}-{conn_n:04}-{from_writer_stream.get_extra_info('peername')}-{to_writer_stream.get_extra_info('peername')}.log"
    await passthrough_logger_loop(queue, log_name)

async def passthrough_logger_loop(queue, log_name, binary=""):
    with open(log_name, f'w{binary}') as log:
        while True:
            bytes = await queue.get()
            if not bytes:
                break
            log.write(bytes)
            log.flush()
            queue.task_done()

async def stream_passthrough(prefix, from_reader_stream, to_writer_stream, logger_queue, raw_logger_queue, control_queue):
    await logger_queue.put(f"{prefix} Passthrough to {to_writer_stream.get_extra_info('peername')} started\n")

    offset = 0
    packet_n = 0

    write_exception = False

    while True:
        try:
            bytes = await from_reader_stream.read(1024*1000)
            if not bytes:
                await logger_queue.put(f"{prefix} Reader connection is closed by remote peer {to_writer_stream.get_extra_info('peername')}\n")
                break
            n = len(bytes)
            await logger_queue.put(f"{prefix} Received ({packet_n}, {offset}) {n} byte(s) from {from_reader_stream._transport.get_extra_info('peername')}\n")
            await log_dump(bytes, logger_queue)
            await raw_logger_queue.put(bytes)

            try:
                to_writer_stream.write(bytes)
            except Exception as e:
                write_exception = True
                await logger_queue.put(f"{prefix} WRITE ERROR: {e}\n")
                break
                
            await logger_queue.put(f"{prefix} Sent ({packet_n}) to {to_writer_stream.get_extra_info('peername')}\n")

            offset += n
            packet_n += 1
        except Exception as e:
            await logger_queue.put(f"READ ERROR: {e}\n")
            break

    await logger_queue.put(f"{prefix} Passthrough to {to_writer_stream.get_extra_info('peername')} transfer finished\n")

    if not write_exception:
        await logger_queue.put(f"{prefix} Draining remote connection to {to_writer_stream.get_extra_info('peername')}\n")
        await to_writer_stream.drain()
        await logger_queue.put(f"{prefix} Closing remote connection to {to_writer_stream.get_extra_info('peername')}\n")
        to_writer_stream.close()
        await logger_queue.put(f"{prefix} Wait to close the remote connection to {to_writer_stream.get_extra_info('peername')}\n")
        await to_writer_stream.wait_closed()

    await logger_queue.put(f"{prefix} Closed remote connection to {to_writer_stream.get_extra_info('peername')}\n")

    await control_queue.put(f"Passthrough to {to_writer_stream.get_extra_info('peername')} task finished")

async def process_connection(local_reader, local_writer):
    global connections_n

    local_reader_info = format_peer_info(local_reader._transport)
    local_writer_info = format_peer_info(local_writer)
    print(f"Accepted local connection #{connections_n}: r={local_reader_info} w={local_writer_info}")

    remote_host = 'speedtest.tele2.net'
    remote_port = 21

    remote_host = "ipv4.download.thinkbroadband.com"
    remote_port = 80
    print(f"Connecting to {remote_host}:{remote_port}")

    remote_reader, remote_writer = await asyncio.open_connection(remote_host, remote_port)
    remote_reader_info = format_peer_info(remote_reader._transport)
    remote_writer_info = format_peer_info(remote_writer)
    print(f"Connected to {remote_host}:{remote_port}: r={remote_reader_info} w={remote_writer_info}")

    control_queue = asyncio.Queue()
    logger_queue = asyncio.Queue()
    remote_raw_logger_queue = asyncio.Queue()
    local_raw_logger_queue = asyncio.Queue()

    logger = asyncio.create_task(passthrough_logger(connections_n, local_writer, remote_writer, logger_queue))
    remote_raw_logger = asyncio.create_task(passthrough_raw_logger(connections_n, remote_writer, remote_raw_logger_queue))
    local_raw_logger = asyncio.create_task(passthrough_raw_logger(connections_n, local_writer, local_raw_logger_queue))

    local_to_remote = asyncio.create_task(stream_passthrough(">>>", local_reader, remote_writer, logger_queue, remote_raw_logger_queue, control_queue))
    remote_to_local = asyncio.create_task(stream_passthrough("<<<", remote_reader, local_writer, logger_queue, local_raw_logger_queue, control_queue))

    try:
        await local_to_remote
        await logger_queue.put(f"Local -> Remote transfer is awaited\n")
    except Exception as e:
        await logger_queue.put(f"{e}\n")
        await logger_queue.put(f"Local -> Remote transfer FAILED\n")

    try:
        await remote_to_local
        await logger_queue.put(f"Remote -> Local transfer is awaited\n")
    except Exception as e:
        await logger_queue.put(f"{e}\n")
        await logger_queue.put(f"Remote -> Local transfer FAILED\n")

    for _ in range(2):
        ack = await control_queue.get()
        await logger_queue.put(f"{ack}\n")

    await remote_raw_logger_queue.put(None)
    await remote_raw_logger
    await logger_queue.put(f"Remote -> Local raw logger is awaited\n")

    await local_raw_logger_queue.put(None)
    await local_raw_logger
    await logger_queue.put(f"Local -> Remote raw logger is awaited\n")

    await logger_queue.put(None)
    await logger

    print(f"Finished connection #{connections_n} from {remote_host}:{remote_port}: r={local_reader_info} w={local_writer_info}")

    connections_n += 1

async def main():
    server = await asyncio.start_server(process_connection, '127.0.0.1', 8888)

    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()

asyncio.run(main())
