// Wild catches are cumulative ledger outcomes, independent of party size or PC moves.
function updateNuzlockeCaught(state) {
    const counter = document.getElementById('ctrCaught');
    const count = state.nuzlocke?.caught;
    counter.textContent = Number.isInteger(count) && count >= 0 ? String(count) : '—';
    counter.title = 'Successful wild captures this run, including Pokémon sent to the PC. Excludes the starter; evolutions do not add catches.';
}

// All reasoning updates belong to one block until an action is selected/executed.
// The raw events remain separate in history; live rendering and history replay use this alike.
function createThinkingBlock(entry, scroll) {
    let current = null, content = null, textSoFar = '', beforeStream = '', streaming = false;
    function reset() { current = null; content = null; textSoFar = ''; beforeStream = ''; streaming = false; }
    return {
        append(text) {
            if (!text) return;
            const tagged = text.match(/^\[([^\]]+)\]\s*([\s\S]*)$/);
            const source = tagged ? tagged[1] : '';
            text = tagged ? tagged[2] : text;
            // Deterministic routing and token bookkeeping aren't model thinking.
            if (source === 'cursor' || source === 'checkpoint' || source === 'memory') return;
            if (source === 'director' && /^(Fast route →|Battle detected [—-] routing|mode=)/.test(text)) return;
            const snapshot = source.endsWith(':thinking');
            const starting = /^thinking with .+…$/.test(text);
            // Older providers send their final JSON response through this same channel.
            if (/^\s*(?:```(?:json)?\s*)?\{/.test(text)) return;
            if (current && !current.isConnected) reset();
            if (starting) {
                beforeStream = textSoFar;
                streaming = false;
            } else if (snapshot) {
                if (!streaming) beforeStream = textSoFar;
                textSoFar = beforeStream + (beforeStream ? '\n\n' : '') + text;
                streaming = true;
            } else {
                if (textSoFar.endsWith(text)) return;
                // Legacy chunks are fragments: don't put every fragment on a new line.
                textSoFar += (textSoFar ? (streaming ? '\n\n' : ' ') : '') + text;
                streaming = false;
            }
            if (!current || !current.isConnected) {
                current = entry('think', 'THINK', '');
                const body = current.querySelector('.e-body');
                body.style.whiteSpace = 'pre-wrap';
                body.style.maxHeight = '18rem';
                body.style.overflowY = 'auto';
                content = document.createTextNode('');
                body.appendChild(content);
            }
            content.textContent = textSoFar || 'Thinking…';
            scroll();
        },
        finish() { reset(); }
    };
}
