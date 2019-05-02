import os
import sys
import subprocess
import datetime

def run(cmd: str):
    print(f"@ {cmd}")
    subprocess.call(cmd, shell=True)

def python(script: str):
    run(f"{sys.executable} {script}")

def build_f(): pass

def test_f():
    run('pytest -v')

def all_f(): 
    build_f()
    test_f()

def curl50_f():
    run('curl --output /dev/null http://127.0.0.1:8888/50MB.zip')
    
def usage():
    [print(cmd) for cmd in globals() if cmd.endswith('_f')]

for cmd in sys.argv[1:]:
    started = datetime.datetime.now()
    print(cmd)
    globals()[f"{cmd}_f"]()
    print(">", f"{datetime.datetime.now() - started}")

if len(sys.argv) < 2:
    usage()
