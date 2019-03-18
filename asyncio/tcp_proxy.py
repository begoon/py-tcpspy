import asyncio
import datetime
import functools

def printable(ch):
   return (int(ch < 32) and '.') or (int(ch >= 32) and chr(ch))

printables = [printable(x) for x in range(256)]

async def log_dump(bytes, queue):
    width = 16
    header = functools.reduce(lambda x, y: x + ("%02X-" % y), range(width), "")[0:-1]
    await queue.put(f"      {header}\n")
    await queue.put(f"      %s\n" % ('-' * width * 3))

    i = 0
    while True:
        line = bytes[i:i+width]
        if len(line) == 0: 
            break
        dump = functools.reduce(lambda x, y: x + ("%02X " % y), line, "")
        char = functools.reduce(lambda x, y: x + printables[y], line, "")
        await queue.put("%04X: %-*s| %-*s\n" % (i, width*3, dump, width, char))
        i = i + width

connections_n = 0

async def process_connection(local_reader, local_writer):
    global connections_n

    print(f"Accepted local connection #{connections_n}: r={local_reader._transport.get_extra_info('peername')} w={local_writer.get_extra_info('peername')}")

    remote_host = 'speedtest.tele2.net'
    remote_port = 21
    print(f"Connecting to {remote_host}:{remote_port}")

    remote_reader, remote_writer = await asyncio.open_connection(remote_host, remote_port)
    print(f"Connected to {remote_host}:{remote_port}: r={remote_reader._transport.get_extra_info('peername')} w={remote_writer.get_extra_info('peername')}")

    async def passthrough_raw_logger(conn_n, writer_stream, queue):
        now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        log_name = f"log-raw-{now}-{conn_n:04}-{writer_stream.get_extra_info('peername')}.log"
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

    async def stream_passthrough(from_reader_stream, to_writer_stream, logger_queue, raw_logger_queue, control_queue):
        await logger_queue.put(f"Passthrough to {to_writer_stream.get_extra_info('peername')} started\n")

        offset = 0
        packet_n = 0

        while True:
            bytes = await from_reader_stream.read(10240)
            if not bytes:
                await logger_queue.put(f"Reader connection is closed by remote peer {to_writer_stream.get_extra_info('peername')}\n")
                break
            n = len(bytes)
            await logger_queue.put(f"Received ({packet_n}, {offset}) {n} byte(s) from {from_reader_stream._transport.get_extra_info('peername')}\n")
            await log_dump(bytes, logger_queue)
            await raw_logger_queue.put(bytes)

            to_writer_stream.write(bytes)
            await logger_queue.put(f"Sent ({packet_n}) to {to_writer_stream.get_extra_info('peername')}\n")

            offset += n
            packet_n += 1

        await logger_queue.put(f"Passthrough to {to_writer_stream.get_extra_info('peername')} finished\n")

        await to_writer_stream.drain()
        to_writer_stream.close()
        await logger_queue.put(f"Closing remote connection to {to_writer_stream.get_extra_info('peername')}\n")
        await to_writer_stream.wait_closed()
        await logger_queue.put(f"Closed remote connection to {to_writer_stream.get_extra_info('peername')}\n")

        await control_queue.put(None)

    control_queue = asyncio.Queue()
    logger_queue = asyncio.Queue()
    remote_raw_logger_queue = asyncio.Queue()
    local_raw_logger_queue = asyncio.Queue()

    await asyncio.gather(
        passthrough_logger(connections_n, local_writer, remote_writer, logger_queue), 
        passthrough_raw_logger(connections_n, remote_writer, remote_raw_logger_queue), 
        passthrough_raw_logger(connections_n, local_writer, local_raw_logger_queue), 

        stream_passthrough(local_reader, remote_writer, logger_queue, remote_raw_logger_queue, control_queue), 
        stream_passthrough(remote_reader, local_writer, logger_queue, local_raw_logger_queue, control_queue)
    )

    await control_queue.get()
    await control_queue.get()

    await remote_raw_logger_queue.put(None)
    await local_raw_logger_queue.put(None)
    await logger_queue.put(None)

    connections_n += 1

    print(f"Finished connection #{connections_n} from {remote_host}:{remote_port}: r={remote_reader._transport.get_extra_info('peername')} w={remote_writer.get_extra_info('peername')}")

async def main():
    server = await asyncio.start_server(process_connection, '127.0.0.1', 8888)

    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()

asyncio.run(main())
