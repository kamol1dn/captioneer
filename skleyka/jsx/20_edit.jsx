// Editing helpers: placing, finding and changing what Skleyka put on the
// timeline. Skleyka only ever edits tracks named "SKL <n>" (its lanes) and
// clips named "SKL <id> ..." (its overlays); the user's own tracks are only
// ever read. The one exception is the multicam edit track, which angle
// changes and switch rolls touch on request.
//
// Gotchas found by probing Premiere 25.6:
// - ES3: "in", "final" and friends are reserved; never use them as bare keys.
// - QE time arguments are timecode strings in the sequence's display format;
//   a ticks string is silently read as frame 0.
// - QE exportFramePNG needs a backslash path with no extension and no dot in
//   the name; a forward-slash path throws.
// - After a setter (start/end), the same command reads stale inPoint/outPoint.
// - Setting a clip's start slides its content rather than trimming the head.

SK.LANE = 'SKL ';

SK.frameTicks = function (seq) {
    return Number(seq.timebase);
};

// Zero-based sequence seconds to the nearest frame boundary, in ticks.
SK.ticksAt = function (seq, seconds) {
    var f = SK.frameTicks(seq);
    return Math.round(seconds * SK.TICKS / f) * f + Number(seq.zeroPoint);
};

SK.secondsAt = function (seq, ticks) {
    return (Number(ticks) - Number(seq.zeroPoint)) / SK.TICKS;
};

SK.timecode = function (seq, ticks) {
    var s = seq.getSettings();
    return SK.timeFromTicks(ticks).getFormatted(s.videoFrameRate, s.videoDisplayFormat);
};

// QE only works on the active sequence: make ours active and return both views.
SK.activate = function (sequenceId) {
    var seq = SK.sequence(sequenceId);
    if (!app.project.activeSequence || app.project.activeSequence.sequenceID !== seq.sequenceID) {
        app.project.openSequence(seq.sequenceID);
    }
    app.enableQE();
    var qs = qe.project.getActiveSequence();
    if (!qs || qs.guid !== seq.sequenceID) throw new Error('Could not make "' + seq.name + '" the active sequence');
    return {seq: seq, qs: qs};
};

SK.normPath = function (p) {
    return String(p || '').split('/').join('\\').toLowerCase();
};

SK.bin = function (name) {
    var root = app.project.rootItem;
    for (var i = 0; i < root.children.numItems; i++) {
        var c = root.children[i];
        if (c.type === ProjectItemType.BIN && c.name === name) return c;
    }
    return root.createBin(name);
};

SK.itemByPath = function (bin, path) {
    var want = SK.normPath(path);
    for (var i = 0; i < bin.children.numItems; i++) {
        var c = bin.children[i];
        if (c.type === ProjectItemType.BIN) continue;
        if (SK.normPath(SK.call(function () { return c.getMediaPath(); }, '')) === want) return c;
    }
    return null;
};

// Reuses the project item when the file was imported before; a re-rendered
// file at the same path is picked up by refreshMedia, not a second import.
SK.importItem = function (path, bin) {
    var item = SK.itemByPath(bin, path);
    if (item) return item;
    if (!app.project.importFiles([path], true, bin, false)) throw new Error('Import failed: ' + path);
    item = SK.itemByPath(bin, path);
    if (!item) throw new Error('Imported, but the item is not in the bin: ' + path);
    return item;
};

SK.tracksOf = function (seq, kind) {
    return kind === 'audio' ? seq.audioTracks : seq.videoTracks;
};

SK.qeTrack = function (qs, kind, index) {
    return kind === 'audio' ? qs.getAudioTrackAt(index) : qs.getVideoTrackAt(index);
};

SK.isLane = function (track) {
    return String(track.name).indexOf(SK.LANE) === 0;
};

SK.lanes = function (seq, kind) {
    var tracks = SK.tracksOf(seq, kind), out = [];
    for (var i = 0; i < tracks.numTracks; i++) if (SK.isLane(tracks[i])) out.push(i);
    return out;
};

SK.isFree = function (track, startTicks, endTicks, ignoreNodeId) {
    for (var i = 0; i < track.clips.numItems; i++) {
        var c = track.clips[i];
        if (ignoreNodeId && c.nodeId === ignoreNodeId) continue;
        if (Number(c.start.ticks) < endTicks && Number(c.end.ticks) > startTicks) return false;
    }
    return true;
};

