const fs = require('node:fs');
const path = require('node:path');
const { createFile } = require('mp4box');
const root = path.resolve(__dirname, '../../.runtime/t49-evidence');
const files = ['video1.mp4', 'video2.mp4', 'video3.mp4'];
const reports = [];
for (const name of files) {
  const filePath = path.join(root, `${name}.anonymous.mp4`);
  if (process.argv.includes('--available') && !fs.existsSync(filePath)) continue;
  const file = createFile();
  let info;
  file.onReady = value => { info = value; };
  const bytes = fs.readFileSync(filePath);
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  buffer.fileStart = 0;
  file.appendBuffer(buffer); file.flush();
  if (!info || info.audioTracks.length || info.videoTracks.length !== 1) throw Error(`Invalid tracks: ${name}`);
  const track = info.videoTracks[0];
  reports.push({ source: name, codec: track.codec, audio_tracks: info.audioTracks.length, frames: track.nb_samples, seconds: track.duration / track.timescale, size: bytes.length });
}
if (!reports.length) throw Error('No results');
fs.writeFileSync(path.join(root, 'media-validation.json'), JSON.stringify(reports, null, 2));
console.log(JSON.stringify(reports, null, 2));
