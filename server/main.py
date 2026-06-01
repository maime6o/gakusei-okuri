"""
FastAPI server  —  M2/M3
- WebSocket keyed by player_name (consistent before/after game start)
- Broadcast on join/start/action (async throughout)
- /rooms/hotseat  : create+add all players+start in one call (hot-seat)
- §4 privacy       : _player_view hides others' hands and face-down antis
"""
from __future__ import annotations
import json
import pathlib
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import server.rooms as registry
from engine.game import create_game, GameConfig
from engine.actions import apply_action, ActionError

app = FastAPI(title="学生課送り", version="0.2.0")

STATIC_DIR = pathlib.Path(__file__).parent.parent / "static"

# ─────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ─────────────────────────────────────────────
# REST — room management
# ─────────────────────────────────────────────

class CreateRoomRequest(BaseModel):
    host_name: str
    target_mobilization: int = 120


class HotseatRequest(BaseModel):
    player_names: list[str]
    target_mobilization: int = 120


class JoinRoomRequest(BaseModel):
    player_name: str


@app.post("/rooms")
async def create_room(req: CreateRoomRequest):
    if req.target_mobilization not in (80, 120, 160):
        raise HTTPException(400, "目標動員数は 80/120/160 から選んでください")
    room = registry.create_room(req.host_name, req.target_mobilization)
    return {"code": room.code, "players": room.player_names}


@app.post("/rooms/hotseat")
async def create_hotseat(req: HotseatRequest):
    """Hot-seat shortcut: create + add all players + start in one call."""
    if not (2 <= len(req.player_names) <= 4):
        raise HTTPException(400, "2〜4人で指定してください")
    if req.target_mobilization not in (80, 120, 160):
        raise HTTPException(400, "目標動員数は 80/120/160 から選んでください")
    if len(set(req.player_names)) != len(req.player_names):
        raise HTTPException(400, "プレイヤー名が重複しています")
    for n in req.player_names:
        if not n.strip():
            raise HTTPException(400, "空の名前は使えません")
    room = registry.create_room(req.player_names[0], req.target_mobilization)
    for name in req.player_names[1:]:
        room.add_player(name)
    room.state = create_game(req.player_names, GameConfig(target_mobilization=req.target_mobilization))
    return {"code": room.code, "players": req.player_names}


@app.post("/rooms/{code}/join")
async def join_room(code: str, req: JoinRoomRequest):
    room = registry.get_room(code)
    if not room:
        raise HTTPException(404, "部屋が見つかりません")
    if room.is_started():
        raise HTTPException(400, "ゲームはすでに開始しています")
    if not room.add_player(req.player_name):
        raise HTTPException(400, "参加できません（満員 or 同名）")
    await _broadcast(room)
    return {"code": room.code, "players": room.player_names}


@app.post("/rooms/{code}/start")
async def start_game(code: str):
    room = registry.get_room(code)
    if not room:
        raise HTTPException(404, "部屋が見つかりません")
    if room.is_started():
        raise HTTPException(400, "すでに開始しています")
    if len(room.player_names) < 2:
        raise HTTPException(400, "2人以上必要です")
    room.state = create_game(room.player_names, GameConfig(target_mobilization=room.target_mobilization))
    await _broadcast(room)
    return {"code": room.code, "status": "started"}


@app.get("/rooms/{code}")
def get_room_info(code: str):
    room = registry.get_room(code)
    if not room:
        raise HTTPException(404, "部屋が見つかりません")
    return {
        "code": room.code,
        "players": room.player_names,
        "started": room.is_started(),
        "target": room.target_mobilization,
    }


# ─────────────────────────────────────────────
# WebSocket  (keyed by player_name)
# ─────────────────────────────────────────────

ACTION_MAP = {
    "draw":          "DrawAction",
    "play_member":   "PlayMemberAction",
    "form_band":     "FormBandAction",
    "disband":       "DisbandAction",
    "use_support":   "UseSupportAction",
    "set_anti":      "SetAntiAction",
    "reveal_anti":   "RevealAntiAction",
    "end_turn":      "EndTurnAction",
    "mulligan":      "MulliganAction",
    "choose_sotai":  "ChooseSotaiAction",
}


