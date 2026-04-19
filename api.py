import logging
import asyncio
import json
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query

# Import the session logic from your existing final.py
try:
    from final import GeoFoodSession
except ImportError:
    # Fallback for testing if final.py isn't immediately present in path
    logging.error("Could not import GeoFoodSession from final.py. Ensure files are in the same directory.")
    GeoFoodSession = None

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

app = FastAPI(title="Geo-Food Assistant API")

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Geo-Food WebSocket API is running. Connect to /ws/chat."}

@app.websocket("/ws/chat")
async def websocket_endpoint(
    websocket: WebSocket,
    lat: Optional[float] = Query(None, description="User's Latitude"),
    lon: Optional[float] = Query(None, description="User's Longitude"),
    top_k: int = Query(5, description="Number of top results to track")
):
    """
    WebSocket endpoint for conversational geo-food search.
    
    Usage:
      Connect to: ws://localhost:8000/ws/chat?lat=17.3850&lon=78.4867&top_k=5
    """
    await websocket.accept()
    
    client_info = f"{websocket.client.host}:{websocket.client.port}"
    logging.info(f"New connection from {client_info}. Lat: {lat}, Lon: {lon}")

    # Initialize the session state for this specific connection.
    # We create one session object per websocket connection to maintain context (follow-up questions).
    if GeoFoodSession:
        session = GeoFoodSession(lat=lat, lon=lon, top_k=top_k)
    else:
        await websocket.close(code=1011, reason="Server misconfiguration: GeoFoodSession not found")
        return

    try:
        while True:
            # 1. Receive message from client
            data = await websocket.receive_text()
            user_query = data.strip()
            
            logging.info(f"[{client_info}] Received: {user_query}")

            if not user_query:
                continue

            # 2. Process message using your existing logic
            # CRITICAL: We run handle_message in a separate thread using asyncio.to_thread.
            # This prevents 'RuntimeError: asyncio.run() cannot be called from a running event loop'
            # because your Phase_2 code calls asyncio.run() internally.
            try:
                response_text = await asyncio.to_thread(session.handle_message, user_query)
            except Exception as e:
                logging.error(f"Error processing message: {e}")
                response_text = f"Internal server error: {str(e)}"

            # 3. Send response back to client
            # We wrap it in JSON structure for easier frontend parsing
            response_payload = {
                "type": "message",
                "text": response_text
            }
            
            await websocket.send_json(response_payload)

    except WebSocketDisconnect:
        logging.info(f"Client {client_info} disconnected")
    except Exception as e:
        logging.error(f"WebSocket connection error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass