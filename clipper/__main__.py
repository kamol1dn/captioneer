"""CLI mirror of every MCP tool.

Debugging a stdio MCP server is miserable — a malformed response is an opaque
client-side parse error with no stack trace. This CLI calls the exact same
plain functions the MCP tools wrap, so the whole surface can be exercised and
debugged with normal Python tracebacks before an MCP client ever touches it.

Usage:
    python -m clipper create-project "EP12" --camera A=D:/footage/CamA.mp4 \\
        --camera B=D:/footage/CamB.mp4 --primary A
    python -m clipper ingest 2026-07-20_ep12
    python -m clipper ingest-status 2026-07-20_ep12
    python -m clipper outline 2026-07-20_ep12
    python -m clipper transcript 2026-07-20_ep12 --start 60 --end 180
    python -m clipper get-edl 2026-07-20_ep12
    python -m clipper set-edl 2026-07-20_ep12 --file edl.json
    python -m clipper export-xml 2026-07-20_ep12
    python -m clipper export-preview 2026-07-20_ep12 --clip c01
"""
import argparse
import json
import sys

from . import captions as captions_mod
from . import energy as energy_mod
from . import ingest as ingest_mod
from . import transcript as transcript_mod
from .compile import compile_for
from .edl import EDL, validate
from .preview import render_preview
from .project import Project, create, list_projects
from .xmeml import write_xmeml