@app.websocket("/ws/{code}/{player_name}")
async def websocket_endpoint(ws: WebSocket, code: str, player_name: str):
    room = registry.get_room(code)
    if not room:
        await ws.close(code=4004, reason="部屋が見つかりません")
        return

    await ws.accept()

    # Register connection by player_name (consistent before/after game start)
    room.connections.setdefault(player_name, []).append(ws)

    # Send current state immediately, then broadcast so others see reconnect
    await _send_to(ws, room, player_name)
    await _broadcast_others(room, player_name)

    try:
        async for raw in ws.iter_text():
            await _handle_message(ws, room, player_name, raw)
    except WebSocketDisconnect:
        pass
    finally:
        conns = room.connections.get(player_name, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            room.connections.pop(player_name, None)


async def _handle_message(ws: WebSocket, room: Any, player_name: str, raw: str):
    import engine.actions as acts

    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await ws.send_json({"type": "error", "message": "JSONパースエラー"})
        return

    atype = msg.get("type")
    if not atype:
        await ws.send_json({"type": "error", "message": "typeフィールドが必要です"})
        return

    class_name = ACTION_MAP.get(atype)
    if not class_name:
        await ws.send_json({"type": "error", "message": f"不明なアクション: {atype}"})
        return

    if room.state is None:
        await ws.send_json({"type": "error", "message": "ゲームがまだ開始していません"})
        return

    player_id = room.player_id_for(player_name)
    if not player_id:
        await ws.send_json({"type": "error", "message": "プレイヤーが見つかりません"})
        return

    klass = getattr(acts, class_name)
    try:
        params = {k: v for k, v in msg.items() if k != "type"}
        action = klass(**params)
        new_state, events = apply_action(room.state, player_id, action)
        room.state = new_state
        room.state.event_log.extend(events)
        await _broadcast(room)
    except ActionError as e:
        await ws.send_json({"type": "error", "message": str(e)})
    except Exception as e:
        await ws.send_json({"type": "error", "message": f"サーバーエラー: {e}"})


# ─────────────────────────────────────────────
# Broadcast helpers
# ─────────────────────────────────────────────

async def _send_to(ws: WebSocket, room: Any, player_name: str) -> None:
    payload = _make_payload(room, player_name)
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:
        pass


async def _broadcast(room: Any) -> None:
    for name, conns in list(room.connections.items()):
        payload = json.dumps(_make_payload(room, name))
        for conn in list(conns):
            try:
                await conn.send_text(payload)
            except Exception:
                pass


async def _broadcast_others(room: Any, skip_name: str) -> None:
    for name, conns in list(room.connections.items()):
        if name == skip_name:
            continue
        payload = json.dumps(_make_payload(room, name))
        for conn in list(conns):
            try:
                await conn.send_text(payload)
            except Exception:
                pass


def _make_payload(room: Any, player_name: str) -> dict:
    if not room.is_started():
        return {"type": "room", "code": room.code, "players": room.player_names}
    player_id = room.player_id_for(player_name)
    if not player_id:
        return {"type": "room", "code": room.code, "players": room.player_names}
    return {"type": "state", "state": _player_view(room.state, player_id)}


def _player_view(state: Any, player_id: str) -> dict:
    """§4 privacy: hide other players' hand contents and face-down antis."""
    d = state.model_dump()
    for p in d["players"]:
        if p["player_id"] == player_id:
            continue
        # Hide hand contents
        p["hand"] = {"hidden": True, "count": len(p["hand"])}
        # Hide face-down anti cards (only reveal count and existence)
        p["anti_zone"] = [
            c if not c.get("face_down") else {"face_down": True, "instance_id": c["instance_id"]}
            for c in p["anti_zone"]
        ]
    return d


# ─────────────────────────────────────────────
# Static SPA (last — catches everything else)
# ─────────────────────────────────────────────

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
