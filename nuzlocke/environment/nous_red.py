"""NousResearch pokemon-agent HTTP adapter (Pokemon Red)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from nuzlocke.environment.base import ActionResult
from nuzlocke.environment.joypad import (
    agent_can_act,
    is_dialog_lock,
    is_naming_lock,
)
from nuzlocke.environment.macros import expand_actions
from nuzlocke.state.models import ControlState, GameAction, PlayerObservation


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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.run_dir = run_dir
        self.rom_path = rom_path
        self.auto_start = auto_start
        self.speed = speed
        self.press_interval_s = max(0.0, float(press_interval_s))
        self._client = httpx.Client(timeout=60.0)
        self._proc: subprocess.Popen[str] | None = None
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
        cmd = [
            "pokemon-agent",
            "serve",
            "--rom",
            str(self.rom_path),
            "--port",
            port,
            "--data-dir",
            str(data_dir),
        ]
        # Best-effort; CLI flags may vary by version.
        log_path = self.run_dir / "pokemon-agent.log"
        log_f = log_path.open("w", encoding="utf-8")
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError as err:
            raise RuntimeError(
                "pokemon-agent CLI not found. Install with: "
                "uv sync --extra emu"
            ) from err
        deadline = time.time() + 45
        while time.time() < deadline:
            if self.healthy():
                return
            time.sleep(0.4)
        raise RuntimeError(
            f"pokemon-agent failed to become healthy. See {log_path}"
        )

    def healthy(self) -> bool:
        try:
            r = self._client.get(f"{self.base_url}/health")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def _get_json(self, path: str) -> Any:
        r = self._client.get(f"{self.base_url}{path}")
        r.raise_for_status()
        return r.json()

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        r = self._client.post(f"{self.base_url}{path}", json=payload)
        r.raise_for_status()
        if r.content:
            try:
                return r.json()
            except ValueError:
                return {"raw": r.text}
        return {}

    def _observation_from_state(
        self,
        state: dict[str, Any],
        *,
        screenshot_path: str | None = None,
        collision_ascii: str | None = None,
    ) -> PlayerObservation:
        player = state.get("player") or {}
        pos = player.get("position") or {}
        map_info = state.get("map") or {}
        dialog = state.get("dialog") or {}
        battle = state.get("battle")
        in_battle = bool(
            isinstance(battle, dict)
            and battle.get("in_battle")
            and (battle.get("type") not in {None, "none", ""})
        )
        meta = state.get("metadata") or {}
        map_name = map_info.get("map_name") or pos.get("map_name")
        map_id = map_info.get("map_id")
        if map_id is None:
            map_id = pos.get("map_id")
        joy_ignore = int(dialog.get("joy_ignore") or 0)
        # pokemon-agent: dialog.active is joy_ignore bit 5 only.
        dialog_active = bool(dialog.get("active"))
        return PlayerObservation(
            screenshot_path=screenshot_path,
            map_name=map_name,
            map_id=map_id,
            x=pos.get("x"),
            y=pos.get("y"),
            facing=player.get("facing"),
            dialog_active=dialog_active,
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
            frame_count=meta.get("frame_count"),
            raw_player=player,
        )

    def peek_state(self) -> PlayerObservation:
        """Lightweight observe: /state only (no screenshot, no map ASCII)."""
        return self._observation_from_state(self._get_json("/state"))

    def observe(self) -> PlayerObservation:
        state = self._get_json("/state")
        collision = None
        try:
            r = self._client.get(f"{self.base_url}/map/ascii")
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").lower()
            if "json" in ctype:
                ascii_map = r.json()
                if isinstance(ascii_map, dict):
                    collision = ascii_map.get("map") or ascii_map.get("ascii")
                elif isinstance(ascii_map, str):
                    collision = ascii_map
            else:
                collision = r.text
        except (httpx.HTTPError, ValueError):
            collision = None

        shot_path = self.run_dir / "screenshots" / "latest.png"
        shot_path_str: str | None
        try:
            self.screenshot(str(shot_path))
            # After load/fade the LCD can be blank; nudge once if needed.
            try:
                from PIL import Image

                extrema = Image.open(shot_path).getextrema()
                flat = all(
                    isinstance(ch, tuple) and ch[0] == ch[1] for ch in extrema[:3]
                )
                if flat:
                    self._post_json("/action", {"actions": ["wait_60"]})
                    self.screenshot(str(shot_path))
            except Exception:
                pass
            shot_path_str = str(shot_path)
        except httpx.HTTPError:
            shot_path_str = None

        return self._observation_from_state(
            state,
            screenshot_path=shot_path_str,
            collision_ascii=collision if isinstance(collision, str) else None,
        )

    def screenshot(self, path: str | None = None) -> bytes:
        r = self._client.get(f"{self.base_url}/screenshot")
        r.raise_for_status()
        data = r.content
        if path:
            Path(path).write_bytes(data)
        return data

    def _joy_ignore(self) -> int:
        try:
            dialog = (self._get_json("/state").get("dialog") or {})
            return int(dialog.get("joy_ignore") or 0)
        except (httpx.HTTPError, TypeError, ValueError):
            return 0

    def _mash_dialog_once(self) -> None:
        self._post_json("/action", {"actions": ["hold_b_120", "press_a"]})
        if self.press_interval_s > 0:
            time.sleep(min(self.press_interval_s, 0.05))

    def execute_skip_dialog(self, *, max_rounds: int = 30) -> PlayerObservation:
        """Mash B+A through narrative text until naming or dialog lock clears."""
        max_rounds = max(1, int(max_rounds))
        for _ in range(max_rounds):
            joy = self._joy_ignore()
            if is_naming_lock(joy):
                break
            self._mash_dialog_once()
            new_joy = self._joy_ignore()
            if is_naming_lock(new_joy):
                break
            # Text lock cleared → decision frame (menu / overworld / battle).
            if is_dialog_lock(joy) and not is_dialog_lock(new_joy):
                break
        return self.observe()

    def wait_until_input_ready(
        self,
        *,
        timeout_s: float = 3.0,
        auto_advance_dialog: bool = True,
        poll_wait_action: str = "wait_30",
        skip_dialog_max_rounds: int = 30,
    ) -> PlayerObservation:
        """Wait until the agent can act; auto-skip pure text locks.

        Joy mask:
        - bit 5 (0x20): narrative text → orchestrator mash B+A (no LLM)
        - bit 6 (0x40): naming keyboard → prompt immediately
        - other nonzero: short wait, then prompt (do not spin 20s)
        - zero: prompt
        """
        deadline = time.time() + max(0.1, float(timeout_s))
        advanced = 0
        max_skip = max(1, int(skip_dialog_max_rounds))
        while time.time() < deadline:
            joy = self._joy_ignore()
            if is_naming_lock(joy):
                obs = self.observe()
                obs.input_ready = True
                return obs
            if joy == 0:
                obs = self.observe()
                obs.input_ready = True
                return obs
            if auto_advance_dialog and is_dialog_lock(joy):
                self._mash_dialog_once()
                advanced += 1
                if advanced >= max_skip:
                    break
                continue
            # Cutscene / fade / unknown lock — brief wait only.
            try:
                self._post_json("/action", {"actions": [poll_wait_action]})
            except httpx.HTTPError:
                time.sleep(0.05)
        obs = self.observe()
        obs.input_ready = agent_can_act(self._joy_ignore())
        return obs

    def execute(self, actions: list[GameAction]) -> ActionResult:
        # Mid-burst uses peek_state (no screenshot). Full observe once at end
        # (or after skip_dialog, which already observes).
        # Expand walk_*_N macros into single-tile walks for the emu API.
        actions = expand_actions(actions)
        before = self.peek_state()
        executed: list[GameAction] = []
        stopped: str | None = None
        need_full_observe = True
        for i, action in enumerate(actions):
            if action == GameAction.SKIP_DIALOG:
                after = self.execute_skip_dialog()
                executed.append(action)
                need_full_observe = False
                if is_naming_lock(after.joy_ignore):
                    stopped = "naming_screen"
                    before = after
                    break
                if after.in_battle and not before.in_battle:
                    stopped = "battle_started"
                    before = after
                    break
                if (
                    after.map_name
                    and before.map_name
                    and after.map_name != before.map_name
                ):
                    stopped = "map_transition"
                    before = after
                    break
                before = after
                if self.press_interval_s > 0 and i + 1 < len(actions):
                    time.sleep(self.press_interval_s)
                continue

            self._post_json("/action", {"actions": [action.value]})
            executed.append(action)
            after = self.peek_state()
            if after.dialog_active and not before.dialog_active:
                stopped = "dialog_started"
                before = after
                break
            if after.in_battle and not before.in_battle:
                stopped = "battle_started"
                before = after
                break
            if (
                after.map_name
                and before.map_name
                and after.map_name != before.map_name
            ):
                stopped = "map_transition"
                before = after
                break
            before = after
            if self.press_interval_s > 0 and i + 1 < len(actions):
                time.sleep(self.press_interval_s)
        if need_full_observe:
            before = self.observe()
        return ActionResult(
            executed=executed,
            stopped_early_because=stopped,
            observation=before,
        )

    def get_control(self) -> ControlState:
        try:
            data = self._get_json("/control")
        except httpx.HTTPError:
            return ControlState.RUNNING
        state = (data.get("state") or data.get("status") or "running").lower()
        if state in {"paused", "pause"}:
            return ControlState.PAUSED
        if state in {"stopped", "stop"}:
            return ControlState.STOPPED
        return ControlState.RUNNING

    def set_control(self, state: ControlState) -> None:
        try:
            self._post_json("/control", {"state": state.value})
        except httpx.HTTPError:
            # Older servers may not support control; ignore.
            return

    def push_event(
        self,
        kind: str,
        text: str,
        *,
        category: str | None = None,
    ) -> None:
        """Push narration to the Field Log dashboard.

        pokemon-agent expects:
          reasoning | decision | alert  -> text
          key_moment                    -> description (+ optional category)
          action                        -> text (also replayed)
        """
        aliases = {
            "thinking": "reasoning",
            "thought": "reasoning",
            "narration": "reasoning",
            "milestone": "key_moment",
            "moment": "key_moment",
        }
        event_type = aliases.get(kind, kind)
        if event_type == "key_moment":
            payload: dict[str, Any] = {
                "type": "key_moment",
                "description": text,
                "category": category or "milestone",
            }
        else:
            payload = {"type": event_type, "text": text}
        try:
            self._post_json("/event", payload)
        except httpx.HTTPError:
            return

    def set_objectives(self, objectives: list[dict]) -> None:
        # Normalize to pokemon-agent Objective shape.
        normalized: list[dict[str, Any]] = []
        tiers = ["primary", "secondary", "tertiary"]
        for i, obj in enumerate(objectives[:3]):
            if "tier" in obj and "text" in obj:
                normalized.append(
                    {
                        "tier": obj["tier"],
                        "text": obj["text"],
                        "done": bool(obj.get("done", False)),
                    }
                )
            else:
                normalized.append(
                    {
                        "tier": tiers[i],
                        "text": str(obj.get("label") or obj.get("text") or obj),
                        "done": bool(obj.get("done", False)),
                    }
                )
        try:
            self._post_json("/objectives", {"objectives": normalized})
        except httpx.HTTPError:
            return

    def close(self) -> None:
        self._client.close()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
