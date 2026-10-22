// Core helpers, prepended to every bridge command. ES3: no JSON object, no
// Array.prototype.map/forEach, no trailing commas.
var SK = {};

SK.TICKS = 254016000000;

SK.quote = function (s) {
    var out = '"';
    for (var i = 0; i < s.length; i++) {
        var c = s.charAt(i), code = s.charCodeAt(i);
        if (c === '"') out += '\\"';
        else if (c === '\\') out += '\\\\';
        else if (c === '\n') out += '\\n';
        else if (c === '\r') out += '\\r';
        else if (c === '\t') out += '\\t';
        else if (code < 32 || code > 126) {
            var h = code.toString(16);
            out += '\\u' + '0000'.substring(h.length) + h;
        } else out += c;
    }
    return out + '"';
};

SK.json = function (v) {
    if (v === null || v === undefined) return 'null';
    var t = typeof v;
    if (t === 'number') return isFinite(v) ? String(v) : 'null';
    if (t === 'boolean') return v ? 'true' : 'false';
    if (t === 'string') return SK.quote(v);
    if (v instanceof Array) {
        var parts = [];
        for (var i = 0; i < v.length; i++) parts.push(SK.json(v[i]));
        return '[' + parts.join(',') + ']';
    }
    var fields = [];
    for (var k in v) {
        if (v.hasOwnProperty(k) && typeof v[k] !== 'function') fields.push(SK.quote(k) + ':' + SK.json(v[k]));
    }
    return '{' + fields.join(',') + '}';
};

// Ticks come back as strings: 2^53 is ~410 days of ticks, safe today, but
// keeping them as strings lets Python own all the arithmetic.
SK.ticks = function (time) {
    return time ? String(time.ticks) : null;
};

SK.timeFromTicks = function (ticks) {
    var t = new Time();
    t.ticks = String(ticks);
    return t;
};

SK.call = function (fn, fallback) {
    try { return fn(); } catch (e) { return fallback; }
};

SK.sequence = function (sequenceId) {
    if (!sequenceId) {
        if (!app.project.activeSequence) throw new Error('No active sequence');
        return app.project.activeSequence;
    }
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
        var s = app.project.sequences[i];
        if (s.sequenceID === sequenceId || s.name === sequenceId) return s;
    }
    throw new Error('Sequence not found: ' + sequenceId);
};
