"""Field Log telemetry overrides kept outside the installed pokemon-agent package."""

from pathlib import Path


def capture_count(ledger):
    """Successful wild catches, including boxed/dead Pokémon; no starter or evolutions."""
    from nuzlocke.knowledge.encounters import area_key

    return len(
        {area_key(int(area)) if str(area).isdigit() else area for area, entry in ledger.items() if entry.get("outcome") == "caught"}
    )


def field_log_script():
    from pokemon_agent.dashboard.mount import STATIC_DIR

    source = (STATIC_DIR / "app.js").read_text()
    old = """caught = party.length; // simple proxy; refined by key_moment catches
        $('ctrCaught').textContent=Math.max(caught, Number($('ctrCaught').textContent)||0);"""
    replacements = {
        old: "updateNuzlockeCaught(state);",
        "if(autoScroll) box.scrollTop=box.scrollHeight;\n    }": "if(autoScroll) box.scrollTop=box.scrollHeight;\n        return e;\n    }",
        "    function renderEvent(msg){": """    var thinkingBlock = createThinkingBlock(entry, function(){
        var box=$('logContainer');
        if(autoScroll) box.scrollTop=box.scrollHeight;
    });
    function renderEvent(msg){""",
        "        switch(type){": """        if(type==='decision' || type==='action') thinkingBlock.finish();
        switch(type){""",
        "entry('think','THINK', d.text||msg.text||''); break;": "thinkingBlock.append(d.text||msg.text||''); break;",
    }
    for before, after in replacements.items():
        if source.count(before) != 1:
            raise RuntimeError("pokemon-agent Field Log changed; review its telemetry override")
        source = source.replace(before, after)
    helper = Path(__file__).with_name("field_log.js").read_text()
    return helper + "\n" + source
