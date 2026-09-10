import { mkdirSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
const ffmpeg = 'D:/anaconda/envs/xmer-annotation/Library/bin/ffmpeg.exe';
if (!existsSync(ffmpeg)) throw new Error('请先准备项目专用环境中的 FFmpeg');
mkdirSync('public/media', { recursive: true });
const video = 'gradients=size=960x600:rate=25:duration=12:c0=0x123d36:c1=0x658164:x0=0:y0=0:x1=960:y1=600:speed=0.01,drawgrid=w=80:h=80:t=1:c=white@0.035,drawbox=x=64:y=60:w=832:h=480:color=white@0.10:t=1,drawbox=x=80:y=410:w=800:h=3:color=white@0.15:t=fill';
const tone = 'sine=frequency=220:sample_rate=16000:duration=12';
const run = args => {
  const result = spawnSync(ffmpeg, ['-hide_banner','-loglevel','error','-n',...args], { stdio:'inherit', windowsHide:true });
  if (result.status !== 0) throw new Error('演示素材生成失败');
};
const output = name => join('public/media',name);
if (!existsSync(output('visual.mp4'))) run(['-f','lavfi','-i',video,'-an','-c:v','libx264','-preset','fast','-crf','26','-pix_fmt','yuv420p','-movflags','+faststart',output('visual.mp4')]);
if (!existsSync(output('audio.wav'))) run(['-f','lavfi','-i',tone,'-af','volume=0.1,afade=t=in:d=1,afade=t=out:st=10:d=2','-c:a','pcm_s16le',output('audio.wav')]);
if (!existsSync(output('audiovisual.mp4'))) run(['-i',output('visual.mp4'),'-i',output('audio.wav'),'-c:v','copy','-c:a','aac','-movflags','+faststart','-shortest',output('audiovisual.mp4')]);
console.log('已生成 12 秒演示素材。音频为合成音，文本为示例时间戳，两者不代表真实语音对齐。');
