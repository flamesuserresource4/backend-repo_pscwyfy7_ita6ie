import os
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database import db, create_document, get_documents
from schemas import CanvasEvent, Note

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionManager:
    def __init__(self):
        # room -> set of websockets
        self.canvas_rooms: Dict[str, List[WebSocket]] = {}
        self.note_rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, ws: WebSocket, room: str, kind: str):
        await ws.accept()
        rooms = self.canvas_rooms if kind == "canvas" else self.note_rooms
        rooms.setdefault(room, [])
        rooms[room].append(ws)

    def _get_rooms(self, kind: str):
        return self.canvas_rooms if kind == "canvas" else self.note_rooms

    def disconnect(self, ws: WebSocket, room: str, kind: str):
        rooms = self._get_rooms(kind)
        if room in rooms and ws in rooms[room]:
            rooms[room].remove(ws)
            if not rooms[room]:
                rooms.pop(room, None)

    async def broadcast(self, message, room: str, kind: str):
        rooms = self._get_rooms(kind)
        for ws in rooms.get(room, []):
            try:
                await ws.send_json(message)
            except Exception:
                # drop broken sockets silently
                pass


manager = ConnectionManager()


@app.get("/")
def read_root():
    return {"message": "Realtime Canvas + Note API running"}


@app.get("/api/canvas/{room}")
def get_canvas_events(room: str):
    # Return latest 500 strokes for the room
    events = get_documents("canvasevent", {"room": room}, limit=500)
    # Convert ObjectId and datetime
    for e in events:
        e["_id"] = str(e.get("_id"))
        if "created_at" in e:
            e["created_at"] = str(e["created_at"])  # simple string conversion
        if "updated_at" in e:
            e["updated_at"] = str(e["updated_at"])  # simple string conversion
    return {"events": events}


@app.get("/api/note/{room}")
def get_note(room: str):
    # Find the latest note doc for room
    doc = db["note"].find_one({"room": room})
    if not doc:
        return {"content": "", "room": room}
    return {"content": doc.get("content", ""), "room": room}


class NoteUpdate(BaseModel):
    content: str


@app.put("/api/note/{room}")
def put_note(room: str, payload: NoteUpdate):
    db["note"].update_one(
        {"room": room},
        {"$set": {"content": payload.content}},
        upsert=True,
    )
    return {"status": "ok"}


@app.websocket("/ws/canvas/{room}")
async def ws_canvas(ws: WebSocket, room: str):
    await manager.connect(ws, room, "canvas")
    try:
        while True:
            data = await ws.receive_json()
            # Validate and persist
            try:
                event = CanvasEvent(**{**data, "room": room})
                create_document("canvasevent", event)
                # Broadcast to others (including sender)
                await manager.broadcast({"type": "stroke", "data": event.model_dump()}, room, "canvas")
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
    except WebSocketDisconnect:
        manager.disconnect(ws, room, "canvas")


@app.websocket("/ws/note/{room}")
async def ws_note(ws: WebSocket, room: str):
    await manager.connect(ws, room, "note")
    # Send current note content on connect
    current = db["note"].find_one({"room": room}) or {"content": ""}
    try:
        await ws.send_json({"type": "init", "content": current.get("content", "")})
        while True:
            data = await ws.receive_json()
            # Expect {type: "update", content: str}
            if isinstance(data, dict) and data.get("type") == "update":
                content = str(data.get("content", ""))
                db["note"].update_one({"room": room}, {"$set": {"content": content}}, upsert=True)
                await manager.broadcast({"type": "update", "content": content}, room, "note")
            else:
                await ws.send_json({"type": "error", "message": "Invalid payload"})
    except WebSocketDisconnect:
        manager.disconnect(ws, room, "note")


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