// A new lane goes on top of everything, so it never sits under the user's
// tracks. Named lanes ("SKL otabek") group overlays that carry that camera's
// footage, so one colour grade on the track covers them all.
SK.addLane = function (seq, qs, kind, name) {
    var tracks = SK.tracksOf(seq, kind);
    var n = tracks.numTracks;
    var label = name ? SK.LANE + name : SK.LANE + (SK.lanes(seq, kind).length + 1);
    if (kind === 'audio') qs.addTracks(0, 0, 1, 1, n);
    else qs.addTracks(1, n, 0);
    if (tracks.numTracks !== n + 1) throw new Error('Could not add a ' + kind + ' track');
    SK.qeTrack(qs, kind, n).setName(label);
    return n;
};

// A free lane for [start, end). ``lane`` is a number (that exact "SKL n",
// which must be free), a name (a free "SKL <name>" or "SKL <name> 2", made if
// needed), or nothing (the lowest free unnamed lane, else a new one).
SK.pickLane = function (seq, qs, kind, startTicks, endTicks, lane) {
    var tracks = SK.tracksOf(seq, kind);
    var lanes = SK.lanes(seq, kind);
    var i, name;
    if (typeof lane === 'number') {
        for (i = 0; i < lanes.length; i++) {
            if (tracks[lanes[i]].name === SK.LANE + lane) {
                if (!SK.isFree(tracks[lanes[i]], startTicks, endTicks)) throw new Error('Lane ' + SK.LANE + lane + ' is not free there');
                return lanes[i];
            }
        }
        throw new Error('No lane named ' + SK.LANE + lane);
    }
    if (lane) {
        var want = SK.LANE + lane, count = 0;
        for (i = 0; i < lanes.length; i++) {
            name = String(tracks[lanes[i]].name);
            if (name === want || name.indexOf(want + ' ') === 0) {
                count++;
                if (SK.isFree(tracks[lanes[i]], startTicks, endTicks)) return lanes[i];
            }
        }
        return SK.addLane(seq, qs, kind, count ? lane + ' ' + (count + 1) : lane);
    }
    for (i = 0; i < lanes.length; i++) {
        name = String(tracks[lanes[i]].name);
        if (/^SKL \d+$/.test(name) && SK.isFree(tracks[lanes[i]], startTicks, endTicks)) return lanes[i];
    }
    return SK.addLane(seq, qs, kind);
};

SK.clipAtStart = function (track, startTicks, nodeId, frameTicks) {
    for (var i = 0; i < track.clips.numItems; i++) {
        var c = track.clips[i];
        if (Math.abs(Number(c.start.ticks) - startTicks) < frameTicks / 2 && c.projectItem && c.projectItem.nodeId === nodeId) return c;
    }
    return null;
};

SK.tagOf = function (id) {
    return SK.LANE + id;
};

// Lanes first (cheap), then every track, in case the user dragged it off a lane.
SK.findTagged = function (seq, kind, id) {
    var tag = SK.tagOf(id);
    var tracks = SK.tracksOf(seq, kind);
    var order = SK.lanes(seq, kind);
    for (var t = 0; t < tracks.numTracks; t++) if (!SK.isLane(tracks[t])) order.push(t);
    for (var o = 0; o < order.length; o++) {
        var track = tracks[order[o]];
        for (var i = 0; i < track.clips.numItems; i++) {
            var c = track.clips[i];
            if (c.name === tag || String(c.name).indexOf(tag + ' ') === 0) return {clip: c, track: order[o]};
        }
    }
    return null;
};

SK.component = function (clip, displayName) {
    for (var i = 0; i < clip.components.numItems; i++) {
        if (clip.components[i].displayName === displayName) return clip.components[i];
    }
    return null;
};

SK.param = function (component, displayName) {
    if (!component) return null;
    for (var i = 0; i < component.properties.numItems; i++) {
        if (component.properties[i].displayName === displayName) return component.properties[i];
    }
    return null;
};

// style: {position: [x, y] (0-1), scale, rotation, opacity, blend (Premiere's
// index, mapped in Python), gain_db}. Unset keys are left alone.
SK.applyStyle = function (clip, style) {
    if (!style) return;
    var motion = SK.component(clip, 'Motion');
    var opacity = SK.component(clip, 'Opacity');
    var volume = SK.component(clip, 'Volume');
    if (style.position) SK.param(motion, 'Position').setValue([style.position[0], style.position[1]], true);
    if (style.scale !== undefined && style.scale !== null) SK.param(motion, 'Scale').setValue(style.scale, true);
    if (style.rotation !== undefined && style.rotation !== null) SK.param(motion, 'Rotation').setValue(style.rotation, true);
    if (style.opacity !== undefined && style.opacity !== null) SK.param(opacity, 'Opacity').setValue(style.opacity, true);
    // Opacity has two "Blend Mode" parameters; the first is the visible one.
    if (style.blend !== undefined && style.blend !== null) SK.param(opacity, 'Blend Mode').setValue(style.blend, true);
    // Premiere stores clip volume as 10^((dB - 15) / 20).
    if (style.gain_db !== undefined && style.gain_db !== null) {
        SK.param(volume, 'Level').setValue(Math.pow(10, (style.gain_db - 15) / 20), true);
    }
};

