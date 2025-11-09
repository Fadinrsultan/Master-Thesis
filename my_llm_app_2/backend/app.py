import os
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
import openai

# 1. Read the OpenAI key from an environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")

# 2. Create the FastAPI app
app = FastAPI()
# In-memory conversation history for /chat
conversation_history = []

# 3. Define request/response models
class SearchRequest(BaseModel):
    query: str

class ChatRequest(BaseModel):
    message: str

# 4. /search endpoint (accepts POST JSON: {"query": "…"})
@app.post("/search")
async def search_endpoint(req: SearchRequest):
    prompt = req.query
    try:
        response = openai.ChatCompletion.create(
            model="chatgpt-4o-latest",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user",   "content": prompt}
            ]
        )
        return {"response": response["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"response": f"Error: {str(e)}"}

# 5. /chat endpoint (accepts POST JSON: {"message": "…"})
@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    msg = req.message
    conversation_history.append({"role": "user", "content": msg})
    # Ensure a system prompt at start if not already present
    if not any(m["role"] == "system" for m in conversation_history):
        conversation_history.insert(0, {"role": "system", "content": "You are a helpful assistant."})
    try:
        res = openai.ChatCompletion.create(
            model="chatgpt-4o-latest",
            messages=conversation_history
        )
        reply = res.choices[0].message["content"]
        conversation_history.append({"role": "assistant", "content": reply})
        return {"response": reply}
    except Exception as e:
        return {"response": f"Error: {str(e)}"}

# 6. GET / returns frontend/index.html
@app.get("/", response_class=FileResponse)
async def get_index():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "../frontend/index.html")
    )

# 7. Serve any static asset under /static (e.g. /static/main.js)
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "../frontend")),
    name="static"
)
