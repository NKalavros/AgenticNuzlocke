"""NousResearch pokemon-agent HTTP adapter (Pokemon Red)."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from nuzlocke.environment import screen
from nuzlocke.environment.base import ActionResult
from nuzlocke.environment.joypad import (
    agent_can_act,
    is_naming_lock,
)
from nuzlocke.environment.macros import (
    drop_naming_confirm_if_walking,
    expand_actions,
)
from nuzlocke.state.models import ControlState, GameAction, PlayerObservation

# Gen 1: a single directional press only turns the sprite when the player
# isn't already facing that way — moving a tile takes a second press in the
# same direction. Mechanical only (never exposed to the LLM, never gates
# whether/when to act) — it just makes `walk_X` reliably move a tile.
_WALK_DIRECTIONS = {
    GameAction.WALK_UP: "up",
    GameAction.WALK_DOWN: "down",
    GameAction.WALK_LEFT: "left",
    GameAction.WALK_RIGHT: "right",
}


# Red Star reports joy_ignore=0 during real dialog, so the old RAM-based exit
# could never fire: every mash ran all its rounds and ended on A, which
# re-opens the NPC it just finished. Rounds are now B-only and stop when the
# text box stops changing (see execute_skip_dialog).
SKIP_DIALOG_MAX_ROUNDS = 6
# Consecutive rounds with an unchanged text-box region before we call it done.
SKIP_DIALOG_STABLE_ROUNDS = 2


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
        self.auto_start = auto_start
        self.speed = speed
        self.press_interval_s = max(0.0, float(press_interval_s))
        self.load_state = load_state
        # Local emulator. Ignore HTTP(S)_PROXY / ALL_PROXY so a dev proxy
        # cannot turn /health into a 503 and look like the server is down.
        self._client = httpx.Client(timeout=60.0, trust_env=False)
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
        if self.load_state and (data_dir / "saves" / f"{self.load_state}.state").exists():
            cmd += ["--load-state", self.load_state]
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

    def save_checkpoint(self, name: str) -> dict[str, Any]:
        """Crash-recovery only — never used to undo a committed outcome.

        pokemon-agent writes into a session-scoped folder whenever a
        dashboard "game session" is active, but /load always reads the flat
        saves/ dir — verify the save actually landed where /load will find
        it, and fail loudly rather than silently produce an unloadable
        checkpoint.
        """
        result = self._post_json("/save", {"name": name})
        saved = result.get("path")
        if saved:
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
        """Copy this run's savestate into the live server's flat saves dir.

        ``/load`` only reads that directory. A server started for another run
        would otherwise keep looking in its own folder.
        """
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
        data = self._get_json("/saves")
        return list(data.get("saves") or [])

    def _joy_ignore(self) -> int:
        try:
            dialog = (self._get_json("/state").get("dialog") or {})
            return int(dialog.get("joy_ignore") or 0)
        except (httpx.HTTPError, TypeError, ValueError):
            return 0

    def _dialog_digest(self) -> str | None:
        """Hash of the bottom-6-tile-row text-box region of the live frame."""
        try:
            return screen.digests_from_bytes(self.screenshot())[1]
        except (httpx.HTTPError, ValueError):
            return None

    def _mash_dialog_once(self) -> None:
        # B only. B advances Gen 1 text exactly like A does, but pressing B in
        # the overworld starts nothing — so a mash can never end by re-opening
        # the NPC, sign, or TV it just finished reading.
        self._post_json("/action", {"actions": ["hold_b_120"]})
        if self.press_interval_s > 0:
            time.sleep(min(self.press_interval_s, 0.05))

    def execute_skip_dialog(self, *, max_rounds: int = SKIP_DIALOG_MAX_ROUNDS) -> PlayerObservation:
        """Clear narrative text with B, stopping when the text box goes quiet.

        The old version mashed ``hold_b_120 + press_a`` and exited on a
        joy_ignore bit-5 transition. On Red Star that bit reads 0 through real
        dialog (AGENTS.md pitfall #1), so the exit never fired: all rounds ran
        and the final A re-opened the box. `skip_dialog` became a fixed point —
        33 minutes of it in run 20260821-164159-3c5a68.

        Termination is now visual and needs no RAM: hash the text-box region
        between rounds and stop once it stops changing. Naming lock (bit 6)
        stays as a guard — unlike bit 5, it was correct all run.
        """
        max_rounds = max(1, int(max_rounds))
        stable = 0
        previous = self._dialog_digest()
        for _ in range(max_rounds):
            if is_naming_lock(self._joy_ignore()):
                break
            self._mash_dialog_once()
            current = self._dialog_digest()
            if current is not None and current == previous:
                stable += 1
                if stable >= SKIP_DIALOG_STABLE_ROUNDS:
                    break
            else:
                stable = 0
            previous = current
        return self.observe()

    def _lock_transition_stop(
        self, before: PlayerObservation, after: PlayerObservation
    ) -> str | None:
        if is_naming_lock(after.joy_ignore):
            return "naming_screen"
        if after.in_battle and not before.in_battle:
            return "battle_started"
        if after.map_name and before.map_name and after.map_name != before.map_name:
            return "map_transition"
        return None

    @staticmethod
    def _d_pad_moves_sprite(obs: PlayerObservation) -> bool:
        """True when walk_* should turn-then-step the overworld sprite.

        On the naming grid / menus the same RAM facing is stale: a second
        walk_right would move the letter cursor two cells and overshoot END.
        """
        if obs.in_battle:
            return False
        if is_naming_lock(obs.joy_ignore):
            return False
        if int(obs.joy_ignore or 0) != 0:
            return False
        return True

    def execute(self, actions: list[GameAction]) -> ActionResult:
        # Mid-burst uses peek_state (no screenshot). Full observe once at end
        # (or after skip_dialog, which already observes).
        before = self.peek_state()
        # Mechanical naming split (same joy bit skip_dialog already trusts):
        # walks move the letter cursor; A in the same burst types junk.
        if is_naming_lock(before.joy_ignore):
            actions = drop_naming_confirm_if_walking(actions)
        actions = expand_actions(actions)
        executed: list[GameAction] = []
        stopped: str | None = None
        need_full_observe = True
        for i, action in enumerate(actions):
            # a_until_dialog_end is pokemon-agent's own opcode and it checks a
            # flat `dialog_active` key incorrectly (AGENTS.md pitfall #5), so it
            # either returns instantly or A-mashes an NPC forever. Serve it from
            # our own visually-terminated macro instead.
            if action in (GameAction.SKIP_DIALOG, GameAction.A_UNTIL_DIALOG_END):
                after = self.execute_skip_dialog()
                executed.append(action)
                need_full_observe = False
                stopped = self._lock_transition_stop(before, after) or "skip_dialog"
                before = after
                # Never walk/A after a mash in the same burst (re-opens TV).
                break

            direction = _WALK_DIRECTIONS.get(action)
            buttons = [action.value]
            if (
                direction
                and self._d_pad_moves_sprite(before)
                and before.facing
                and before.facing.lower() != direction
            ):
                # One /action with turn+step so Field Log shows a single ACT
                # (not two walk_rights) and the sprite actually leaves the tile.
                buttons = [action.value, action.value]
            self._post_json("/action", {"actions": buttons})
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
