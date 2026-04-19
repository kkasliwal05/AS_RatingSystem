import asyncio
import websockets

async def chat_client():
    # We use 127.0.0.1 instead of localhost to prevent timeout issues on macOS
    uri = "ws://127.0.0.1:8000/ws/chat"
    
    print(f"🔌 Connecting to {uri} ...")

    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected! (Type 'exit' to quit)\n")

            while True:
                # 1. Get User Input
                user_input = input("You: ")
                
                if user_input.lower() in ["exit", "quit"]:
                    print("👋 Disconnecting...")
                    break
                
                if not user_input.strip():
                    continue

                # 2. Send to Server
                await websocket.send(user_input)

                # 3. Wait for Server Response
                # Note: If your scraping takes time, the script waits here
                try:
                    print("⏳ ... waiting for response ...")
                    response = await websocket.recv()
                    print(f"🤖 Server: {response}\n")
                    
                except websockets.exceptions.ConnectionClosed:
                    print("❌ Connection closed by server.")
                    break

    except ConnectionRefusedError:
        print("❌ Could not connect. Is the server running?")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(chat_client())