SK.keys = function (prop, pairs) {
    // pairs: [[ticks, value], ...]; eased where Premiere lets us.
    prop.setTimeVarying(true);
    for (var i = 0; i < pairs.length; i++) {
        var t = SK.timeFromTicks(pairs[i][0]);
        prop.addKey(t);
        prop.setValueAtKey(t, pairs[i][1], true);
        SK.call(function () { return prop.setInterpolationTypeAtKey(t, 5, true); }, null); // 5 = ease
    }
};

// Entrance and exit as opacity keyframes on the clip: "fade" (the editor's
// lower third has only that, 12 frames each way), "rise" also lifts a little.
SK.animate = function (seq, clip, kind) {
    if (!kind) return;
    var f = SK.frameTicks(seq);
    // Key times are in the clip's media clock (its in-point is frame 0 of the
    // clip), not sequence time: keys set at sequence time sat past the clip's
    // end, and the held value before the first key (opacity 0) hid everything.
    var m0 = Number(clip.inPoint.ticks);
    var len = Number(clip.end.ticks) - Number(clip.start.ticks);
    var inF = kind === 'fade' ? 4 : 10, outF = kind === 'fade' ? 4 : 8;
    var op = SK.param(SK.component(clip, 'Opacity'), 'Opacity');
    SK.keys(op, [[m0, 0], [m0 + inF * f, 100], [m0 + len - outF * f, 100], [m0 + len - f, 0]]);
    if (kind === 'rise') {
        var pos = SK.param(SK.component(clip, 'Motion'), 'Position');
        var base = pos.getValue();
        var lift = 26 / 1080;  // a little below its place, in frame fractions
        SK.keys(pos, [[m0, [base[0], base[1] + lift]], [m0 + inF * f, [base[0], base[1]]]]);
    }
};

// Real Cross Dissolves on a clip's edges (the editor's graphics use these,
// not opacity keys): a dissolve on a lone clip fades from and to nothing.
SK.dissolve = function (seq, qs, trackIndex, startTicks, frames) {
    var f = SK.frameTicks(seq);
    var qt = qs.getVideoTrackAt(trackIndex), qi = null;
    for (var i = 0; i < qt.numItems; i++) {
        var it = qt.getItemAt(i);
        if (it.type !== 'Empty' && Math.abs(Number(it.start.ticks) - startTicks) < f / 2) { qi = it; break; }
    }
    if (!qi) throw new Error('clip for the dissolve not found');
    var tr = qe.project.getVideoTransitionByName('Cross Dissolve');
    if (!tr) throw new Error('Cross Dissolve not available');
    var code = SK.timecode(seq, Number(seq.zeroPoint) + frames * f);
    var a = qi.addTransition(tr, true, code, '0', 0.5, false, true);
    var b = qi.addTransition(tr, false, code, '0', 0.5, false, true);
    return [String(a), String(b)];
};

SK.clipState = function (seq, clip, track) {
    return {
        name: clip.name,
        track: track,
        start: SK.secondsAt(seq, clip.start.ticks),
        end: SK.secondsAt(seq, clip.end.ticks),
        start_ticks: String(clip.start.ticks),
        end_ticks: String(clip.end.ticks),
        node_id: clip.nodeId,
        media_path: SK.call(function () { return clip.projectItem.getMediaPath(); }, null)
    };
};

// Multicam clips of the edit, as [track, start, end, inPoint, outPoint,
// disabled]; lanes are skipped. isMulticamClip is asked once per project item.
SK.programCuts = function (seq) {
    var known = {}, out = [];
    for (var t = 0; t < seq.videoTracks.numTracks; t++) {
        var track = seq.videoTracks[t];
        if (SK.isLane(track)) continue;
        for (var i = 0; i < track.clips.numItems; i++) {
            var c = track.clips[i], item = c.projectItem;
            if (!item) continue;
            var id = item.nodeId;
            if (known[id] === undefined) known[id] = SK.call(function () { return item.isMulticamClip(); }, false);
            if (!known[id]) continue;
            out.push([t, String(c.start.ticks), String(c.end.ticks), String(c.inPoint.ticks), String(c.outPoint.ticks), c.disabled ? 1 : 0]);
        }
    }
    return out;
};
