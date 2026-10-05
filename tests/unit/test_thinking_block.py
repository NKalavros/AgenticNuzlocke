"""Exercise the served Field Log renderer, including live and replay event shapes."""

import shutil
import subprocess

import pytest

from nuzlocke.environment.dashboard import field_log_script


def test_reasoning_updates_share_one_block_until_the_action_decision(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the Field Log renderer test")
    source = field_log_script()
    # Export the real renderer and skip timers/network/UI initialization below it.
    source = source.replace(
        "    // ---- screenshot ----",
        "    globalThis.render = renderEvent; return;\n    // ---- screenshot ----",
    )
    script = tmp_path / "field-log.js"
    script.write_text(source)
    test = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
class Element {
    constructor(tag) { this.tag=tag; this.children=[]; this.style={}; this.isConnected=true; this.textContent=''; }
    appendChild(child) { this.children.push(child); return child; }
    removeChild(child) { this.children.splice(this.children.indexOf(child),1); child.isConnected=false; }
    get firstChild() { return this.children[0]; }
    querySelector(selector) { return this.children.find(c=>'.'+c.className===selector); }
}
const elements = new Map();
global.document = {
    getElementById(id) { if(!elements.has(id)) elements.set(id,new Element('div')); return elements.get(id); },
    createElement(tag) { return new Element(tag); },
    createTextNode(text) { const e=new Element('#text'); e.textContent=text; return e; }
};
global.window = {location:{protocol:'http:',host:'localhost'}};
global.setInterval = ()=>{};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const log = document.getElementById('logContainer');
render({type:'reasoning',text:'[director] Fast route → overworld (vision-only).'});
render({type:'reasoning',text:'[director] mode=battle owner=battle → Fight'});
render({type:'reasoning',text:'[cursor] context≈2000 tokens'});
assert.equal(log.children.length,0);
render({type:'reasoning',text:'[director] thinking...'});
render({type:'reasoning',data:{text:'[director] compare moves'}});
render({type:'state_update',state:{}});
render({type:'thought',text:'<script>literal text</script>'});
assert.equal(log.children.length,1);
assert.equal(log.children[0].className,'entry e-think');
const body=log.children[0].querySelector('.e-body');
assert.equal(body.children.at(-1).textContent,'thinking... compare moves <script>literal text</script>');
assert(!body.children.at(-1).textContent.includes('[director]'));
render({type:'decision',data:{text:'Use Confusion'}});
render({type:'action',actions:['press_a']});
render({type:'reasoning',text:'[director] next turn'});
assert.equal(log.children.filter(c=>c.className==='entry e-think').length,2);
render({type:'action',actions:['walk_down']});
render({type:'reasoning',text:'[director] after action with no decision event'});
assert.equal(log.children.filter(c=>c.className==='entry e-think').length,3);
// Clearing/replaying history must not append into a detached old block.
while(log.children.length) log.removeChild(log.firstChild);
render({type:'reasoning',data:{text:'replay begins'}});
render({type:'reasoning',data:{text:'replay continues'}});
assert.equal(log.children.length,1);
render({type:'decision',text:'next'});
render({type:'reasoning',text:'[director] thinking with model…'});
const stream=log.children.at(-1).querySelector('.e-body');
render({type:'reasoning',text:'[director:thinking] Use'});
render({type:'reasoning',text:'[director:thinking] Use Tackle.\nThe opponent is weakened.'});
assert.equal(stream.children.at(-1).textContent,'Use Tackle.\nThe opponent is weakened.');
render({type:'reasoning',text:'[director] {"moves":["TACKLE"]}'});
assert.equal(stream.children.at(-1).textContent,'Use Tackle.\nThe opponent is weakened.');
"""
    subprocess.run([node, "-e", test, str(script)], check=True, capture_output=True, text=True)