def _out(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _load(project_id: str) -> Project:
    project = Project.load(project_id)
    if project is None:
        sys.exit(f"no such project: {project_id!r}")
    return project


def _camera_spec(spec: str) -> dict:
    """``id[@speaker][:V1]=path`` -> the dict ``create`` wants.

    ``@speaker`` groups several angles onto one person. ``:V1`` names the master
    timeline's V-track this angle takes its picture from — the timeline route,
    where ``path`` is then the isolated mic that person is *heard* on rather than
    a flat vertical export. Either half may be omitted; ``path`` may be empty for
    a track-backed angle with no mic of its own.
    """
    cam_id, _, path = spec.partition("=")
    cam_id, _, track = cam_id.partition(":")
    cam_id, _, speaker = cam_id.partition("@")
    return {"id": cam_id, "path": path, "speaker": speaker,
            "source_track": track}


def cmd_create_project(args):
    cameras = [_camera_spec(s) for s in args.camera]
    project, warnings_ = create(args.name, cameras, args.primary or "",
                                project_dir=args.project_dir,
                                language=args.language or "",
                                caption_preset=args.preset or "",
                                master_xml=args.master_xml or "",
                                master_sequence=args.master_sequence or "")
    _out({"project_id": project.id, "project_dir": str(project.dir),
         "media_dir": str(project.media_dir), "warnings": warnings_,
         "language": project.language, "caption_preset": project.caption_preset,
         "cameras": [c.to_dict(project.dir) for c in project.cameras]})


def cmd_list_projects(args):
    _out(list_projects())


def cmd_ingest(args):
    project = _load(args.project_id)
    # Same rule as the MCP tool: the project remembers the language, and an
    # explicit --language both wins and is saved back.
    language = (args.language or project.language or "").strip().lower()
    if language and language != project.language:
        project.language = language
        project.save()
    job = ingest_mod.start_ingest(project, args.model, language or None,
                                  args.camera or None, args.diarize)
    if args.wait:
        job.done.wait()
    _out({"job_id": job.id, "state": project.ingest_state})


def cmd_ingest_status(args):
    project = _load(args.project_id)
    _out(project.ingest_state)


def cmd_outline(args):
    project = _load(args.project_id)
    utterances = transcript_mod.load_utterances(project)
    envelopes = ingest_mod.load_envelopes(project)
    print(transcript_mod.build_outline(utterances, envelopes, args.bucket,
                                       args.start, args.end))


def cmd_transcript(args):
    project = _load(args.project_id)
    utterances = transcript_mod.load_utterances(project)
    envelopes = ingest_mod.load_envelopes(project)
    result = transcript_mod.format_transcript(utterances, envelopes, args.start,
                                              args.end, args.max_chars)
    print(result["text"])
    if result["truncated"]:
        print(f"\n... truncated, next_start={result['next_start']}",
              file=sys.stderr)


def cmd_search(args):
    project = _load(args.project_id)
    utterances = transcript_mod.load_utterances(project)
    _out(transcript_mod.search(utterances, args.query, args.regex, args.max_hits))


def cmd_silences(args):
    project = _load(args.project_id)
    cam = args.camera or project.primary_audio_camera
    env = energy_mod.load_envelope(project.energy_path(cam))
    if not env:
        sys.exit(f"no energy envelope for {cam!r} — run ingest first")
    _out(energy_mod.find_silences(env, args.start, args.end, args.min_sec))


def cmd_get_edl(args):
    project = _load(args.project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        _out({"edl": None})
        return
    _out({"edl": edl.to_dict(),
         "validation": validate(edl, project.camera_ids,
                                project.master_duration,
                                project.video_camera_ids)})


def cmd_set_edl(args):
    project = _load(args.project_id)
    data = json.loads(open(args.file, encoding="utf-8").read())
    edl = EDL.from_dict(data)
    result = validate(edl, project.camera_ids, project.master_duration,
                      project.video_camera_ids)
    if not result["ok"]:
        _out(result)
        sys.exit(1)
    edl.save(project.edl_path)
    _out(result)


def cmd_validate_edl(args):
    project = _load(args.project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        sys.exit("no EDL saved")
    _out(validate(edl, project.camera_ids, project.master_duration,
                  project.video_camera_ids))


def cmd_export_xml(args):
    project = _load(args.project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        sys.exit("no EDL saved")
    result = validate(edl, project.camera_ids, project.master_duration,
                      project.video_camera_ids)
    if not result["ok"]:
        _out(result)
        sys.exit(1)
    # Rendered caption overlays ride along, same as the MCP path — an export
    # that silently dropped them would look identical until you scrubbed it.
    movs = {} if args.no_captions else captions_mod.caption_movs(project, edl)
    compiled = compile_for(project, edl, args.clip or None, movs)

    meta = dict(project.file_meta())
    meta.update(captions_mod.caption_file_meta(
        movs, edl.frame_size, edl.timebase,
        {c.id: c.duration for c in compiled}))

    out = args.out or str(project.exports_dir / f"{project.id}.xml")
    write_xmeml(compiled, out, project_name=project.name, file_meta=meta)
    _out({"path": out, "n_clips": len(compiled),
          "captioned_clips": sorted(movs)})


def cmd_export_preview(args):
    project = _load(args.project_id)
    edl = EDL.load(project.edl_path)
    if edl is None:
        sys.exit("no EDL saved")
    clip = edl.clip(args.clip)
    if clip is None:
        sys.exit(f"no clip {args.clip!r}")
    compiled = compile_for(project, edl, [args.clip])[0]
    out = args.out or str(project.exports_dir / f"{args.clip}_preview.mp4")
    render_preview(compiled, out, args.quality)
    _out({"path": out, "duration_sec": compiled.duration_seconds})


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m clipper")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("create-project"); c.add_argument("name")
    c.add_argument("--camera", action="append", required=True,
                   help="id[@speaker][:V1]=path, repeatable; @speaker groups "
                        "two angles onto one person, :V1 takes picture from "
                        "that master V-track instead of a flat export")
    c.add_argument("--primary", help="primary audio camera id")
    c.add_argument("--master-xml", default=None,
                   help="FCP7 XML of the episode timeline, for :V1 angles")
    c.add_argument("--master-sequence", default=None,
                   help="which sequence in --master-xml to cut from")
    c.add_argument("--language", default=None,
                   help="spoken language, e.g. uz (Gashtak) or en (OTG)")
    c.add_argument("--preset", default=None,
                   help="caption preset for this project's clips")
    c.add_argument("--project-dir", default=None,
                   help="override where the project is stored "
                        "(default: clipper/ beside the media)")
    c.set_defaults(func=cmd_create_project)

    c = sub.add_parser("list-projects"); c.set_defaults(func=cmd_list_projects)

    c = sub.add_parser("ingest"); c.add_argument("project_id")
    c.add_argument("--model", default="large-v3")
    c.add_argument("--language", default=None)
    c.add_argument("--camera", action="append", help="restrict to these camera ids")
    c.add_argument("--diarize", action="store_true",
                   help="transcribe one mic per speaker and merge into a "
                        "speaker-labelled timeline (needs two+ speakers)")
    c.add_argument("--wait", action="store_true")
    c.set_defaults(func=cmd_ingest)

    c = sub.add_parser("ingest-status"); c.add_argument("project_id")
    c.set_defaults(func=cmd_ingest_status)

    c = sub.add_parser("outline"); c.add_argument("project_id")
    c.add_argument("--bucket", type=float, default=20.0)
    c.add_argument("--start", type=float, default=0.0)
    c.add_argument("--end", type=float, default=None)
    c.set_defaults(func=cmd_outline)

    c = sub.add_parser("transcript"); c.add_argument("project_id")
    c.add_argument("--start", type=float, default=0.0)
    c.add_argument("--end", type=float, default=None)
    c.add_argument("--max-chars", type=int, default=8000)
    c.set_defaults(func=cmd_transcript)

    c = sub.add_parser("search"); c.add_argument("project_id")
    c.add_argument("query")
    c.add_argument("--regex", action="store_true")
    c.add_argument("--max-hits", type=int, default=30)
    c.set_defaults(func=cmd_search)

    c = sub.add_parser("silences"); c.add_argument("project_id")
    c.add_argument("--start", type=float, required=True)
    c.add_argument("--end", type=float, required=True)
    c.add_argument("--min-sec", type=float, default=0.35)
    c.add_argument("--camera", default=None)
    c.set_defaults(func=cmd_silences)

    c = sub.add_parser("get-edl"); c.add_argument("project_id")
    c.set_defaults(func=cmd_get_edl)

    c = sub.add_parser("set-edl"); c.add_argument("project_id")
    c.add_argument("--file", required=True)
    c.set_defaults(func=cmd_set_edl)

    c = sub.add_parser("validate-edl"); c.add_argument("project_id")
    c.set_defaults(func=cmd_validate_edl)

    c = sub.add_parser("export-xml"); c.add_argument("project_id")
    c.add_argument("--out", default=None)
    c.add_argument("--no-captions", action="store_true",
                   help="omit rendered caption overlays")
    c.add_argument("--clip", action="append", help="restrict to these clip ids")
    c.set_defaults(func=cmd_export_xml)

    c = sub.add_parser("export-preview"); c.add_argument("project_id")
    c.add_argument("--clip", required=True)
    c.add_argument("--out", default=None)
    c.add_argument("--quality", default="fast", choices=["fast", "final"])
    c.set_defaults(func=cmd_export_preview)

    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
