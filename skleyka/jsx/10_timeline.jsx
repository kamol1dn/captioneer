// Timeline readers. Everything is read, nothing is changed.

SK.clipInfo = function (clip, index) {
    var item = clip.projectItem;
    var info = {
        index: index,
        name: clip.name,
        node_id: SK.call(function () { return clip.nodeId; }, null),
        start: SK.ticks(clip.start),
        end: SK.ticks(clip.end),
        in_point: SK.ticks(clip.inPoint),
        out_point: SK.ticks(clip.outPoint),
        disabled: SK.call(function () { return clip.disabled; }, null),
        speed: SK.call(function () { return clip.getSpeed(); }, null),
        media_path: null,
        project_item: null,
        multicam: false
    };
    if (item) {
        info.project_item = item.nodeId;
        info.media_path = SK.call(function () { return item.getMediaPath() || null; }, null);
        info.multicam = SK.call(function () { return item.isMulticamClip(); }, false);
        info.is_sequence = SK.call(function () { return item.isSequence(); }, false);
    }
    return info;
};

// Static Motion values (position is normalised 0-1, scale in %, crops in %).
// Keyframed parameters are flagged rather than sampled.
SK.MOTION_KEYS = {
    'Position': 'position', 'Scale': 'scale', 'Scale Width': 'scale_width',
    'Uniform Scale': 'uniform', 'Rotation': 'rotation', 'Anchor Point': 'anchor',
    'Crop Left': 'crop_left', 'Crop Top': 'crop_top', 'Crop Right': 'crop_right', 'Crop Bottom': 'crop_bottom'
};

SK.motion = function (clip) {
    var comps = clip.components;
    for (var i = 0; i < comps.numItems; i++) {
        if (comps[i].displayName !== 'Motion') continue;
        var out = {animated: []};
        for (var p = 0; p < comps[i].properties.numItems; p++) {
            var prop = comps[i].properties[p];
            var key = SK.MOTION_KEYS[prop.displayName];
            if (!key) continue;
            var v = SK.call(function () { return prop.getValue(); }, null);
            out[key] = (v instanceof Array) ? [Number(v[0]), Number(v[1])] : v;
            if (SK.call(function () { return prop.isTimeVarying(); }, false)) out.animated.push(key);
        }
        return out;
    }
    return null;
};

SK.trackInfo = function (track, index, withMotion) {
    var clips = [];
    for (var i = 0; i < track.clips.numItems; i++) {
        var info = SK.clipInfo(track.clips[i], i);
        if (withMotion) info.motion = SK.call(function () { return SK.motion(track.clips[i]); }, null);
        clips.push(info);
    }
    return {
        index: index,
        name: track.name,
        muted: SK.call(function () { return track.isMuted(); }, null),
        locked: SK.call(function () { return track.isLocked(); }, null),
        clips: clips
    };
};

SK.markers = function (seq) {
    var out = [];
    var m = seq.markers.getFirstMarker();
    while (m) {
        out.push({
            name: m.name,
            comments: m.comments,
            start: SK.ticks(m.start),
            end: SK.ticks(m.end),
            type: m.type,
            color: SK.call(function () { return m.getColorByIndex(); }, null)
        });
        m = seq.markers.getNextMarker(m);
    }
    return out;
};

SK.sequenceInfo = function (seq, withAudio, withMotion) {
    var settings = seq.getSettings();
    var video = [], audio = [];
    for (var v = 0; v < seq.videoTracks.numTracks; v++) video.push(SK.trackInfo(seq.videoTracks[v], v, withMotion));
    if (withAudio) {
        for (var a = 0; a < seq.audioTracks.numTracks; a++) audio.push(SK.trackInfo(seq.audioTracks[a], a));
    }
    return {
        name: seq.name,
        sequence_id: seq.sequenceID,
        project_item: seq.projectItem ? seq.projectItem.nodeId : null,
        width: settings.videoFrameWidth,
        height: settings.videoFrameHeight,
        frame_ticks: String(settings.videoFrameRate.ticks),
        timebase: seq.timebase,
        zero_point: String(seq.zeroPoint),
        end: String(seq.end),
        playhead: SK.ticks(seq.getPlayerPosition()),
        in_point: SK.call(function () { return SK.ticks(seq.getInPointAsTime()); }, null),
        out_point: SK.call(function () { return SK.ticks(seq.getOutPointAsTime()); }, null),
        video: video,
        audio: audio,
        markers: SK.markers(seq)
    };
};

// The sequence behind a multicam project item: its video tracks are the angles.
SK.sequenceForItem = function (nodeId) {
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
        var s = app.project.sequences[i];
        if (s.projectItem && s.projectItem.nodeId === nodeId) return s;
    }
    return null;
};
