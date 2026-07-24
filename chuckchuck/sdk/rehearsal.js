/**
 * 통합 리허설 녹음 SDK를 다시 export하거나 감싸는 파일입니다.
 * index.js에서 가져가기 쉽게 정리합니다.
 */

import './rehearsal-recorder.js';

const g = globalThis;

export const RehearsalRecorder = g.RehearsalRecorder;
export const RecorderError = g.RecorderError;
export const uploadRehearsal = g.uploadRehearsal;
