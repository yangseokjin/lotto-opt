'use strict';
// 실행: node --test test/lottoRouter.test.js   (express, better-sqlite3 를 찾을 수 있는 곳에서)
// 진짜 엔진까지 시험하려면 LOTTO_REAL_OPT_DIR=<lotto-opt 폴더> (와 필요하면 LOTTO_REAL_PYTHON) 를 준다.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const express = require('express');
const Database = require('better-sqlite3');
const { createLottoRouter } = require('../server/lottoRouter');

const PYTHON = process.env.LOTTO_REAL_PYTHON || process.env.LOTTO_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const FAKE_DIR = path.join(__dirname, 'fake-lotto-opt');

// 진짜 requireSystemAdmin 대신: x-test-user 헤더가 admin 이면 통과
const fakeGuard = (req, res, next) => {
  if (req.get('x-test-user') !== 'admin') return res.status(403).json({ error: '권한이 없습니다' });
  req.user = { username: 'admin' };
  next();
};

async function startApp(opts = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lotto-test-'));
  const db = new Database(path.join(dir, 'test.db'));
  const app = express();
  app.use('/api/lotto', createLottoRouter({ db, guard: fakeGuard, pythonPath: PYTHON, lottoOptDir: FAKE_DIR, ...opts }));
  const server = await new Promise((resolve) => {
    const s = app.listen(0, '127.0.0.1', () => resolve(s));
  });
  const base = `http://127.0.0.1:${server.address().port}/api/lotto`;
  const call = async (method, url, body, user = 'admin') => {
    const res = await fetch(base + url, {
      method,
      headers: { 'content-type': 'application/json', 'x-test-user': user },
      body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
    });
    return { status: res.status, data: await res.json() };
  };
  const close = () => {
    server.close();
    db.close();
    fs.rmSync(dir, { recursive: true, force: true });
  };
  return { call, close, db };
}

test('관리자가 아니면 모든 경로가 403', async () => {
  const app = await startApp();
  try {
    for (const [m, u, b] of [['GET', '/status'], ['POST', '/run', {}], ['GET', '/runs'], ['GET', '/runs/1'], ['POST', '/runs/1/check', {}], ['DELETE', '/runs/1']]) {
      const r = await app.call(m, u, b, 'staff');
      assert.strictEqual(r.status, 403, `${m} ${u}`);
    }
  } finally {
    app.close();
  }
});

test('잘못된 입력은 400', async () => {
  const app = await startApp();
  try {
    assert.strictEqual((await app.call('POST', '/run', { preset: 'x' })).status, 400);
    assert.strictEqual((await app.call('POST', '/run', { sets: 40 })).status, 400);
    assert.strictEqual((await app.call('POST', '/run', { seed: -3 })).status, 400);
    assert.strictEqual((await app.call('POST', '/run', { seed: 1.5 })).status, 400);
    assert.strictEqual((await app.call('POST', '/run', { seed: '7; rm -rf /' })).status, 400);
    const broken = await app.call('POST', '/run', '{broken json');
    assert.strictEqual(broken.status, 400);
    assert.match(broken.data.error, /요청 형식/);
    assert.strictEqual((await app.call('GET', '/runs/abc')).status, 404);
  } finally {
    app.close();
  }
});

test('실행 → 저장 → 목록 → 조회 → 삭제', async () => {
  process.env.FAKE_MODE = 'ok';
  const app = await startApp();
  try {
    const r = await app.call('POST', '/run', { preset: 'to_be', sets: 50, seed: 11 });
    assert.strictEqual(r.status, 200, JSON.stringify(r.data));
    const run = r.data.run;
    assert.strictEqual(run.preset, 'to_be');
    assert.strictEqual(run.sets, 50);
    assert.strictEqual(run.seed, 11);
    assert.strictEqual(run.drawFrom, 1145);
    assert.strictEqual(run.drawTo, 1244);
    assert.strictEqual(run.violations, false);
    assert.strictEqual(run.createdBy, 'admin');
    assert.strictEqual(run.result.sets.length, 50);
    assert.match(run.report, /포트폴리오 리포트/);

    const list = await app.call('GET', '/runs');
    assert.strictEqual(list.data.runs.length, 1);
    assert.strictEqual(list.data.runs[0].id, run.id);
    assert.strictEqual(list.data.runs[0].result, undefined, '목록에는 결과 본문을 싣지 않는다');

    const got = await app.call('GET', `/runs/${run.id}`);
    assert.deepStrictEqual(got.data.run.result.sets, run.result.sets);

    assert.strictEqual((await app.call('DELETE', `/runs/${run.id}`)).status, 200);
    assert.strictEqual((await app.call('GET', `/runs/${run.id}`)).status, 404);
    assert.strictEqual((await app.call('DELETE', `/runs/${run.id}`)).status, 404);
  } finally {
    app.close();
  }
});

test('시드를 안 주면 엔진이 고른 시드를 기록', async () => {
  process.env.FAKE_MODE = 'ok';
  const app = await startApp();
  try {
    const r = await app.call('POST', '/run', { preset: 'as_is' });
    assert.strictEqual(r.status, 200);
    assert.strictEqual(r.data.run.seed, 4242);
    assert.strictEqual(r.data.run.sets, 30);
    assert.strictEqual(r.data.run.preset, 'as_is');
  } finally {
    app.close();
  }
});

