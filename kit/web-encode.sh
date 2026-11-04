#!/usr/bin/env bash
# web-encode.sh — the web copies of a finished film: a small MP4 for a page's <video> and a GIF for where video won't play.
#
#   web-encode.sh mp4 IN OUT [CRF]                       H.264 High, yuv420p, preset slow, CRF (default 24), faststart,
#                                                        IN's size and frame rate; IN's audio as AAC 128k when it has any.
#                                                        libx264 on the CPU.
#   web-encode.sh gif IN OUT WIDTH FPS COLOURS [SS T]    WIDTH px wide (height kept in proportion, lanczos), FPS frames a
#                                                        second, one palette of COLOURS (stats_mode=diff), no dithering,
#                                                        diff_mode=rectangle; SS and T cut T seconds from SS seconds in
#   web-encode.sh selfcheck                              encodes a test pattern both ways and checks what came out
#
# The film itself stays the master: these are copies for a web page, small enough to load fast. Without dithering a
# GIF keeps the flat colours of a UI clean and compresses far better; a photo-like frame shows bands instead.
set -euo pipefail

usage(){ sed -n '4,10p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

ffx=(ffmpeg)

mp4(){
  local in=$1 out=$2 crf=${3:-24}
  "${ffx[@]}" -hide_banner -loglevel error -y -i "$in" -map 0:v:0 -map '0:a:0?' \
    -c:v libx264 -preset slow -crf "$crf" -profile:v high -pix_fmt yuv420p \
    -c:a aac -b:a 128k -movflags +faststart "$out"
}

gif(){
  local in=$1 out=$2 w=$3 fps=$4 colours=$5 ss=${6:-} t=${7:-} cut=()
  [ -n "$ss" ] && cut+=(-ss "$ss")
  [ -n "$t" ] && cut+=(-t "$t")
  ffmpeg -hide_banner -loglevel error -y "${cut[@]}" -i "$in" -an -filter_complex \
    "fps=$fps,scale=$w:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=$colours:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
    "$out"
}

selfcheck(){
  local tmp fails=0 got
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' RETURN
  ffmpeg -hide_banner -loglevel error -y -f lavfi -i testsrc2=s=640x360:r=30:d=4 -f lavfi -i sine=d=4 \
    -shortest -c:v libx264 -crf 10 -pix_fmt yuv444p -c:a pcm_s16le "$tmp/in.mkv"
  ffmpeg -hide_banner -loglevel error -y -i "$tmp/in.mkv" -map 0:v -c:v copy "$tmp/silent.mkv"
  ok(){ if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got '$2', want '$3'"; fails=$((fails + 1)); fi; }
  probe(){ ffprobe -v error -select_streams "$1" -show_entries "$2" -of csv=p=0 "$3" | head -1; }

  mp4 "$tmp/in.mkv" "$tmp/a.mp4"
  ok 'mp4: video is H.264 High yuv420p at the source size and rate' \
     "$(probe v:0 stream=codec_name,profile,pix_fmt,width,height,r_frame_rate "$tmp/a.mp4")" 'h264,High,640,360,yuv420p,30/1'
  ok 'mp4: CRF 24 by default' "$(grep -ao 'crf=[0-9.]*' "$tmp/a.mp4" | head -1)" 'crf=24.0'
  ok 'mp4: the moov atom comes before mdat (faststart)' \
     "$(grep -abo -m1 -e moov -e mdat "$tmp/a.mp4" | head -1 | cut -d: -f2)" moov
  ok 'mp4: a source with sound keeps it, as AAC' "$(probe a:0 stream=codec_name "$tmp/a.mp4")" aac
  mp4 "$tmp/silent.mkv" "$tmp/b.mp4" 30
  ok 'mp4: a silent source gives a silent MP4' "$(probe a stream=codec_name "$tmp/b.mp4")" ''
  ok 'mp4: CRF given is CRF used' "$(grep -ao 'crf=[0-9.]*' "$tmp/b.mp4" | head -1)" 'crf=30.0'

  gif "$tmp/in.mkv" "$tmp/a.gif" 320 10 64
  ok 'gif: WIDTH wide, height in proportion, FPS a second' \
     "$(probe v:0 stream=codec_name,width,height,r_frame_rate "$tmp/a.gif")" 'gif,320,180,10/1'
  got=$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$tmp/a.gif")
  ok 'gif: the whole film when no cut is given (4 s at 10 fps)' "$got" 40
  gif "$tmp/in.mkv" "$tmp/b.gif" 160 5 16 1 2
  got=$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$tmp/b.gif")
  ok 'gif: SS and T cut T seconds (2 s at 5 fps)' "$got" 10
  # ffmpeg writes a 256-entry table whatever the palette holds, so count the colours the frames actually use
  got=$(ffmpeg -v error -i "$tmp/b.gif" -f rawvideo -pix_fmt rgb24 - | python3 -c 'import sys; b=sys.stdin.buffer.read(); print(len({b[i:i + 3] for i in range(0, len(b), 3)}))')
  ok 'gif: no more than COLOURS in its frames (16)' "$([ "$got" -le 16 ] && [ "$got" -gt 1 ] && echo yes || echo "$got")" yes

  echo "$fails failed"
  [ "$fails" = 0 ]
}

case ${1:-} in
  mp4) [ $# -ge 3 ] && [ $# -le 4 ] || usage; shift; mp4 "$@";;
  gif) [ $# = 6 ] || [ $# = 8 ] || usage; shift; gif "$@";;
  selfcheck) selfcheck;;
  *) usage;;
esac
