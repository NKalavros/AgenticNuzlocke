## 8. Route 3 / Mt. Moon / Cerulean

- Route 3 connects NORTH to western Route 4, at boundary tiles `(57..61, 0)` in the vanilla layout. It has no east connection. Use `navigation.reference_map.desired_exit` and the full reference layout; do not search the east wall or rediscover known exits. Live movement and map tables override mismatches in the vanilla reference.
- Resolve Route 3 before entering Mt. Moon. Western Route 4 has no reachable grass; its encounter waits until the eastern side after the cave.
- Mt. Moon has one encounter across all three floors. Use the current ROM's land table and reachable cave floor; do not seek a second catch downstairs.
- Vanilla route hints: 1F northwest ladder (5,5), B1F ladder (17,11), cross the main B2F room past the trainers/fossils to (5,7), then leave the separate B1F exit passage. These coordinates must match visible/observed warps; Red Star may differ.
- Cave floors can be separated by impassable elevation boundaries even when both cells read as floor. Use `terrain_blocked_edges` as well as tiles. Ladders sharing a destination map can belong to disconnected chambers: for healing from the main B2F area, use the reachable ladder `(21,17)` and then the B1F corridor to `(5,5)`; do not try to cross the boundary toward the isolated B2F ladder `(25,9)`.
- At the blocking fossil choice, select one fossil so the passage opens. Do not return to side chambers repeatedly.
- On Route 4, the eastern Mt. Moon exit is at (24,5). Continue east from that apron; do not return to the western cave entrance. Reach the eastern grass using `reference_map.ledge_jumps`: launch → landing is one way, so do not attempt to climb a drop in reverse. The measured (64,8) → (64,10) drop enters the grass.
- Resolve eastern Route 4 before Cerulean. Prepare at Cerulean Center to 19 (below the reserve band for Misty’s level-21 cap), resolve Route 24 and Route 25 through the northern bridge, then return to heal for the gym. The bridge rival is a trainer battle: System 2 plans it.
- Stop at the Cascade Badge only when configured to do so. For a continuation after Cascade, follow the Lt. Surge prerequisites below. Full-game completion remains unverified.
