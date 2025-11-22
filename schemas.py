"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name.
"""

from pydantic import BaseModel, Field
from typing import List, Optional

class CanvasPoint(BaseModel):
    x: float
    y: float

class CanvasStroke(BaseModel):
    color: str = Field("#ffffff", description="Stroke color in hex")
    size: float = Field(2.0, ge=0.5, le=50, description="Stroke size in px")
    points: List[CanvasPoint] = Field(default_factory=list)

class CanvasEvent(BaseModel):
    """
    Realtime canvas drawing events (each stroke saved as an event)
    Collection name: "canvasevent"
    """
    stroke: CanvasStroke
    user_id: Optional[str] = Field(None, description="Anonymous user id/hash")
    room: str = Field("global", description="Canvas room/channel")

class Note(BaseModel):
    """
    Single shared note content
    Collection name: "note"
    """
    content: str = Field("", description="Full note content")
    room: str = Field("global", description="Note room/channel")
