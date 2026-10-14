"""Atomic owned-roster reads for the verified Red Star layout; never write memory."""

from nuzlocke.environment.surge import supported_rom


def read_storage(emu, party):
    from pokemon_agent.memory.red import GEN1_ENCODING, MOVE_NAMES, TYPE_NAMES, species_name_from_index

    if not supported_rom(str(getattr(emu, "rom_path", ""))):
        return {"complete": False, "reason": "Storage layout is not verified for this ROM", "boxes": []}
    current = emu.read_u8(0xD5A0)
    active = current & 0x7F
    if active >= 12:
        return {"complete": False, "reason": "Invalid active box", "boxes": []}

    def enrich(mon, raw):
        mon["dvs"] = [raw[27] >> 4, raw[27] & 15, raw[28] >> 4, raw[28] & 15]
        mon["stat_exp"] = [int.from_bytes(raw[i : i + 2], "big") for i in range(17, 27, 2)]
        return mon

    for i, mon in enumerate(party):
        enrich(mon, emu.read_range(0xD16B + 44 * i, 33))
    boxes = []
    for box in range(12):
        raw = (
            emu.read_range(0xDA80, 1122)
            if box == active
            else bytes(emu._pyboy.memory[2 + box // 6, 0xA000 + (box % 6) * 1122 : 0xA000 + (box % 6 + 1) * 1122])
        )
        count = raw[0] if box == active or current & 0x80 else 0
        if count > 20 or (count and raw[count + 1] != 0xFF):
            return {"complete": False, "reason": f"Invalid box {box + 1}", "boxes": []}
        mons = []
        for slot in range(count):
            d = raw[22 + slot * 33 : 55 + slot * 33]
            species = species_name_from_index(d[0])
            if d[0] != raw[slot + 1] or not species or "?" in species or not 1 <= d[3] <= 100:
                return {"complete": False, "reason": "Invalid boxed Pokémon", "boxes": []}
            nick = raw[902 + slot * 11 : 913 + slot * 11]
            name = "".join(GEN1_ENCODING.get(b, "?") for b in nick.split(b"\x50", 1)[0])
            mons.append(
                enrich(
                    {
                        "box": box + 1,
                        "slot": slot,
                        "species": species,
                        "nickname": name,
                        "level": d[3],
                        "ot_id": int.from_bytes(d[12:14], "big"),
                        "types": list(dict.fromkeys(TYPE_NAMES.get(t, "Unknown") for t in d[5:7])),
                        "moves": [
                            {"id": d[8 + i], "name": MOVE_NAMES.get(d[8 + i], "UNKNOWN"), "pp": d[29 + i] & 63}
                            for i in range(4)
                            if d[8 + i]
                        ],
                    },
                    d,
                )
            )
        boxes.append({"box": box + 1, "members": mons})
    return {"complete": True, "active_box": active + 1, "boxes": boxes}


def boxed(obs):
    return [m for box in (obs.storage or {}).get("boxes", []) for m in box["members"]]
