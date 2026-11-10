#!/usr/bin/env node
// Render a motion-graphics HTML file (one that defines window.seek(seconds)) to an MP4.
// Usage: node tools/render-video.js <file.html> <out.mp4> [--w 1080 --h 1920 --fps 30 --dur 60]
// Output is upload-safe and plays on phones: H.264 High@4.0, capped bitrate, yuv420p, bt709,
// +faststart, with a silent AAC track.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');

const [html, out, ...rest] = process.argv.slice(2);
if (!html || !out) { console.error('Usage: node tools/render-video.js <file.html> <out.mp4> [--w 1920 --h 1080 --fps 30 --dur 60]'); process.exit(1); }
const opt = { w: 1920, h: 1080, fps: 30, dur: 60 };
for (let i = 0; i < rest.length; i += 2) opt[rest[i].replace(/^--/, '')] = +rest[i + 1];

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'frames-'));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: opt.w, height: opt.h } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file://' + path.resolve(html) + '?render');
  await page.evaluate(() => document.fonts.ready);
  if (errors.length) { console.error('Page errors:', errors); process.exit(1); }
  const n = Math.round(opt.fps * opt.dur);
  for (let i = 0; i < n; i++) {
    await page.evaluate(t => window.seek(t), i / opt.fps);
    await page.screenshot({ path: path.join(dir, String(i).padStart(5, '0') + '.jpg'), type: 'jpeg', quality: 92 });
    if (i % (opt.fps * 10) === 0) console.log(`frame ${i}/${n}`);
  }
  await browser.close();
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-framerate', String(opt.fps), '-i', path.join(dir, '%05d.jpg'),
    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-shortest',
    '-c:v', 'libx264', '-profile:v', 'high', '-level:v', '4.0', '-preset', 'slow', '-crf', '20', '-maxrate', '2500k', '-bufsize', '5000k', '-pix_fmt', 'yuv420p',
    '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv',
    '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out], { stdio: 'inherit' });
  fs.rmSync(dir, { recursive: true, force: true });
  console.log('Wrote', out);
})();
