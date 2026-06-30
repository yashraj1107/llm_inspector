import os
from dotenv import load_dotenv
load_dotenv()
import llm_inspector
import openai
import time
import sqlite3

print("Initializing patch...")
llm_inspector.auto()

client = openai.OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

print("\n--- Sending Streaming Request ---")
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Write a 1-sentence haiku about coding."}],
    stream=True,
    stream_options={"include_usage": True}
)

for chunk in response:
    if chunk.choices and chunk.choices[0].delta.content:
         print(chunk.choices[0].delta.content, end="", flush=True)

print("\n\n--- Waiting for flush ---")
time.sleep(2)

print("\n--- Verifying Database ---")
conn = sqlite3.connect("llm_inspector_data/traces.db")
row = conn.execute("SELECT model, provider, latency_ms, prompt_tokens, response_json FROM traces ORDER BY timestamp DESC LIMIT 1").fetchone()
print(f"Model: {row[0]}, Provider: {row[1]}, Latency: {row[2]}ms, Prompt Tokens: {row[3]}")
print(f"Response JSON: {row[4]}")
