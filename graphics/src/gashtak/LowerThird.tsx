import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {loadFont} from '@remotion/fonts';

const FONT = 'Gashtak Helvetica';
void loadFont({family: FONT, url: staticFile('_assets/Helvetica.ttf'), weight: '400'});
void loadFont({family: FONT, url: staticFile('_assets/Helvetica-Bold.ttf'), weight: '700'});

export type GashtakProps = {kind: 'book' | 'term' | 'question'; title: string; detail?: string; label?: string};
const Icon: React.FC<{kind: GashtakProps['kind']}> = ({kind}) => <svg width="28" height="28" viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round">
  {kind === 'book' ? <><path d="M5 5h9c2 0 3 1 3 3v20c0-3-3-4-6-4H5Z"/><path d="M17 8c0-2 2-3 4-3h6v19h-5c-3 0-5 1-5 4"/></> : kind === 'question' ? <><path d="m3 14 26-10-7 24-8-8-5 4v-8Z"/><path d="m9 16 20-12-15 16"/></> : <><path d="m4 25 8-19 8 19M7 18h10M23 12v13M23 7v1"/></>}
</svg>;

// A transparent full-frame overlay in a 1920 x 1080 design space.
export const GashtakLowerThird: React.FC<GashtakProps> = ({kind, title, detail, label}) => {
  const frame = useCurrentFrame();
  const {width, fps, durationInFrames} = useVideoConfig();
  const enter = interpolate(frame, [0, fps*.4], [0, 1], {extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const exit = interpolate(frame, [durationInFrames-fps*.3, durationInFrames-1], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const book = kind === 'book';
  const question = kind === 'question';
  const accent = book ? '#E4D7BC' : '#A4D9ED';
  return <AbsoluteFill style={{fontFamily: FONT}}>
    <div style={{position: 'absolute', left: 0, top: 0, width: 1920, height: 1080, transform: `scale(${width/1920})`, transformOrigin: 'top left'}}>
      <div style={{position: 'absolute', left: 220, bottom: 92, width: question ? 1240 : book ? 870 : 1030, opacity: enter*exit, transform: `translateY(${(1-enter)*18+(1-exit)*8}px)`, display: 'flex', color: '#FAFAF7', textShadow: '0 2px 5px rgba(0,0,0,0.8), 0 0 18px rgba(0,0,0,0.45)'}}>
        {book && <div style={{width: 88, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
          <div style={{width: 57, height: 78, borderRadius: '2px 5px 5px 2px', background: '#506352', boxShadow: '4px 3px 0 #F7F1E5, 5px 4px 0 #A49C89', borderLeft: '5px solid #384B3B', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#E8DEC7'}}><Icon kind="book"/></div>
        </div>}
        <div style={{padding: '23px 16px 25px', flex: 1}}>
          {kind !== 'term' && <div style={{display: 'flex', alignItems: 'center', gap: 10, color: accent, fontSize: 14, fontWeight: 700, letterSpacing: 2.3, marginBottom: 10}}>
            {question && <Icon kind="question"/>} {label ?? (book ? 'KITOB JAVONI' : 'TELEGRAMDAN SAVOL')}
          </div>}
          <div style={{fontSize: question ? 34 : 38, fontWeight: 700, lineHeight: 1.22, letterSpacing: -.4}}>{title}</div>
          {detail && <div style={{fontSize: book ? 25 : 27, fontWeight: 400, lineHeight: 1.4, marginTop: 10, color: '#E5E7E6'}}>{detail}</div>}
        </div>
      </div>
    </div>
  </AbsoluteFill>;
};
export const GASHTAK_EXAMPLES: GashtakProps[] = [
  {kind: 'book', title: 'So‘z erkinligi haqida so‘z', detail: 'Karim Bahriyev'},
  {kind: 'term', title: 'Axborot gigiyenasi', detail: 'Axborotni saralash, manbasini tekshirish va iste’molini me’yorlash.'},
  {kind: 'question', title: 'Fikringizni butunlay o‘zgartirgan voqea yoki kitob bo‘lganmi?'},
];
// Preview-only background. Alpha export uses GashtakLowerThird directly.
export const GashtakPreview: React.FC = () => {
  const {fps} = useVideoConfig();
  return <AbsoluteFill>
    <Img src={staticFile('_assets/gashtak-reference.jpg')} style={{width: '100%', height: '100%', objectFit: 'cover'}}/>
    {GASHTAK_EXAMPLES.map((props, i) => <Sequence key={props.kind} from={i*5*fps} durationInFrames={5*fps}><GashtakLowerThird {...props}/></Sequence>)}
  </AbsoluteFill>;
};
