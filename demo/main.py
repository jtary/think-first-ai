import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import httpx
from typing import Dict, Set

app = FastAPI()

# Store active WebSocket connections
thoughts_connections: Set[WebSocket] = set()
outputs_connections: Set[WebSocket] = set()

# Mount static files from Web directory
app.mount("/static", StaticFiles(directory="Web"), name="static")

# Ollama configuration
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma3:12b"  # Change this to your preferred model


@app.get("/")
async def read_root():
    return FileResponse("web/index.html")


@app.websocket("/ws/thoughts")
async def websocket_thoughts(websocket: WebSocket):
    """WebSocket endpoint for thoughts"""
    await websocket.accept()
    thoughts_connections.add(websocket)
    print(f"Thoughts WebSocket connected. Total connections: {len(thoughts_connections)}")
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle different message types
            if message.get("type") == "generate":
                # Forward to Ollama and stream thoughts
                await stream_thoughts_to_ollama(message.get("prompt", ""), websocket)
            
    except WebSocketDisconnect:
        thoughts_connections.discard(websocket)
        print(f"Thoughts WebSocket disconnected. Total connections: {len(thoughts_connections)}")


@app.websocket("/ws/outputs")
async def websocket_outputs(websocket: WebSocket):
    """WebSocket endpoint for outputs"""
    await websocket.accept()
    outputs_connections.add(websocket)
    print(f"Outputs WebSocket connected. Total connections: {len(outputs_connections)}")
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle different message types
            if message.get("type") == "generate":
                # Forward to Ollama and stream outputs
                await stream_outputs_to_ollama(message.get("prompt", ""), websocket)
            
    except WebSocketDisconnect:
        outputs_connections.discard(websocket)
        print(f"Outputs WebSocket disconnected. Total connections: {len(outputs_connections)}")


async def stream_thoughts_to_ollama(prompt: str, websocket: WebSocket):
    """Stream thoughts from Ollama to the thoughts WebSocket"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": True
                }
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            # Send thought chunk to WebSocket
                            await websocket.send_json({
                                "type": "thought",
                                "content": data.get("response", ""),
                                "done": data.get("done", False)
                            })
                            
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except httpx.RequestError as e:
            await websocket.send_json({
                "type": "error",
                "message": f"Error connecting to Ollama: {str(e)}"
            })


async def stream_outputs_to_ollama(prompt: str, websocket: WebSocket):
    """Stream outputs from Ollama to the outputs WebSocket"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": True
                }
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            # Send output chunk to WebSocket
                            await websocket.send_json({
                                "type": "output",
                                "content": data.get("response", ""),
                                "done": data.get("done", False)
                            })
                            
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except httpx.RequestError as e:
            await websocket.send_json({
                "type": "error",
                "message": f"Error connecting to Ollama: {str(e)}"
            })


async def broadcast_to_thoughts(message: dict):
    """Broadcast a message to all thoughts WebSocket connections"""
    disconnected = set()
    for connection in thoughts_connections:
        try:
            await connection.send_json(message)
        except:
            disconnected.add(connection)
    
    # Remove disconnected connections
    thoughts_connections.difference_update(disconnected)


async def broadcast_to_outputs(message: dict):
    """Broadcast a message to all outputs WebSocket connections"""
    disconnected = set()
    for connection in outputs_connections:
        try:
            await connection.send_json(message)
        except:
            disconnected.add(connection)
    
    # Remove disconnected connections
    outputs_connections.difference_update(disconnected)


if __name__ == "__main__":
    import uvicorn
    print("Starting server on http://localhost:8000")
    print("WebSocket endpoints:")
    print("  - ws://localhost:8000/ws/thoughts")
    print("  - ws://localhost:8000/ws/outputs")
    print(f"Connecting to Ollama at {OLLAMA_BASE_URL}")
    uvicorn.run(app, host="0.0.0.0", port=8000)

