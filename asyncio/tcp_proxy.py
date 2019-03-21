import sys
import asyncio
import datetime
import functools
import logging

def create_logger(name):
    formatter = logging.Formatter(fmt='%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = logging.FileHandler(name, mode='w')
    file_handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.addHandler(file_handler)
    logger.setLevel(logging.DEBUG)
    logger.flush = logger.handlers[0].flush
    return logger

class Hexify:
    def __init__(self, width):
        self.printables = [self.printable(x) for x in range(256)]
        self.width = width

    def printable(self, ch):
       if ch < 32 or ch > 127:
           return '.'
       return chr(ch)

    def header(self):
        yield f"######  {'.'.join(map(lambda x: '%02X' % x, range(self.width)))}"
        yield f"------  {''.ljust(self.width*3-1, '-')}"

    def reset(self):
        self.offset = -self.width

    def chunks(self, raw):
        for i in range(0, len(raw), self.width):
            yield raw[i:i + self.width]

    def hexify_chunk(self, chunk):
        dump = " ".join(map(lambda x: f"{x:02X}", chunk))
        char = "".join(map(lambda x: self.printables[x], chunk))
        self.offset += self.width
        return "%06X: %-*s  %-*s" % (self.offset, self.width*3, dump, self.width, char)
    
    async def hexify(self, raw, cb):
        self.reset()
        [await cb(x) for x in self.header()]
        for chunk in self.chunks(raw):
            await cb(self.hexify_chunk(chunk))

connections_n = 0
log_binary = False

def format_peer_info(peer):
    ip, port = peer.get_extra_info('peername')
    return f"{ip}({port})"

async def transfer_logger(conn_n, from_writer_stream, to_writer_stream, queue):
    to_writer_info = format_peer_info(to_writer_stream)
    from_writer_info = format_peer_info(from_writer_stream)

    now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_name = f"log-{now}-{conn_n:04}-{from_writer_info}-{to_writer_info}.log"
    log = create_logger(log_name)
    while True:
        msg = await queue.get()
        if not msg:
            break
        log.info(msg)
        log.flush()
        queue.task_done()

async def transfer_raw_logger(conn_n, writer_stream, queue):
    now = datetime.datetime.now().strftime('%Y.%m.%d-%H-%M-%S')
    log_name = f"log-raw-{now}-{conn_n:04}-{format_peer_info(writer_stream)}.log"
    with open(log_name, 'wb') as log:
        while True:
            bytes = await queue.get()
            if not bytes:
                break
            log.write(bytes)
            log.flush()
            queue.task_done()

async def stream_transfer(prefix, from_reader_stream, to_writer_stream, logger_queue, raw_logger_queue, transfer_completion_queue):
    from_reader_info = format_peer_info(from_reader_stream._transport)
    to_writer_info = format_peer_info(to_writer_stream)

    await logger_queue.put(f"{prefix} Transfer to {to_writer_info} started")

    offset = 0
    packet_n = 0

    write_exception = False

    hexifier = Hexify(16)
    while True:
        try:
            bytes = await from_reader_stream.read(1024*1000)
            if not bytes:
                await logger_queue.put(f"{prefix} Reader connection is closed by remote peer {to_writer_info}")
                break
            n = len(bytes)
            await logger_queue.put(f"{prefix} Received ({packet_n}, {offset}) {n} byte(s) from {from_reader_info}")
            await hexifier.hexify(bytes, logger_queue.put)
            if raw_logger_queue:
                await raw_logger_queue.put(bytes)

            try:
                to_writer_stream.write(bytes)
            except Exception as e:
                write_exception = True
                await logger_queue.put(f"{prefix} WRITE ERROR: {e}")
                break
                
            await logger_queue.put(f"{prefix} Sent ({packet_n}) to {to_writer_info}")

            offset += n
            packet_n += 1
        except Exception as e:
            await logger_queue.put(f"READ ERROR: {e}")
            break

    await logger_queue.put(f"{prefix} Transfer to {to_writer_info} is finished")

    if not write_exception:
        await logger_queue.put(f"{prefix} Draining remote connection to {to_writer_info}")
        await to_writer_stream.drain()
        await logger_queue.put(f"{prefix} Closing remote connection to {to_writer_info}")
        to_writer_stream.close()
        await logger_queue.put(f"{prefix} Waiting to close the remote connection to {to_writer_info}")
        await to_writer_stream.wait_closed()

    await logger_queue.put(f"{prefix} Closed remote connection to {to_writer_info}")

    await transfer_completion_queue.put(f"Transfter to {to_writer_stream.get_extra_info('peername')} task is finished")

async def process_connection(local_reader, local_writer):
    global log_binary
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

    logger_queue = asyncio.Queue()

    logger = asyncio.create_task(transfer_logger(connections_n, local_writer, remote_writer, logger_queue))

    transfer_completion_queue = asyncio.Queue()

    remote_raw_logger_queue, local_raw_logger_queue = None, None
    remote_raw_logger, local_raw_logger = None, None
    if log_binary:
        remote_raw_logger_queue = asyncio.Queue()
        local_raw_logger_queue = asyncio.Queue()
        remote_raw_logger = asyncio.create_task(transfer_raw_logger(connections_n, remote_writer, remote_raw_logger_queue))
        local_raw_logger = asyncio.create_task(transfer_raw_logger(connections_n, local_writer, local_raw_logger_queue))

    local_to_remote = asyncio.create_task(stream_transfer(">>>", local_reader, remote_writer, logger_queue, remote_raw_logger_queue, transfer_completion_queue))
    remote_to_local = asyncio.create_task(stream_transfer("<<<", remote_reader, local_writer, logger_queue, local_raw_logger_queue, transfer_completion_queue))

    try:
        await local_to_remote
        await logger_queue.put(f"||| Local -> Remote transfer is awaited")
    except Exception as e:
        await logger_queue.put(f"||| {e}")
        await logger_queue.put(f"||| Local -> Remote transfer FAILED")

    try:
        await remote_to_local
        await logger_queue.put(f"||| Remote -> Local transfer is awaited")
    except Exception as e:
        await logger_queue.put(f"||| {e}")
        await logger_queue.put(f"||| Remote -> Local transfer FAILED")

    for _ in range(2):
        ack = await transfer_completion_queue.get()
        await logger_queue.put(f"||| {ack}")

    if remote_raw_logger_queue:
        await remote_raw_logger_queue.put(None)
        await remote_raw_logger
        await logger_queue.put(f"||| Remote -> Local raw logger is awaited")

    if local_raw_logger_queue:
        await local_raw_logger_queue.put(None)
        await local_raw_logger
        await logger_queue.put(f"||| Local -> Remote raw logger is awaited")

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
