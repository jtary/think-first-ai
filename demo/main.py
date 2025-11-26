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
chat_connections: Set[WebSocket] = set()
debug_connections: Set[WebSocket] = set()

# Store conversation history per connection
conversation_histories: Dict[WebSocket, List[Dict]] = {}
wake_up_active: Dict[WebSocket, bool] = {}
user_messages: Dict[WebSocket, List[Dict]] = {}
thinking_interrupt: Dict[WebSocket, asyncio.Event] = {}

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


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for chat (user messages and AI responses)"""
    await websocket.accept()
    chat_connections.add(websocket)
    conversation_histories[websocket] = []
    user_messages[websocket] = []
    wake_up_active[websocket] = False
    thinking_interrupt[websocket] = asyncio.Event()
    print(f"Chat WebSocket connected. Total connections: {len(chat_connections)}")
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle different message types
            if message.get("type") == "wake_up":
                wake_up_active[websocket] = True
                status_msg = {
                    "type": "status",
                    "message": "AI is waking up...",
                    "timestamp": datetime.now().isoformat()
                }
                await websocket.send_json(status_msg)
                await broadcast_to_debug(status_msg)
                # Start the wake up loop
                asyncio.create_task(wake_up_loop(websocket))
            elif message.get("type") == "sleep":
                wake_up_active[websocket] = False
                thinking_interrupt[websocket].set()  # Interrupt any ongoing thinking
                status_msg = {
                    "type": "status",
                    "message": "AI is going to sleep...",
                    "timestamp": datetime.now().isoformat()
                }
                await websocket.send_json(status_msg)
                await broadcast_to_debug(status_msg)
            elif message.get("type") == "user_message":
                # Store user message and interrupt thinking
                user_msg = {
                    "content": message.get("content", ""),
                    "timestamp": message.get("timestamp", datetime.now().isoformat())
                }
                user_messages[websocket].append(user_msg)
                await broadcast_to_debug({
                    "type": "user-message",
                    "content": user_msg["content"],
                    "timestamp": user_msg["timestamp"]
                })
                # Interrupt current thinking to process user message
                thinking_interrupt[websocket].set()
            
    except WebSocketDisconnect:
        chat_connections.discard(websocket)
        conversation_histories.pop(websocket, None)
        user_messages.pop(websocket, None)
        wake_up_active.pop(websocket, None)
        thinking_interrupt.pop(websocket, None)
        print(f"Chat WebSocket disconnected. Total connections: {len(chat_connections)}")


@app.websocket("/ws/debug")
async def websocket_debug(websocket: WebSocket):
    """WebSocket endpoint for debug information"""
    await websocket.accept()
    debug_connections.add(websocket)
    print(f"Debug WebSocket connected. Total connections: {len(debug_connections)}")
    
    try:
        while True:
            # Just keep connection alive, messages are sent from other parts
            await websocket.receive_text()
    except WebSocketDisconnect:
        debug_connections.discard(websocket)
        print(f"Debug WebSocket disconnected. Total connections: {len(debug_connections)}")


async def broadcast_to_chat(message: dict):
    """Broadcast a message to all chat WebSocket connections"""
    disconnected = set()
    for connection in chat_connections:
        try:
            await connection.send_json(message)
        except:
            disconnected.add(connection)
    
    # Remove disconnected connections
    chat_connections.difference_update(disconnected)


async def broadcast_to_debug(message: dict):
    """Broadcast a message to all debug WebSocket connections"""
    disconnected = set()
    for connection in debug_connections:
        try:
            await connection.send_json(message)
        except:
            disconnected.add(connection)
    
    # Remove disconnected connections
    debug_connections.difference_update(disconnected)




async def wake_up_loop(websocket: WebSocket):
    """Main loop that continuously invokes the LLM with previous thoughts"""
    while wake_up_active.get(websocket, False):
        try:
            # Reset interrupt event
            thinking_interrupt[websocket].clear()
            
            # Get conversation history and user messages
            history = conversation_histories.get(websocket, [])
            user_msgs = user_messages.get(websocket, [])
            
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
            
            # Add user messages to the prompt
            if user_msgs:
                system_prompt += "\n\nUser messages:\n"
                for msg in user_msgs:
                    timestamp = msg.get("timestamp", "")
                    content = msg.get("content", "")
                    system_prompt += f"\n[{timestamp}] User: {content}\n"
                # Clear user messages after processing
                user_messages[websocket] = []
            
            system_prompt += "\n\nContinue thinking. If you want to send a message to the user, use the send_message_to_user tool."
            
            # Get current timestamp
            current_timestamp = datetime.now().isoformat()
            
            # Send invocation status to debug only (include prompt)
            await broadcast_to_debug({
                "type": "invocation",
                "timestamp": current_timestamp,
                "message": "Invoking LLM...",
                "prompt": system_prompt
            })
            
            # Signal that a new thought is starting (debug only)
            await broadcast_to_debug({
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
                            # Check for interrupt
                            interrupt_event = thinking_interrupt.get(websocket)
                            if interrupt_event and interrupt_event.is_set():
                                break
                            
                            if line:
                                try:
                                    data = json.loads(line)
                                    chunk = data.get("response", "")
                                    full_response += chunk
                                    
                                    # Stream thought chunk to debug
                                    await broadcast_to_debug({
                                        "type": "thought_chunk",
                                        "content": chunk,
                                        "timestamp": current_timestamp
                                    })
                                    
                                    if data.get("done", False):
                                        break
                                except json.JSONDecodeError:
                                    continue
                    
                    # Only store thought if not interrupted
                    interrupt_event = thinking_interrupt.get(websocket)
                    if (not interrupt_event or not interrupt_event.is_set()) and full_response:
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
                            # Send message to user via chat WebSocket
                            ai_msg = {
                                "type": "ai_message",
                                "content": message,
                                "timestamp": current_timestamp
                            }
                            await broadcast_to_chat(ai_msg)
                            
                            # Notify debug about tool call and message
                            await broadcast_to_debug({
                                "type": "tool_call",
                                "tool": "send_message_to_user",
                                "message": message,
                                "timestamp": current_timestamp
                            })
                            await broadcast_to_debug({
                                "type": "ai-message",
                                "content": message,
                                "timestamp": current_timestamp
                            })
                    
                    # Small delay before next invocation (unless interrupted)
                    interrupt_event = thinking_interrupt.get(websocket)
                    if not interrupt_event or not interrupt_event.is_set():
                        await asyncio.sleep(1)
                    else:
                        # If interrupted, continue immediately to process user message
                        continue
                    
                except httpx.RequestError as e:
                    error_msg = f"Error connecting to Ollama: {str(e)}"
                    await websocket.send_json({
                        "type": "error",
                        "message": error_msg,
                        "timestamp": current_timestamp
                    })
                    await broadcast_to_debug({
                        "type": "error",
                        "message": error_msg,
                        "timestamp": current_timestamp
                    })
                    await asyncio.sleep(5)  # Wait longer on error
                    
        except Exception as e:
            error_msg = f"Error in wake up loop: {str(e)}"
            timestamp = datetime.now().isoformat()
            await websocket.send_json({
                "type": "error",
                "message": error_msg,
                "timestamp": timestamp
            })
            await broadcast_to_debug({
                "type": "error",
                "message": error_msg,
                "timestamp": timestamp
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
    print("  - ws://localhost:8000/ws/chat")
    print("  - ws://localhost:8000/ws/debug")
    print(f"Connecting to Ollama at {OLLAMA_BASE_URL}")
    uvicorn.run(app, host="0.0.0.0", port=8000)