test('종료 코드 1 (규칙 위반)은 결과와 함께 violations 표시', async () => {
  process.env.FAKE_MODE = 'violations';
  const app = await startApp();
  try {
    const r = await app.call('POST', '/run', {});
    assert.strictEqual(r.status, 200);
    assert.strictEqual(r.data.run.violations, true);
  } finally {
    app.close();
  }
});

test('엔진 오류는 500과 오류 내용', async () => {
  process.env.FAKE_MODE = 'crash';
  const app = await startApp();
  try {
    const r = await app.call('POST', '/run', {});
    assert.strictEqual(r.status, 500);
    assert.match(r.data.detail, /데이터 검증 실패/);
    assert.strictEqual((await app.call('GET', '/runs')).data.runs.length, 0);
  } finally {
    app.close();
  }
});

test('결과 파일이 없으면 500', async () => {
  process.env.FAKE_MODE = 'nojson';
  const app = await startApp();
  try {
    const r = await app.call('POST', '/run', {});
    assert.strictEqual(r.status, 500);
    assert.match(r.data.error, /결과를 읽지 못했어요/);
  } finally {
    app.close();
  }
});

test('계산 중에 또 실행하면 409, 끝나면 다시 가능', async () => {
  process.env.FAKE_MODE = 'slow';
  const app = await startApp();
  try {
    const first = app.call('POST', '/run', {});
    await new Promise((r) => setTimeout(r, 500));
    const status = await app.call('GET', '/status');
    assert.strictEqual(status.data.running, true);
    const second = await app.call('POST', '/run', {});
    assert.strictEqual(second.status, 409);
    assert.strictEqual((await first).status, 200);
    process.env.FAKE_MODE = 'ok';
    assert.strictEqual((await app.call('POST', '/run', {})).status, 200);
  } finally {
    app.close();
  }
});

test('시간 제한을 넘기면 504, 그다음 실행은 정상', async () => {
  process.env.FAKE_MODE = 'slow';
  const app = await startApp({ timeoutMs: 1000 });
  try {
    const r = await app.call('POST', '/run', {});
    assert.strictEqual(r.status, 504);
    process.env.FAKE_MODE = 'ok';
    assert.strictEqual((await app.call('POST', '/run', {})).status, 200);
  } finally {
    app.close();
  }
});

test('파이썬을 못 찾으면 500과 설정 안내', async () => {
  const app = await startApp({ pythonPath: 'no-such-python-xyz' });
  try {
    const r = await app.call('POST', '/run', {});
    assert.strictEqual(r.status, 500);
    assert.match(r.data.error, /LOTTO_PYTHON/);
    assert.strictEqual((await app.call('GET', '/status')).data.running, false);
  } finally {
    app.close();
  }
});

test('엔진 폴더가 설정되지 않으면 500', async () => {
  const app = await startApp({ lottoOptDir: '' });
  try {
    const r = await app.call('POST', '/run', {});
    assert.strictEqual(r.status, 500);
    assert.match(r.data.error, /LOTTO_OPT_DIR/);
  } finally {
    app.close();
  }
});

async function makeRun(app) {
  process.env.FAKE_MODE = 'ok';
  const r = await app.call('POST', '/run', { sets: 30, seed: 7 });
  assert.strictEqual(r.status, 200, JSON.stringify(r.data));
  return r.data.run;
}

test('당첨 확인: 기본은 최신 회차, 세트별 등수와 요약', async () => {
  process.env.FAKE_CHECK = 'ok';
  const app = await startApp();
  try {
    const run = await makeRun(app);
    const r = await app.call('POST', `/runs/${run.id}/check`, {});
    assert.strictEqual(r.status, 200, JSON.stringify(r.data));
    const c = r.data.check;
    assert.strictEqual(c.draw.draw_no, 1244);
    assert.deepStrictEqual(c.numbers, [1, 7, 13, 19, 25, 31]);
    assert.strictEqual(c.results.length, 30);
    assert.strictEqual(c.results[0].rank, 1);
    assert.deepStrictEqual(c.results[0].matched, [1, 7, 13, 19, 25, 31]);
    assert.strictEqual(c.summary.best_rank, 1);
    assert.strictEqual(c.summary.sets, 30);
    assert.deepStrictEqual(c.portfolio.range, [1145, 1244]);
  } finally {
    app.close();
  }
});

test('당첨 확인: 회차 지정, 직접 입력, 없는 회차', async () => {
  process.env.FAKE_CHECK = 'ok';
  const app = await startApp();
  try {
    const run = await makeRun(app);
    const byDraw = await app.call('POST', `/runs/${run.id}/check`, { draw: 1243 });
    assert.strictEqual(byDraw.status, 200);
    assert.strictEqual(byDraw.data.check.draw.draw_no, 1243);

    const manual = await app.call('POST', `/runs/${run.id}/check`, { numbers: [8, 14, 20, 26, 32, 1], bonus: 38 });
    assert.strictEqual(manual.status, 200);
    assert.strictEqual(manual.data.check.draw, null);
    assert.strictEqual(manual.data.check.results[1].rank, 2, '5개 + 보너스 = 2등');

    const missing = await app.call('POST', `/runs/${run.id}/check`, { draw: 1300 });
    assert.strictEqual(missing.status, 422);
    assert.match(missing.data.error, /제1300회 당첨번호가 데이터에 없습니다/);
  } finally {
    app.close();
  }
});

