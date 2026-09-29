"""NousResearch pokemon-agent HTTP adapter (Pokemon Red).

The emulator only advances inside /action, so every wait is frames sent there.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from nuzlocke.environment import screen
from nuzlocke.environment.base import ActionResult
from nuzlocke.environment.joypad import agent_can_act, is_naming_lock
from nuzlocke.environment.macros import drop_naming_confirm_if_walking, expand_actions
from nuzlocke.environment.maps import map_name
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import ControlState, GameAction, PlayerObservation

# /screenshot/grid scale for vision calls: labelled A1..J9 walk cells, player at E5.
VISION_GRID_SCALE = 4
SKIP_DIALOG_MAX_ROUNDS = 6
SKIP_DIALOG_STABLE_ROUNDS = 2
# pokemon-agent runs no frames after a hold lets go, so two holds in a row reach the game as
# one unbroken hold and only the first is a press. Every hold is followed by released frames.
MASH_ROUND = ("hold_b_30", "wait_30")
HOLD_RELEASE = "wait_12"
# What A opens is drawn up to 10 frames after press_a returns, so a burst's last A waits.
A_SETTLE = "wait_30"
SCENE_ROUND = "wait_30"
SCENE_MAX_ROUNDS = 10
SCENE_STILL_ROUNDS = 2


def _same_tile(before: PlayerObservation, after: PlayerObservation) -> bool:
    if None in (before.x, before.y, after.x, after.y):
        return False
    return (before.map_name, before.x, before.y) == (after.map_name, after.x, after.y)


# One walk_* press is one tile from any facing: Gen 1 has no turn-in-place, and a press into
# a wall only turns the player.
def _turned(before: PlayerObservation, after: PlayerObservation) -> bool:
    return bool(before.facing and after.facing) and (
        str(before.facing).lower() != str(after.facing).lower()
    )


def _turned_to(action: GameAction, before: PlayerObservation, after: PlayerObservation) -> bool:
    direction = action.value.removeprefix("walk_")
    return _turned(before, after) and str(after.facing).lower() == direction


def _transition(before: PlayerObservation, after: PlayerObservation) -> str | None:
    if after.in_battle and not before.in_battle:
        return "battle_started"
    if after.map_name and before.map_name and after.map_name != before.map_name:
        return "map_transition"
    return None


class NousRedEnvironment:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8765",
        run_dir: Path,
        rom_path: Path | None = None,
        auto_start: bool = True,
        speed: int = 4,
        press_interval_s: float = 0.1,
        load_state: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.run_dir = run_dir
        self.rom_path = rom_path
        self.speed = speed
        self.press_interval_s = max(0.0, float(press_interval_s))
        self.load_state = load_state
        # trust_env=False: a dev HTTP(S)_PROXY would turn /health into a 503.
        self._client = httpx.Client(timeout=60.0, trust_env=False)
        self._proc: subprocess.Popen[str] | None = None
        # The map the last observation was on; a change means a warp is still loading.
        self._last_map_id: Any = None
        self._log: Any = None
        if auto_start:
            self._ensure_server()

    def _ensure_server(self) -> None:
        if self.healthy():
            return
        if not self.rom_path or not self.rom_path.exists():
            raise FileNotFoundError(
                "Pokemon Red/Blue ROM required to start pokemon-agent. "
                "Pass --rom /path/to/pokemon_red.gb or set NUZLOCKE_ROM."
            )
        port = self.base_url.rsplit(":", 1)[-1]
        data_dir = self.run_dir / "pokemon-agent-data"
        data_dir.mkdir(parents=True, exist_ok=True)
        # pokemon-agent's server plus /map/objects (warps, signs, NPCs from WRAM).
        cmd = [sys.executable, "-m", "nuzlocke.environment.pa_serve", "serve"]
        cmd += ["--rom", str(self.rom_path), "--port", port]
        cmd += ["--data-dir", str(data_dir)]
        if self.load_state and (data_dir / "saves" / f"{self.load_state}.state").exists():
            cmd += ["--load-state", self.load_state]
        log_path = self.run_dir / "pokemon-agent.log"
        self._log = log_path.open("w", encoding="utf-8")
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=self._log, stderr=subprocess.STDOUT, text=True
            )
        except FileNotFoundError as err:
            raise RuntimeError(
                "pokemon-agent CLI not found. Install with: uv sync --extra emu"
            ) from err
        deadline = time.time() + 45
        while time.time() < deadline:
            if self.healthy():
                return
            time.sleep(0.4)
        raise RuntimeError(f"pokemon-agent failed to become healthy. See {log_path}")

    def shutdown(self) -> None:
        """Stop the pokemon-agent this object started. A server it found running is left alone."""
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if self._log is not None:
            self._log.close()
            self._log = None
        self._client.close()

    def healthy(self) -> bool:
        try:
            return self._client.get(f"{self.base_url}/health").status_code == 200
        except httpx.HTTPError:
            return False

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        r = self._client.get(f"{self.base_url}{path}", **kwargs)
        r.raise_for_status()
        return r

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        r = self._client.post(f"{self.base_url}{path}", json=payload)
        r.raise_for_status()
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {"raw": r.text}

    def _observation_from_state(
        self,
        state: dict[str, Any],
        *,
        screenshot_path: str | None = None,
        collision_ascii: str | None = None,
        objects: dict[str, Any] | None = None,
    ) -> PlayerObservation:
        player = state.get("player") or {}
        pos = player.get("position") or {}
        map_info = state.get("map") or {}
        dialog = state.get("dialog") or {}
        battle = state.get("battle")
        in_battle = bool(
            isinstance(battle, dict)
            and battle.get("in_battle")
            and battle.get("type") not in {None, "none", ""}
        )
        map_id = map_info.get("map_id")
        joy_ignore = int(dialog.get("joy_ignore") or 0)
        if in_battle and (objects or {}).get("enemy"):
            # The POKéMON on the field (wEnemyMon), not pokemon-agent's stale enemy party.
            battle = {**battle, "enemy": objects["enemy"]}
        return PlayerObservation(
            screenshot_path=screenshot_path,
            map_name=map_name(
                pos.get("map_id") if map_id is None else map_id,
                map_info.get("map_name") or pos.get("map_name"),
            ),
            map_id=pos.get("map_id") if map_id is None else map_id,
            x=pos.get("x"),
            y=pos.get("y"),
            facing=player.get("facing"),
            dialog_active=bool(dialog.get("active")),
            dialog_text=dialog.get("text"),
            joy_ignore=joy_ignore,
            text_box_id=dialog.get("text_box_id"),
            input_ready=agent_can_act(joy_ignore),
            in_battle=in_battle,
            battle=battle if in_battle else None,
            party=list(state.get("party") or []),
            bag=list(state.get("bag") or []),
            badges=list(player.get("badges") or player.get("badges_list") or []),
            money=player.get("money"),
            collision_ascii=collision_ascii,
            **_objects_on_map(objects, map_id if map_id is not None else pos.get("map_id")),
            screen_rows=[str(row) for row in (objects or {}).get("screen") or []],
            map_size=(objects or {}).get("size") or None,
            connections=[str(side) for side in (objects or {}).get("connections") or []],
            cutscene=_cutscene((objects or {}).get("input")),
            flags=dict(state.get("flags") or {}),
            frame_count=(state.get("metadata") or {}).get("frame_count"),
            raw_player=player,
        )

    def peek_state(self) -> PlayerObservation:
        """/state only: no screenshot, no map ASCII."""
        return self._observation_from_state(self._get("/state").json())

    def _collision_ascii(self) -> str | None:
        try:
            r = self._get("/map/ascii")
            is_json = "json" in (r.headers.get("content-type") or "").lower()
            body = r.json() if is_json else r.text
        except (httpx.HTTPError, ValueError):
            return None
        if isinstance(body, dict):
            body = body.get("map") or body.get("ascii")
        return body if isinstance(body, str) else None

    def _map_objects(self) -> dict[str, Any] | None:
        """Warps, signs, and NPCs from WRAM. None on a server without the route."""
        try:
            r = self._get("/map/objects")
            body = r.json()
        except (httpx.HTTPError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    def settle(self) -> int:
        """Run frames until there is something to decide: control, a text box, or a ▶ menu.

        A step still animating, a cutscene, a battle animation between lines: a Jev call or a
        vision look made then is spent on a frame that is about to change. Returns the rounds.
        """
        for rounds in range(SETTLE_ROUNDS):
            objects = self._map_objects()
            if not objects or not busy(objects):
                return rounds
            self._post_json("/action", {"actions": [SETTLE_ROUND]})
        return SETTLE_ROUNDS

    def observe(self) -> PlayerObservation:
        self.settle()
        shot: str | None = str(self.run_dir / "screenshots" / "latest.png")
        try:
            self.screenshot(shot)
        except httpx.HTTPError:
            shot = None
        else:
            # After a load or a fade the LCD can be blank; it gets 60 more frames once.
            with contextlib.suppress(Exception):
                from PIL import Image

                extrema = Image.open(shot).getextrema()
                if all(isinstance(ch, tuple) and ch[0] == ch[1] for ch in extrema[:3]):
                    self._post_json("/action", {"actions": ["wait_60"]})
                    self.screenshot(shot)
        state = self._get("/state").json()
        map_id = (state.get("map") or {}).get("map_id")
        if self._last_map_id is not None and map_id != self._last_map_id:
            # A warp: the map id changes first, x/y and the warp table 30-40 frames later
            # (measured at Red's front door). Let the new map finish loading, then read again.
            self._post_json("/action", {"actions": ["wait_60"]})
            if shot is not None:
                with contextlib.suppress(httpx.HTTPError):
                    self.screenshot(shot)
            state = self._get("/state").json()
        self._last_map_id = map_id
        collision = self._collision_ascii()
        objects = self._map_objects()
        return self._observation_from_state(
            state, screenshot_path=shot, collision_ascii=collision, objects=objects
        )

    def screenshot(self, path: str | None = None) -> bytes:
        data = self._get("/screenshot").content
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(data)
        return data

    def vision_frame(self, obs: PlayerObservation) -> PlayerObservation:
        """``obs`` with ``vision_path`` set to the grid-overlay frame.

        The emulator is frozen between /action calls, so this is the frame of
        ``obs.screenshot_path``. An older server without /screenshot/grid keeps the native frame.
        """
        try:
            data = self._get("/screenshot/grid", params={"scale": VISION_GRID_SCALE}).content
        except httpx.HTTPError:
            return obs
        path = self.run_dir / "screenshots" / "latest_grid.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return obs.model_copy(update={"vision_path": str(path)})

    def save_checkpoint(self, name: str) -> dict[str, Any]:
        """Crash-recovery only, never to undo a committed outcome.

        While a dashboard game session is active, /save writes a session-scoped folder that /load
        never reads, so a save missing from /saves raises instead of passing silently.
        """
        result = self._post_json("/save", {"name": name})
        if saved := result.get("path"):
            from nuzlocke.orchestration.checkpoint import mirror_save

            mirror_save(Path(saved), run_dir=self.run_dir, name=name)
        if name not in {s.get("name") for s in self.list_checkpoints()}:
            raise RuntimeError(
                f"checkpoint '{name}' saved to a session-scoped path that "
                "pokemon-agent's /load cannot read (a dashboard game session "
                "is active) — close the active dashboard session for "
                "checkpointing to work"
            )
        return result

    def load_checkpoint(self, name: str) -> dict[str, Any]:
        return self._post_json("/load", {"name": name})

    def publish_savestate(self, name: str) -> None:
        """Copy this run's savestate into the live server's flat saves dir; /load reads only that."""
        from nuzlocke.orchestration.checkpoint import data_dir_from_ps

        src = self.run_dir / "savestates" / f"{name}.state"
        if not src.is_file():
            src = self.run_dir / "pokemon-agent-data" / "saves" / f"{name}.state"
        if not src.is_file():
            return
        try:
            text = subprocess.check_output(["ps", "-ax", "-o", "command="], text=True)
        except (OSError, subprocess.CalledProcessError):
            return
        data_dir = data_dir_from_ps(text, self.base_url.rsplit(":", 1)[-1])
        if data_dir is None:
            return
        dest = data_dir / "saves" / f"{name}.state"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)

    def list_checkpoints(self) -> list[dict[str, Any]]:
        return list(self._get("/saves").json().get("saves") or [])

    def _joy_ignore(self) -> int:
        try:
            dialog = self._get("/state").json().get("dialog") or {}
            return int(dialog.get("joy_ignore") or 0)
        except (httpx.HTTPError, TypeError, ValueError):
            return 0

    def _live_frame(self, name: str) -> tuple[bytes, str] | None:
        """The live frame and the file it was saved to, or None when it cannot be read."""
        path = self.run_dir / "screenshots" / f"{name}.png"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = self.screenshot(str(path))
        except (httpx.HTTPError, OSError, TypeError, ValueError):
            return None
        return (data, str(path)) if isinstance(data, (bytes, bytearray)) else None

    def _mash_frame(self) -> tuple[str | None, bool]:
        """Whole-frame digest, and whether the text box is drawn.

        The digest covers the world region too: in battle "CHARMANDER used SCRATCH!" sits
        unchanged while the move and the HP bar animate above it, and B does nothing until
        they finish. An unreadable frame counts as open, so the mash runs on with B.
        """
        frame = self._live_frame("mash")
        if frame is None:
            return None, True
        data, path = frame
        world, dialog = screen.digests_from_bytes(data)
        return f"{world}:{dialog}", screen.text_box_open(path)

    def _prompt_up(self) -> bool:
        """A YES/NO or a list waits above the text box: the next B answers NO."""
        frame = self._live_frame("mash")
        return frame is not None and screen.prompt_box_open(frame[1])

    def execute_skip_dialog(self, *, max_rounds: int = SKIP_DIALOG_MAX_ROUNDS) -> PlayerObservation:
        """Page narrative text with B until the text box closes or stops changing.

        B advances Gen 1 text like A but starts nothing in the overworld, so a mash cannot
        re-open the NPC it just finished. The naming keyboard and a prompt end it before a press.
        """
        stable = 0
        previous, _ = self._mash_frame()
        for _ in range(max_rounds):
            if is_naming_lock(self._joy_ignore()) or self._prompt_up():
                break
            self._post_json("/action", {"actions": list(MASH_ROUND)})
            if self.press_interval_s > 0:
                time.sleep(min(self.press_interval_s, 0.05))
            current, box_open = self._mash_frame()
            stable = stable + 1 if current is not None and current == previous else 0
            if not box_open or stable >= SKIP_DIALOG_STABLE_ROUNDS:
                break
            previous = current
        return self.observe()

    def _frame_blocks_walk(self) -> bool:
        """A text box is on the live frame (a prompt always sits above one).

        RAM ``dialog_active`` stays false through real text on Red Star. An unreadable frame
        counts as clear: the tile check still stops a walk that did not move.
        """
        frame = self._live_frame("burst")
        return frame is not None and screen.text_box_open(frame[1])

    def _menu_cursor_open(self) -> bool:
        """A ▶ menu is drawn (NEW GAME, START, the battle menus, whose boxes overlap), or the
        Mart's ×01 quantity box: walks there move a cursor, not the player."""
        objects = self._map_objects() or {}
        return any("▶" in row or "×" in row for row in objects.get("screen") or [])

    def _scene_frame(self) -> tuple[str | None, bool]:
        """World-region digest of the live frame, and whether a text box is up."""
        frame = self._live_frame("burst")
        if frame is None:
            return None, False
        data, path = frame
        return screen.digests_from_bytes(data)[0], screen.text_box_open(path)

    def _wait_out_scene(self, start: PlayerObservation) -> tuple[bool, str | None]:
        """Send frames while a scripted scene (the rival walking to his ball) holds the input.

        Returns whether a scene held it, and why the burst should stop instead of trying the
        walk again. A still picture after the first round is a wall, not a scene.
        """
        previous, _ = self._scene_frame()
        if previous is None:
            return False, None
        moving = False
        still = 0
        for _ in range(SCENE_MAX_ROUNDS):
            self._post_json("/action", {"actions": [SCENE_ROUND]})
            current, boxed = self._scene_frame()
            state = self.peek_state()
            stop = "text_box" if boxed else _transition(start, state)
            if stop:
                return True, stop
            if current is None:
                break
            if current != previous:
                moving = True
                still = 0
            else:
                still += 1
                if not moving or still >= SCENE_STILL_ROUNDS:
                    break
            previous = current
        return moving, None

    def execute(self, actions: list[GameAction]) -> ActionResult:
        before = self.peek_state()
        naming = is_naming_lock(before.joy_ignore)
        # Naming and an open menu move a cursor: an unchanged map tile there is not a failed walk.
        cursor = naming or self._frame_blocks_walk() or self._menu_cursor_open()
        if naming:
            actions = drop_naming_confirm_if_walking(actions)
        actions = expand_actions(actions)
        executed: list[GameAction] = []
        walks: list[dict[str, object]] = []
        stopped: str | None = None
        waited = False
        for i, action in enumerate(actions):
            last = i + 1 == len(actions)
            executed.append(action)
            # pokemon-agent's a_until_dialog_end reads a dialog key that never exists. Nothing
            # follows a mash in the same burst: a walk or an A would re-open what it closed.
            if action in (GameAction.SKIP_DIALOG, GameAction.A_UNTIL_DIALOG_END):
                after = self.execute_skip_dialog()
                stopped = _transition(before, after) or "skip_dialog"
                if is_naming_lock(after.joy_ignore):
                    stopped = "naming_screen"
                return ActionResult(
                    executed=executed, stopped_early_because=stopped, observation=after, walks=walks
                )
            opcodes = [action.value]
            if action.value.startswith("hold_"):
                opcodes.append(HOLD_RELEASE)
            elif action is GameAction.PRESS_A and last:
                opcodes.append(A_SETTLE)
            self._post_json("/action", {"actions": opcodes})
            after = self.peek_state()
            walk = action.value.startswith("walk_") and not cursor
            scene_stop = None
            if walk and not waited and _same_tile(before, after) and not _turned(before, after):
                waited = True
                held, scene_stop = self._wait_out_scene(before)
                if held:
                    if scene_stop is None:
                        self._post_json("/action", {"actions": opcodes})
                    after = self.peek_state()
            if walk:
                walks.append(
                    {
                        "action": action.value,
                        "x0": before.x,
                        "y0": before.y,
                        "x1": after.x,
                        "y1": after.y,
                        "map_name": after.map_name,
                        "map_id": after.map_id,
                    }
                )
            if scene_stop:
                stopped = scene_stop
                break
            if walk and _same_tile(before, after):
                next_is_a = not last and actions[i + 1] is GameAction.PRESS_A
                if next_is_a and _turned_to(action, before, after):
                    before = after
                    continue
                # A wall only turns the player and a stuck press does not; either way the rest
                # of the path is no longer aimed at the tile it was planned for.
                stopped = "immobile"
                break
            stopped = _transition(before, after)
            if stopped is None and not last and not cursor and self._frame_blocks_walk():
                stopped = "text_box"
            if stopped:
                break
            before = after
            if self.press_interval_s > 0 and not last:
                time.sleep(self.press_interval_s)
        return ActionResult(
            executed=executed,
            stopped_early_because=stopped,
            observation=self.observe(),
            walks=walks,
        )

    def get_control(self) -> ControlState:
        try:
            data = self._get("/control").json()
        except httpx.HTTPError:
            return ControlState.RUNNING
        state = (data.get("state") or data.get("status") or "running").lower()
        if state in {"paused", "pause"}:
            return ControlState.PAUSED
        if state in {"stopped", "stop"}:
            return ControlState.STOPPED
        return ControlState.RUNNING

    def set_control(self, state: ControlState) -> None:
        with contextlib.suppress(httpx.HTTPError):  # older servers have no /control
            self._post_json("/control", {"state": state.value})

    def push_event(self, kind: str, text: str, *, category: str | None = None) -> None:
        """Push narration to the Field Log dashboard."""
        if kind in {"thinking", "thought", "narration"}:
            kind = "reasoning"
        elif kind in {"milestone", "moment"}:
            kind = "key_moment"
        if kind == "key_moment":
            payload = {"type": kind, "description": text, "category": category or "milestone"}
        else:
            payload = {"type": kind, "text": text}
        with contextlib.suppress(httpx.HTTPError):
            self._post_json("/event", payload)

    def set_objectives(self, objectives: list[dict]) -> None:
        normalized = []
        for default_tier, obj in zip(("primary", "secondary", "tertiary"), objectives):
            if "tier" in obj and "text" in obj:
                tier, text = obj["tier"], obj["text"]
            else:
                tier, text = default_tier, str(obj.get("label") or obj.get("text") or obj)
            normalized.append({"tier": tier, "text": text, "done": bool(obj.get("done", False))})
        with contextlib.suppress(httpx.HTTPError):
            self._post_json("/objectives", {"objectives": normalized})

    def close(self) -> None:
        self._client.close()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def _objects_on_map(objects: dict[str, Any] | None, map_id: Any) -> dict[str, list[dict[str, Any]]]:
    """The object lists, only when they were read on the map ``/state`` reports."""
    if not objects or (map_id is not None and objects.get("map_id") not in (None, map_id)):
        return {}
    return {
        key: [item for item in objects.get(key) or [] if isinstance(item, dict)]
        for key in ("warps", "signs", "npcs")
    }


# At most 300 frames (about five seconds of game time) before deciding anyway.
SETTLE_ROUND = "wait_20"
SETTLE_ROUNDS = 15


def busy(objects: dict[str, Any]) -> bool:
    """Nothing to decide yet: a step, a cutscene, or a battle animation with no text or menu up."""
    rows = objects.get("screen") or []
    if any("▶" in row for row in rows) or parse_screen(rows).text_lines:
        return False
    flags = objects.get("input") or {}
    return bool(int(flags.get("walking") or 0) or int(flags.get("battle") or 0) or _cutscene(flags))


def _cutscene(flags: dict[str, Any] | None) -> bool:
    """The D-pad is ignored (0xF0 of wJoyIgnore) or a script is walking the player."""
    if not flags:
        return False
    return bool(int(flags.get("joy_ignore") or 0) & 0xF0 or int(flags.get("status5") or 0) & 0x80)
