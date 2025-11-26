import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import httpx
from typing import Dict, Set, List
from datetime import datetime
import re
import os

app = FastAPI()

# Store active WebSocket connections
thoughts_connections: Set[WebSocket] = set()
outputs_connections: Set[WebSocket] = set()
wake_up_connections: Set[WebSocket] = set()

# Store conversation history per connection
conversation_histories: Dict[WebSocket, List[Dict]] = {}
wake_up_active: Dict[WebSocket, bool] = {}

def resolve_directory(path: str) -> str:
    return os.path.join(os.path.dirname(__file__), path)

# Mount static files from web directory
app.mount("/static", StaticFiles(directory=resolve_directory("web")), name="static")

# Ollama configuration
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma3:12b"  # Change this to your preferred model


@app.get("/")
async def read_root():
    return FileResponse(resolve_directory("web/index.html"))


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


@app.websocket("/ws/wakeup")
async def websocket_wakeup(websocket: WebSocket):
    """WebSocket endpoint for wake up loop"""
    await websocket.accept()
    wake_up_connections.add(websocket)
    conversation_histories[websocket] = []
    wake_up_active[websocket] = False
    print(f"Wake up WebSocket connected. Total connections: {len(wake_up_connections)}")
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle different message types
            if message.get("type") == "wake_up":
                wake_up_active[websocket] = True
                await websocket.send_json({
                    "type": "status",
                    "message": "AI is waking up...",
                    "timestamp": datetime.now().isoformat()
                })
                # Start the wake up loop
                asyncio.create_task(wake_up_loop(websocket))
            elif message.get("type") == "sleep":
                wake_up_active[websocket] = False
                await websocket.send_json({
                    "type": "status",
                    "message": "AI is going to sleep...",
                    "timestamp": datetime.now().isoformat()
                })
            
    except WebSocketDisconnect:
        wake_up_connections.discard(websocket)
        conversation_histories.pop(websocket, None)
        wake_up_active.pop(websocket, None)
        print(f"Wake up WebSocket disconnected. Total connections: {len(wake_up_connections)}")


async def wake_up_loop(websocket: WebSocket):
    """Main loop that continuously invokes the LLM with previous thoughts"""
    while wake_up_active.get(websocket, False):
        try:
            # Get conversation history
            history = conversation_histories.get(websocket, [])
            
            # Build the prompt with system instructions and history
            system_prompt = """You are an AI that thinks before speaking. You have access to a tool to send messages to the user.

TOOL: send_message_to_user
Description: Use this tool to send a message to the user. This is the ONLY way to communicate with the user.
Format: <tool_call>send_message_to_user("your message here")</tool_call>

Your previous thoughts:
"""
            
            # Add previous thoughts to the prompt
            if history:
                for entry in history:
                    timestamp = entry.get("timestamp", "")
                    thought = entry.get("thought", "")
                    system_prompt += f"\n[{timestamp}] {thought}\n"
            else:
                system_prompt += "\n(No previous thoughts yet)\n"
            
            system_prompt += "\n\nContinue thinking. If you want to send a message to the user, use the send_message_to_user tool."
            
            # Get current timestamp
            current_timestamp = datetime.now().isoformat()
            
            # Send status to client
            await websocket.send_json({
                "type": "invocation",
                "timestamp": current_timestamp,
                "message": "Invoking LLM..."
            })
            
            # Signal that a new thought is starting (clear previous)
            await websocket.send_json({
                "type": "thought_start",
                "timestamp": current_timestamp
            })
            
            # Call Ollama
            full_response = ""
            async with httpx.AsyncClient(timeout=60.0) as client:
                try:
                    async with client.stream(
                        "POST",
                        f"{OLLAMA_BASE_URL}/api/generate",
                        json={
                            "model": OLLAMA_MODEL,
                            "prompt": system_prompt,
                            "stream": True
                        }
                    ) as response:
                        response.raise_for_status()
                        
                        async for line in response.aiter_lines():
                            if line:
                                try:
                                    data = json.loads(line)
                                    chunk = data.get("response", "")
                                    full_response += chunk
                                    
                                    # Stream thought chunk to WebSocket
                                    await websocket.send_json({
                                        "type": "thought_chunk",
                                        "content": chunk,
                                        "timestamp": current_timestamp
                                    })
                                    
                                    if data.get("done", False):
                                        break
                                except json.JSONDecodeError:
                                    continue
                    
                    # Store the thought in history
                    conversation_histories[websocket].append({
                        "timestamp": current_timestamp,
                        "thought": full_response
                    })
                    
                    # Parse for tool calls
                    tool_calls = parse_tool_calls(full_response)
                    
                    for tool_call in tool_calls:
                        if tool_call["name"] == "send_message_to_user":
                            message = tool_call.get("args", {}).get("message", "")
                            # Send message to user via outputs WebSocket
                            await broadcast_to_outputs({
                                "type": "user_message",
                                "content": message,
                                "timestamp": current_timestamp
                            })
                            
                            # Also notify wake up connection
                            await websocket.send_json({
                                "type": "tool_call",
                                "tool": "send_message_to_user",
                                "message": message,
                                "timestamp": current_timestamp
                            })
                    
                    # Small delay before next invocation
                    await asyncio.sleep(1)
                    
                except httpx.RequestError as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Error connecting to Ollama: {str(e)}",
                        "timestamp": current_timestamp
                    })
                    await asyncio.sleep(5)  # Wait longer on error
                    
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "message": f"Error in wake up loop: {str(e)}",
                "timestamp": datetime.now().isoformat()
            })
            await asyncio.sleep(5)


def parse_tool_calls(text: str) -> List[Dict]:
    """Parse tool calls from LLM response text"""
    tool_calls = []
    # Look for <tool_call>send_message_to_user("message")</tool_call>
    pattern = r'<tool_call>send_message_to_user\("([^"]+)"\)</tool_call>'
    matches = re.finditer(pattern, text)
    
    for match in matches:
        tool_calls.append({
            "name": "send_message_to_user",
            "args": {
                "message": match.group(1)
            }
        })
    
    return tool_calls


if __name__ == "__main__":
    import uvicorn
    print("Starting server on http://localhost:8000")
    print("WebSocket endpoints:")
    print("  - ws://localhost:8000/ws/thoughts")
    print("  - ws://localhost:8000/ws/outputs")
    print(f"Connecting to Ollama at {OLLAMA_BASE_URL}")
    uvicorn.run(app, host="0.0.0.0", port=8000)

