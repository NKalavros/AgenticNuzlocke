"""Event-driven team strategist; persistent intent, ordinary controller execution."""

import json
from copy import deepcopy

from nuzlocke.agents.battle import active_mon, move_facts, parse_battle
from nuzlocke.agents.calculations import comparisons
from nuzlocke.agents.gym_preparation import party_ready
from nuzlocke.agents.lead_rotation import LeadRotationError
from nuzlocke.agents.move_learning import HM, move_data, normalized
from nuzlocke.assets import data, text
from nuzlocke.environment.screen_text import find_boxes
from nuzlocke.environment.storage import boxed
from nuzlocke.knowledge import trainers
from nuzlocke.knowledge.beats import Beat
from nuzlocke.knowledge.walkthrough import compose, holds
from nuzlocke.llm.factory import create_provider
from nuzlocke.llm.settings import provider_identity
from nuzlocke.state.models import AgentRole, TeamPlan
from nuzlocke.state.models import GameAction as A


def roster(obs):
    return [*obs.party, *boxed(obs)]


def team_signature(obs):
    return [[m.get("capture_id"), m.get("species"), m.get("level"), [v.get("id") for v in m.get("moves", [])]] for m in obs.party]


class System4:
    def __init__(self):
        self.state = {"job": None, "deaths": [], "completed": [], "in_battle": False, "epoch": 0}
        self.llm = None

    def snapshot(self):
        return deepcopy(self.state)

    def restore(self, state):
        if state:
            self.state.update(deepcopy(state))

    def observe(self, obs, loop):
        s = self.state
        deaths = [m.get("capture_id") or m.get("nickname") for m in loop.referee.death_ledger]
        fresh = any(d not in s["deaths"] for d in deaths)
        s["deaths"] = deaths
        job = s["job"]
        for c in data("walkthrough/challenges_red.json"):
            if c["id"] not in s["completed"] and (holds(obs, c["complete_item"], "") or obs.map_id in c.get("complete_maps", [])):
                s["completed"].append(c["id"])
        if job and (job.get("badge") in obs.badges or job["id"] in s["completed"]):
            loop.store.append("system4_complete", {"id": job["id"]})
            s["job"] = job = None
        gym = obs.policy.get("gym_preparation")
        if not job and (gym or fresh) and obs.party:
            job = {
                "id": gym["badge"] if gym else "death_recovery",
                "name": gym["name"] if gym else "Rebuild the surviving team",
                "center": gym["center"] if gym else None,
                "map": gym["gym"] if gym else None,
                "badge": gym["badge"] if gym else None,
            }
        if not job and not obs.in_battle and not find_boxes(obs.screen_rows):
            job = next(
                (
                    deepcopy(c)
                    for c in data("walkthrough/challenges_red.json")
                    if c["map"] == obs.map_id and c["badges"] == len(obs.badges) and c["id"] not in s["completed"]
                ),
                None,
            )
        if job and "phase" not in job:
            job.update(
                phase="review",
                plan=None,
                reason="recorded death" if fresh else "major challenge",
                name=job.get("name", job.get("trainer")),
                consumed={},
            )
            loop.store.append("system4_trigger", job)
        if fresh and job:
            job.update(phase="review", plan=None, reason="recorded death", consumed={}, rebuild_after_battle=obs.in_battle)
        if s["in_battle"] and not obs.in_battle and job:
            rebuild = job.pop("rebuild_after_battle", False)
            if job.pop("review_after_battle", False) or rebuild:
                job.update(phase="review", plan=job.pop("preparation_plan", None), reason="post-battle replacement")
        enemy = (obs.battle or {}).get("enemy") or {}
        old = s.get("enemy") or {}
        if obs.in_battle and (
            not s["in_battle"] or enemy.get("species") != old.get("species") or old.get("hp") == 0 and enemy.get("hp", 0) > 0
        ):
            s["epoch"] += 1
        if job and s.get("opening"):
            identity, mid, pp, line = s["opening"]
            mon = next((m for m in obs.party if m.get("capture_id") == identity), {})
            now = next((m.get("pp") for m in mon.get("moves", []) if m.get("id") == mid), None)
            if now is not None and now < pp:
                job["consumed"][line] = job["consumed"].get(line, 0) + 1
                s["opening"] = None
                loop.store.append("system4_opener_used", {"capture_id": identity, "move": mid, "line": line})
        s.update(job=job, in_battle=obs.in_battle, enemy=deepcopy(enemy))
        self.annotate(obs)

    def annotate(self, obs):
        job = self.state["job"]
        obs.policy["system4"] = deepcopy(job)
        obs.policy.pop("team_plan", None)
        if job and job.get("plan"):
            obs.policy["team_plan"] = job["plan"]
        obs.policy["strategic_battle"] = self.owns_battle(obs)

    def owns_battle(self, obs):
        job = self.state["job"]
        return bool(job and obs.in_battle and ((obs.battle or {}).get("type") == "trainer" or job.get("rebuild_after_battle")))

    def review(self, loop, obs, reason):
        job = self.state["job"]
        if not obs.in_battle and not (obs.storage or {}).get("complete"):
            raise LeadRotationError("System 4 requires a verified full owned roster")
        options = loop.agents_cfg["system4"]
        identity = provider_identity(options)
        if self.llm is None:
            self.llm = create_provider(
                loop.agents_cfg,
                loop.run_dir / "system4_workspace",
                role="system4",
                on_stream=lambda t: loop.env.push_event("reasoning", "[system4] " + t),
            )
        entry = next((t for t in trainers.trainers() if t["trainer"] == job["name"]), {})
        enemies = [
            {
                "species": n,
                "level": lv,
                "moves": [
                    {"id": mid, "name": move_data().get(mid, {}).get("name", str(mid))}
                    for mid in (entry.get("reference_moves") or [[]] * len(entry.get("team", [])))[i]
                ],
            }
            for i, (n, lv) in enumerate(entry.get("team", []))
        ]
        if obs.in_battle:
            visible = (obs.battle or {}).get("enemy") or {}
            reference = next((e for e in enemies if e["species"] == visible.get("species")), {})
            enemies = [{**visible, "moves": reference.get("moves", [])}]
        guidance = compose(
            job.get("section")
            or {"Boulder": "brock", "Cascade": "misty", "Thunder": "surge.gym", "Rainbow": "erika.gym", "Soul": "koga.gym"}.get(
                job.get("badge"), "rules"
            ),
            "rules",
            "team",
        )
        payload = {
            "reason": reason,
            "challenge": job["name"],
            "cap": loop.referee.current_cap,
            "party": obs.party,
            "owned": roster(obs),
            "bag": obs.bag,
            "in_battle": obs.in_battle,
            "active": active_mon(obs),
            "enemy": (obs.battle or {}).get("enemy"),
            "walkthrough": guidance,
            "comparisons": comparisons(roster(obs), enemies, None if obs.in_battle else loop.referee.current_cap),
            "previous_plan": job.get("plan"),
            "rejected_moves": job.get("rejected_moves", []),
            "teaching_items": data("walkthrough/teaching_red.json"),
            "learnsets": {
                m["species"]: data("walkthrough/species_red.json")["species"].get(m["species"].upper(), {}) for m in roster(obs)
            },
            "move_reference": {m["id"]: move_data().get(m["id"]) for mon in roster(obs) for m in mon.get("moves", [])},
        }
        result = self.llm.complete(
            role=AgentRole.STRATEGIST,
            system=text("prompts/system4.md"),
            user=json.dumps(payload),
            schema_hint=TeamPlan.model_json_schema(),
        )
        plan = TeamPlan.model_validate(result.parsed or json.loads(result.raw_text))
        self.validate(plan, obs, loop.referee.current_cap)
        mons = {m["capture_id"]: m for m in roster(obs)}
        plan.levels = {i: plan.levels.get(i, mons[i]["level"]) for i in plan.party}
        if any(str(mid) in plan.model_dump(mode="json")["learn"].get(cid, {}) for cid, mid in job.get("rejected_moves", [])):
            raise LeadRotationError("System 4 repeated a rejected teaching request")
        value = plan.model_dump(mode="json")
        if obs.in_battle:
            if not job.get("review_after_battle"):
                job["preparation_plan"] = deepcopy(job.get("plan"))
            job["review_after_battle"] = True
        ready = (
            obs.in_battle
            or reason == "preparation verified"
            and set(plan.party) == {m["capture_id"] for m in obs.party}
            and obs.party[0]["capture_id"] == plan.lead
            and all(
                m["level"] >= plan.levels.get(m["capture_id"], m["level"])
                and all(mid in {v["id"] for v in m.get("moves", [])} for mid in plan.learn.get(m["capture_id"], {}))
                for m in obs.party
            )
        )
        job.update(
            plan=value,
            provider=identity,
            reason=reason,
            phase="ready" if ready else "roster",
            signature=team_signature(obs),
            consumed={},
        )
        loop.store.append("system4_plan", {**job, "usage": result.usage})
        loop.env.push_event("reasoning", f"[system4] {plan.reasoning}")
        self.annotate(obs)

    @staticmethod
    def validate(plan, obs, cap):
        mons = {m.get("capture_id"): m for m in roster(obs)}
        if len(set(plan.party)) != len(plan.party) or plan.lead not in plan.party:
            raise LeadRotationError("System 4 returned an invalid party/lead")
        if any(i not in mons or mons[i].get("dead") or mons[i].get("ineligible") for i in plan.party):
            raise LeadRotationError("System 4 selected an unavailable or ineligible Pokémon")
        if obs.in_battle and set(plan.party) != {
            m["capture_id"] for m in obs.party if not m.get("dead") and not m.get("ineligible")
        }:
            raise LeadRotationError("System 4 cannot change the party during battle")
        if any(
            i not in plan.party or (lv != mons[i]["level"] if obs.in_battle else lv < mons[i]["level"] or lv > cap)
            for i, lv in plan.levels.items()
        ):
            raise LeadRotationError("System 4 level target violates the cap or observed level")
        needed = {mv["id"] for m in obs.party if not m.get("dead") for mv in m.get("moves", []) if mv.get("id") in HM}
        retained = {mv["id"] for i in plan.party for mv in mons[i].get("moves", [])}
        if not obs.in_battle and not needed <= retained:
            raise LeadRotationError("System 4 would remove a living field-move user")
        if not set(plan.party) <= {line.active for line in plan.lines}:
            raise LeadRotationError("System 4 omitted battle lines for a selected Pokémon")
        for i, moves in plan.learn.items():
            if i not in plan.party or any(new not in move_data() or old in HM for new, old in moves.items()):
                raise LeadRotationError("Invalid planned move replacement")
            available = {
                int(data("walkthrough/teaching_red.json").get(str(v.get("id")), 0)) for v in obs.bag if v.get("quantity", 0) > 0
            }
            learned = data("walkthrough/species_red.json")["species"].get(mons[i]["species"].upper(), {}).get("learnset", [])
            available |= {mid for lv, mid in learned if mons[i]["level"] < lv <= plan.levels.get(i, mons[i]["level"])}
            available |= {m["id"] for m in mons[i].get("moves", [])}
            if any(
                new not in available or old and old not in {m["id"] for m in mons[i].get("moves", [])} for new, old in moves.items()
            ):
                raise LeadRotationError("Planned move or replacement is unavailable")
        for line in plan.lines:
            if (
                line.active not in plan.party
                or line.strategy.switch_to
                and (line.strategy.switch_to not in plan.party or line.strategy.switch_to == line.active)
            ):
                raise LeadRotationError("Battle line names an unavailable Pokémon")
            known = {normalized(m["name"]) for m in mons[line.active].get("moves", [])}
            planned = {normalized(move_data()[i]["name"].removesuffix("_M")) for i in plan.learn.get(line.active, {})}
            if any(normalized(m) not in known | planned for m in [*line.strategy.moves, *line.strategy.opening_moves]):
                raise LeadRotationError("Battle line uses an unknown move")

    def battle_plan(self, obs):
        job = self.state["job"]
        if not job or not job.get("plan") or not self.owns_battle(obs):
            return None
        mon, enemy = active_mon(obs), (obs.battle or {}).get("enemy") or {}
        if mon.get("dead") or mon.get("ineligible"):
            return {"switch_to": job["plan"]["lead"], "switch_below": 1.0, "moves": [], "opening_moves": []}
        for i, line in enumerate(job["plan"]["lines"]):
            if (
                line["active"] != mon.get("capture_id")
                or line["enemy"] != "*"
                and normalized(line["enemy"]) != normalized(enemy.get("species"))
            ):
                continue
            if (
                mon.get("hp", 0) / (mon.get("max_hp") or 1) >= line["hp_below"]
                or line["enemy_status"]
                and enemy.get("status", "UNKNOWN") not in line["enemy_status"]
            ):
                continue
            key = f"{self.state['epoch']}:{i}"
            plan = deepcopy(line["strategy"])
            if plan.get("switch_below") == 1.0:
                plan["switch_below"] = 1.01
            plan["opening_moves"] = plan["opening_moves"][job["consumed"].get(key, 0) :]
            switching = plan.get("switch_to") and mon.get("hp", 0) / (mon.get("max_hp") or 1) < plan.get("switch_below", 0)
            target = next((m for m in obs.party if m.get("capture_id") == plan.get("switch_to")), {})
            if switching and (
                target.get("dead")
                or target.get("ineligible")
                or target.get("hp", 0) / (target.get("max_hp") or 1) < line.get("switch_min_hp", 0.5)
            ):
                continue
            if not switching and not any(
                not move_facts(obs, m["name"], plan=plan)["unavailable_reason"] for m in mon.get("moves", [])
            ):
                continue
            opening = plan["opening_moves"]
            move = next((m for m in mon.get("moves", []) if opening and normalized(m["name"]) == normalized(opening[0])), None)
            self.state["opening"] = [mon.get("capture_id"), move["id"], move["pp"], key] if move else None
            return {**plan, "source": "system4", "intent": job["plan"]["reasoning"], "do_not": []}
        return None

    def turn(self, loop, obs):
        job = self.state["job"]
        if not job or loop.referee.wiped:
            return [], ""
        from nuzlocke.environment.evolution import evolution_phase

        if evolution_phase(obs.screen_rows):
            return [], ""
        if not obs.in_battle and job["phase"] == "review" and find_boxes(obs.screen_rows):
            return [A.PRESS_B], "close menus before System 4 review"
        if job.get("provider") and job["provider"] != provider_identity(loop.agents_cfg["system4"]):
            job.update(phase="review", plan=None, reason="System 4 provider changed")
        if obs.in_battle:
            from nuzlocke.agents.battle import party_cursor

            if (
                self.owns_battle(obs)
                and (parse_battle(obs.screen_rows).kind or party_cursor(obs) is not None)
                and (job["plan"] is None or self.battle_plan(obs) is None)
            ):
                self.review(loop, obs, "battle line unavailable")
                if self.battle_plan(obs) is None:
                    raise LeadRotationError("System 4 supplied no applicable battle line")
            return [], ""
        if job["phase"] == "review":
            self.review(loop, obs, job["reason"])
        plan = job["plan"]
        ids = [m["capture_id"] for m in obs.party]
        if job["phase"] == "ready":
            if team_signature(obs) != job.get("signature"):
                job["phase"] = "review"
            return [], ""
        if loop._preparing_target or loop._closing_preparation:
            job["phase"] = "levels"
            return [], ""
        from nuzlocke.agents.system3 import HEALING_CENTERS, needs_heal

        if needs_heal(obs) and not loop.storage.pending and not loop.storage.closing:
            return [], ""
        if set(ids) != set(plan["party"]) or loop.storage.pending or loop.storage.closing:
            job["phase"] = "roster"
            if obs.map_id in HEALING_CENTERS and (obs.x, obs.y) == (13, 4):
                return loop.storage.turn(obs, plan["party"], loop.store.append)
            return [], ""
        if not party_ready(obs):
            job["phase"] = "heal"
            return [], ""
        if any(m["level"] < plan["levels"].get(m["capture_id"], m["level"]) for m in obs.party):
            job["phase"] = "levels"
            return [], ""
        teaching = {int(item): mid for item, mid in data("walkthrough/teaching_red.json").items()}
        for mon in obs.party:
            missing = [
                int(mid)
                for mid in plan["learn"].get(mon["capture_id"], {})
                if int(mid) not in [m["id"] for m in mon.get("moves", [])]
            ]
            if missing:
                item = next((i for i in obs.bag if i.get("quantity", 0) > 0 and teaching.get(i.get("id")) == missing[0]), None)
                if not item:
                    job.setdefault("rejected_moves", []).append([mon["capture_id"], missing[0]])
                    job.update(phase="review", reason="Planned move unavailable after leveling")
                    return [A.WAIT_60], job["reason"]
                job.update(phase="moves", teaching={"capture_id": mon["capture_id"], "item": item["item"], "move": missing[0]})
                from nuzlocke.agents.inventory import teaching_actions

                self.annotate(obs)
                try:
                    return teaching_actions(obs) or [A.WAIT_60], "System 4: teach planned move"
                except ValueError as err:
                    job.setdefault("rejected_moves", []).append([mon["capture_id"], missing[0]])
                    job.update(phase="review", reason=str(err))
                    job.pop("teaching", None)
                    return [A.PRESS_B], str(err)
        job.pop("teaching", None)
        if loop.lead_rotation.pending:
            return loop.lead_rotation.turn(obs, record=loop.store.append, target=plan["lead"])
        if find_boxes(obs.screen_rows):
            return [A.PRESS_B], "close team preparation menus"
        if ids[0] != plan["lead"]:
            return loop.lead_rotation.turn(obs, record=loop.store.append, target=plan["lead"])
        self.review(loop, obs, "preparation verified")
        if job["id"] == "death_recovery" and job["phase"] == "ready":
            self.state["job"] = None
        return [], ""


def team_beat(obs):
    job = obs.policy.get("system4")
    if not job or obs.in_battle or job["phase"] == "ready":
        return None
    from nuzlocke.agents.system3 import HEALING_CENTERS, heal_beat

    if obs.map_id not in HEALING_CENTERS:
        hurt = obs.model_copy(update={"party": [{**m, "hp": 1} for m in obs.party if not m.get("dead")]})
        return heal_beat(hurt)
    plan = job.get("plan") or {}
    target = (
        {"kind": "face", "x": 13, "y": 4, "dir": "up"}
        if job["phase"] == "roster" and set(plan.get("party", [])) != {m.get("capture_id") for m in obs.party}
        else None
    )
    if job["phase"] == "heal":
        return Beat(
            "heal_team",
            "Heal the selected team.",
            "Use the nurse and verify HP, status and PP.",
            target={"kind": "face", "x": 3, "y": 3, "dir": "up"},
        )
    return Beat(
        "prepare_team",
        f"Prepare the team for {job['name']} ({job['phase']}).",
        plan.get("reasoning", "System 4 reviews the owned roster."),
        target=target,
    )
