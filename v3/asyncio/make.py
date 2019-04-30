import os
import sys
import subprocess

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
    
def usage():
    [print(cmd) for cmd in globals() if cmd.endswith('_f')]

for cmd in sys.argv[1:]:
    print(cmd)
    globals()[f"{cmd}_f"]()
else:
    usage()