test('상태에 당첨 확인 기능 표시, 모르는 경로는 한국어 404', async () => {
  const app = await startApp();
  try {
    assert.deepStrictEqual((await app.call('GET', '/status')).data.features, ['check']);
    const r = await app.call('POST', '/runs/1/nope', {});
    assert.strictEqual(r.status, 404);
    assert.match(r.data.error, /로또 API에 없는 경로/);
  } finally {
    app.close();
  }
});

test('당첨 확인: 잘못된 입력은 400, 없는 결과는 404', async () => {
  const app = await startApp();
  try {
    const run = await makeRun(app);
    const url = `/runs/${run.id}/check`;
    for (const body of [
      { draw: 0 }, { draw: 1.5 }, { draw: '1244; del *' },
      { numbers: [1, 2, 3, 4, 5], bonus: 6 }, { numbers: [1, 2, 3, 4, 5, 5], bonus: 6 },
      { numbers: [1, 2, 3, 4, 5, 46], bonus: 7 }, { numbers: [1, 2, 3, 4, 5, 6], bonus: 6 },
      { numbers: [1, 2, 3, 4, 5, 6] }, { numbers: '1,2,3,4,5,6', bonus: 7 },
    ]) {
      assert.strictEqual((await app.call('POST', url, body)).status, 400, JSON.stringify(body));
    }
    assert.strictEqual((await app.call('POST', '/runs/999/check', {})).status, 404);
  } finally {
    app.close();
  }
});

test('당첨 확인: 엔진이 옛 버전이면 501과 업데이트 안내', async () => {
  process.env.FAKE_CHECK = 'old';
  const app = await startApp();
  try {
    const run = await makeRun(app);
    const r = await app.call('POST', `/runs/${run.id}/check`, {});
    assert.strictEqual(r.status, 501);
    assert.match(r.data.error, /당첨 확인 기능이 아직 없어요/);
  } finally {
    process.env.FAKE_CHECK = 'ok';
    app.close();
  }
});

test('당첨 확인: 시간 초과 504, 읽을 수 없는 출력 500, 계산 중에도 가능', async () => {
  const app = await startApp({ checkTimeoutMs: 1000 });
  try {
    const run = await makeRun(app);
    process.env.FAKE_CHECK = 'slow';
    assert.strictEqual((await app.call('POST', `/runs/${run.id}/check`, {})).status, 504);
    process.env.FAKE_CHECK = 'garbage';
    const bad = await app.call('POST', `/runs/${run.id}/check`, {});
    assert.strictEqual(bad.status, 500);
    assert.match(bad.data.error, /결과를 읽지 못했어요/);

    process.env.FAKE_CHECK = 'ok';
    process.env.FAKE_MODE = 'slow';
    const pending = app.call('POST', '/run', {});
    await new Promise((r) => setTimeout(r, 500));
    assert.strictEqual((await app.call('POST', `/runs/${run.id}/check`, {})).status, 200);
    assert.strictEqual((await pending).status, 200);
  } finally {
    process.env.FAKE_CHECK = 'ok';
    process.env.FAKE_MODE = 'ok';
    app.close();
  }
});

test('진짜 엔진으로 30세트 (LOTTO_REAL_OPT_DIR 이 있을 때만)', { skip: !process.env.LOTTO_REAL_OPT_DIR, timeout: 300000 }, async (t) => {
  delete process.env.FAKE_MODE;
  const app = await startApp({ lottoOptDir: process.env.LOTTO_REAL_OPT_DIR });
  try {
    const r = await app.call('POST', '/run', { preset: 'to_be', sets: 30, seed: 11 });
    assert.strictEqual(r.status, 200, JSON.stringify(r.data).slice(0, 2000));
    const run = r.data.run;
    assert.strictEqual(run.result.sets.length, 30);
    assert.ok(run.result.sets.every((s) => s.length === 6 && s.every((n) => n >= 1 && n <= 45)));
    assert.strictEqual(run.seed, 11);
    assert.ok(run.drawTo > run.drawFrom);
    assert.match(run.report, /1\/8,145,060/);

    // 당첨 확인 (엔진에 check 명령이 있을 때만)
    const c = await app.call('POST', `/runs/${run.id}/check`, { draw: run.drawTo });
    if (c.status === 501) {
      t.diagnostic('이 엔진에는 check 명령이 없어 당첨 확인 시험은 건너뜀');
    } else {
      assert.strictEqual(c.status, 200, JSON.stringify(c.data).slice(0, 2000));
      assert.strictEqual(c.data.check.draw.draw_no, run.drawTo);
      assert.strictEqual(c.data.check.results.length, 30);
    }
  } finally {
    app.close();
  }
});
