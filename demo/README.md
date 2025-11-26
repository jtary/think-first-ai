# Think First AI - Demo

A web application that serves a frontend and exposes two WebSocket endpoints for thoughts and outputs, connecting to Ollama on localhost.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Make sure Ollama is running on localhost (default port 11434):
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags
```

3. Update the model name in `main.py` if needed (default is "llama2"):
```python
OLLAMA_MODEL = "your-model-name"
```

## Running

Start the server:
```bash
python main.py
```

The application will be available at:
- Web interface: http://localhost:8000
- Thoughts WebSocket: ws://localhost:8000/ws/thoughts
- Outputs WebSocket: ws://localhost:8000/ws/outputs

## Usage

1. Open http://localhost:8000 in your browser
2. The page will automatically connect to both WebSocket endpoints
3. Enter a prompt and click "Send" or press Enter
4. Watch the thoughts and outputs stream in real-time

## Architecture

- **FastAPI**: Web server and WebSocket handling
- **Static Files**: Served from the `Web/` directory
- **WebSocket Endpoints**: 
  - `/ws/thoughts`: Streams internal thoughts/processing
  - `/ws/outputs`: Streams final outputs
- **Ollama Integration**: Connects to Ollama API at http://localhost:11434

