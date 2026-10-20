import asyncio
import os
from dotenv import load_dotenv
from jarvis.voice import stt

async def test():
    load_dotenv()
    print(f"Key check: {os.getenv('DEEPGRAM_API_KEY')[:5] if os.getenv('DEEPGRAM_API_KEY') else 'NONE'}...")
    try:
        # Create a tiny dummy wav file
        with open("test.wav", "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x08\x00\x00\x00\x01\x00\x00\x00data\x00\x00\x00\x00")
        
        with open("test.wav", "rb") as f:
            data = f.read()
            print("Transcribing...")
            text = await stt.transcribe(data)
            print(f"Result: {text}")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
