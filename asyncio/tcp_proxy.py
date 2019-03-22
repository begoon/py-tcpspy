import os
import sys
import getopt
import asyncio
import datetime
import functools
import logging

class Hexify:
    def __init__(self, width):
        self.padding = ''.rjust(19, '.')
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
        return "%s %06X: %-*s  %-*s" % (self.padding, self.offset, self.width*3, dump, self.width, char)
    
    def hexify(self, raw):
        self.reset()
        [(yield x) for x in self.header()]
        for chunk in self.chunks(raw):
            yield self.hexify_chunk(chunk)

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

flag_port = False
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
      elif opt == "-?":
         usage()
      elif opt == "-v":
         print("Python TCP/IP Spy  Version 2.00  Copyright (c) 2019 by Alexander Demin")
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

    now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_name = f"log-{now}-{conn_n:04}-{from_writer_info}-{to_writer_info}.log"

    with open(log_name, 'w') as log:
        while True:
            msg = await queue.get()
            if not msg:
                break
            print(msg, file=log)
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
    global flag_log_hexify

    started = datetime.datetime.now()

    from_reader_info = format_peer_info(from_reader_stream._transport)
    to_writer_info = format_peer_info(to_writer_stream)

    direction_prefix = f"{from_reader_info} to {to_writer_info} {prefix}"

    async def log(msg):
        await logger_queue.put(f"{now_prefix()} {direction_prefix} {msg}")

    await log(f"Transfer form {from_reader_info} to {to_writer_info} started")

    offset = 0
    packet_n = 0

    hexifier = Hexify(16)
    while True:
        try:
            bytes = await from_reader_stream.read(1024*1000)
            if not bytes:
                await log(f"Reader connection from {from_reader_info} to {to_writer_info} is closed by reader")
                break
            n = len(bytes)
            await log(f"Received (packet {packet_n}, offset {offset}) {n} byte(s) from {from_reader_info}")
            if flag_log_hexify:
                hexified = '\n'.join(hexifier.hexify(bytes))
                await logger_queue.put(hexified)
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
            break

    await log(f"Transfer is finished")

    to_writer_stream.close()
    await log(f"Closed writer stream to {to_writer_info}")

    duration = datetime.datetime.now() - started
    await transfer_completion_queue.put(f"{direction_prefix} Transfter task is finished, duration {duration}")

async def process_connection(local_reader, local_writer):
    global flag_log_binary
    global connections_n

    local_reader_info = format_peer_info(local_reader._transport)
    local_writer_info = format_peer_info(local_writer)
    print(f"Accepted local connection #{connections_n}: r={local_reader_info} w={local_writer_info}")

    started = datetime.datetime.now()

    remote_host, remote_port = flag_remote_host, flag_remote_port

    print(f"Connecting to {remote_host}:{remote_port} at {started}")

    remote_reader, remote_writer = await asyncio.open_connection(remote_host, remote_port)
    remote_reader_info = format_peer_info(remote_reader._transport)
    remote_writer_info = format_peer_info(remote_writer)
    print(f"Connected to {remote_host}:{remote_port}: r={remote_reader_info} w={remote_writer_info}")

    logger_queue = asyncio.Queue()
    logger = asyncio.create_task(transfer_logger(connections_n, local_writer, remote_writer, logger_queue))

    async def log(msg):
        await logger_queue.put(f"{now_prefix()} || {msg}")

    transfer_completion_queue = asyncio.Queue()

    remote_raw_logger_queue, local_raw_logger_queue = None, None
    remote_raw_logger, local_raw_logger = None, None
    if flag_log_binary:
        remote_raw_logger_queue = asyncio.Queue()
        local_raw_logger_queue = asyncio.Queue()
        remote_raw_logger = asyncio.create_task(transfer_raw_logger(connections_n, remote_writer, remote_raw_logger_queue))
        local_raw_logger = asyncio.create_task(transfer_raw_logger(connections_n, local_writer, local_raw_logger_queue))

    local_to_remote = asyncio.create_task(stream_transfer(">>", local_reader, remote_writer, logger_queue, remote_raw_logger_queue, transfer_completion_queue))
    remote_to_local = asyncio.create_task(stream_transfer("<<", remote_reader, local_writer, logger_queue, local_raw_logger_queue, transfer_completion_queue))

    try:
        await local_to_remote
        await log(f"Transfer from {local_reader_info} to {remote_writer_info} is awaited")
    except Exception as e:
        await log(f"Transfer from {local_reader_info} to {remote_writer_info} FAILED {e}")

    try:
        await remote_to_local
        await log(f"Transfer from {remote_reader_info} to {local_writer_info} is awaited")
    except Exception as e:
        await log(f"Transfer from {remote_reader_info} to {local_writer_info} FAILED {e}")

    for _ in range(2):
        ack = await transfer_completion_queue.get()
        await log(f"{ack}")

    if remote_raw_logger_queue:
        await remote_raw_logger_queue.put(None)
        await remote_raw_logger
        await log(f"Raw logger for {remote_writer_info} is awaited")

    if local_raw_logger_queue:
        await local_raw_logger_queue.put(None)
        await local_raw_logger
        await log(f"Raw logger for {local_writer_info} is awaited")

    duration = datetime.datetime.now() - started
    final_msg = f"Finished connection #{connections_n} from {remote_host}:{remote_port}, duration {duration}"

    await log(final_msg)
    await logger_queue.put(None)
    await logger

    print(final_msg)

    connections_n += 1

async def main():
    server = await asyncio.start_server(process_connection, '0.0.0.0', flag_listen_port)

    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()

asyncio.run(main())
