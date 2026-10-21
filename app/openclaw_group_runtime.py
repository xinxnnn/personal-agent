"""Supervise OpenClaw and its local ANP mailbox as one runtime process tree."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi import FastAPI
from app.octopus_group_runtime import attach

async def run():
    application=FastAPI()
    attach(application,None,os.environ['OCTOPUS_GROUP_FILE'],os.environ['OCTOPUS_INSTANCE_ID'])
    node=subprocess.Popen(sys.argv[2:],stdin=subprocess.DEVNULL,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    @application.get('/health')
    def health():return {'ready':node.poll() is None}
    server=uvicorn.Server(uvicorn.Config(application,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning'))
    async def monitor():
        while node.poll() is None and not server.should_exit:await asyncio.sleep(.5)
        server.should_exit=True
    task=asyncio.create_task(monitor())
    try:await server.serve()
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        if node.poll() is None:node.terminate()
        try:node.wait(timeout=5)
        except subprocess.TimeoutExpired:node.kill();node.wait(timeout=5)

if __name__=='__main__':asyncio.run(run())
