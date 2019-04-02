#!/usr/bin/python
"""
Transparent multithreaded TCP/IP logger.

Copyright (GPL) 2009 Alexander Demin, <alexander@demin.ws>

This file is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.

You can redistribute this file and/or modify it under the terms of the GNU
General Public License (GPL) as published by the Free Software Foundation;
either version 2 of the License, or (at your discretion) any later version.
See the accompanying file "COPYING.txt" for more details.
"""

import socket, string, threading, os, select, sys, time, getopt
from sys import argv

def usage():
   name = os.path.basename(argv[0])
   print "usage:", name, "-l listen_port -a host -p port [-L file] [-c] [-h?]"
   print "	-a host         - address/host to connect"
   print "	-p port         - remote port to connect"
   print "	-l listen_port  - local port to listen"
   print "	-L file         - log file"
   print "	-c              - supress console output"
   print "	-h or -?        - this help"
   print "	-v              - version"
   sys.exit(1)

PORT = False
REMOTE_HOST = REMOTE_PORT = False

CONSOLE = True
LOGFILE = False

try:
   opts, args = getopt.getopt(argv[1:], "l:a:p:L:ch?v")

   for opt in opts:
      opt, val = opt
      if opt == "-l":
         PORT = int(val)
      elif opt == "-a":
         REMOTE_HOST = val
      elif opt == "-p":
         REMOTE_PORT = int(val)
      elif opt == "-L":
         LOGFILE = val
      elif opt == "-c":
         CONSOLE = False
      elif opt == "-?" or opt == "-h":
         usage()
      elif opt == "-v":
         print "Python TCP/IP Spy  Version 1.01  Copyright (c) 2009 by Alexander Demin"
         sys.exit(1)
      else:
         usage()

   if not PORT:
      raise StandardError, "listen port is not given"

   if not REMOTE_HOST:
      raise StandardError, "remote host is not given"

   if not REMOTE_PORT:
      raise StandardError, "remote port is not given"

except Exception, e:
   print "error:", e, "\n"
   usage()

# Remote host
REMOTE = (REMOTE_HOST, REMOTE_PORT)

# Create logging contitional variable
log_cond = threading.Condition()

queue = []

def logger():
   global queue
   while 1:
      log_cond.acquire()

      while len(queue) == 0:
         log_cond.wait()

      if LOGFILE:
         try:
            logfile = open(LOGFILE, "a+")
            logfile.writelines(map(lambda x: x+"\n", queue))
            logfile.close()
         except: pass
     
      if CONSOLE:
         for line in queue:
            print line
      
      queue = []
      log_cond.release()

# Thread safe logger
def log(thread, msg):
   if CONSOLE or LOGFILE:
      log_cond.acquire()
      queue.append("%04d: %s" % (thread, msg))
      log_cond.notify()
      log_cond.release()

def printable(ch):
   return (int(ch < 32) and '.') or (int(ch >= 32) and chr(ch))

# Pre-build a printable characters map
printable_map = [ printable(x) for x in range(256) ]

# Thread safe dumper
def log_dump(thread, msg):

   if CONSOLE or LOGFILE:
      log_cond.acquire()

      width = 16

      header = reduce(lambda x, y: x + ("%02X-" % y), range(width), "")[0:-1]
      queue.append("%04d: ----: %s" % (thread, header))
      queue.append("%04d:       %s" % (thread, '-' * width * 3))

      i = 0
      while 1:
         line = msg[i:i+width]
         if len(line) == 0: break
         dump = reduce(lambda x, y: x + ("%02X " % ord(y)), line, "")
         char = reduce(lambda x, y: x + printable_map[ord(y)], line, "")
         queue.append("%04X: %04X: %-*s| %-*s" % (thread, i, width*3, dump, width, char))
         i = i + width

      log_cond.notify()
      log_cond.release()

# Spy thread
def spy_thread(local, addr, thread_id):
   log(thread_id, "Thread started")

   try:
      log(thread_id, "Connecting to %s..." % str(REMOTE))
      remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      remote.connect(REMOTE)
   except Exception, e:
      log(thread_id, "Unable connect to %s -> %s" % (REMOTE, e))
      local.close()
      return

   LOCAL = str(addr)

   log(thread_id, "Remote host: " + LOCAL)

   try:
      running = 1;
      while running == 1: 

         rd, wr, er = select.select([local, remote], [], [local, remote], 3600)

         for sock in er:
            if sock == local:
               log(thread_id, "Connection error from " + LOCAL)
               running = 0
            if sock == remote:
               log(thread_id, "Connection error from " + REMOTE)
               running = 0

         for sock in rd:
            if sock == local:
               val = local.recv(1024)
               if val: 
                  log(thread_id, "Recevied from %s (%d)" % (LOCAL, len(val)))
                  log_dump(thread_id, val)
                  remote.send(val)
                  log(thread_id, "Sent to %s (%d)" % (REMOTE, len(val)))
               else:
                  log(thread_id, "Connection reset by %s" % LOCAL)
                  running = 0;

            if sock == remote:
               val = remote.recv(1024)
               if val: 
                  log(thread_id, "Recevied from %s (%d)" % (REMOTE, len(val)))
                  log_dump(thread_id, val)
                  local.send(val)
                  log(thread_id, "Sent to %s (%d)" % (LOCAL, len(val)))
               else:
                  log(thread_id, "Connection reset by %s" % str(REMOTE))
                  running = 0;

   except Exception, e:
      log(thread_id, ("Connection terminated: " + str(e)))

   remote.close()
   local.close()

   log(thread_id, "Connection closed")

try:
   # Server socket
   srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
   srv.bind(("", PORT)) 
except Exception, e:
   print "error", e
   sys.exit(1)

counter = 1

threading.Thread(target=logger, args=[]).start()

log(0, "Listen at port %d, remote host %s" % (PORT, REMOTE))
 
while 1: 
   srv.listen(1)              
   local, addr = srv.accept()
   log(0, "Connection accepted from %s, thread %d launched" % (addr, counter))
   threading.Thread(target=spy_thread, args=[local, addr, counter]).start()
   counter = counter + 1
