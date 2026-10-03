'use strict';
// 로또 최적화(lotto-opt) 실행 API. 시스템 관리자 전용.
//
//   const { createLottoRouter } = require('./lottoRouter');
//   app.use('/api/lotto', createLottoRouter({ db, guard: requireSystemAdmin }));
//
// lotto-opt(파이썬 CLI)를 자식 프로세스로 돌리고, 결과를 lotto_runs 테이블에 남긴다.
// 엔진 위치와 파이썬 경로는 옵션이나 환경 변수 LOTTO_OPT_DIR, LOTTO_PYTHON 으로 정한다.
const express = require('express');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const PRESETS = ['to_be', 'as_is'];
const SET_SIZES = [30, 50];
const MAX_LOG = 64 * 1024;

const SCHEMA = `
CREATE TABLE IF NOT EXISTS lotto_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  created_by TEXT,
  preset TEXT NOT NULL,
  sets INTEGER NOT NULL,
  seed INTEGER,
  draw_from INTEGER,
  draw_to INTEGER,
  seconds REAL,
  violations INTEGER NOT NULL DEFAULT 0,
  result_json TEXT NOT NULL,
  report_md TEXT
)`;

const LIST_COLUMNS = 'id, created_at, created_by, preset, sets, seed, draw_from, draw_to, seconds, violations';

function toRun(row, full) {
  const run = {
    id: row.id,
    createdAt: row.created_at,
    createdBy: row.created_by,
    preset: row.preset,
    sets: row.sets,
    seed: row.seed,
    drawFrom: row.draw_from,
    drawTo: row.draw_to,
    seconds: row.seconds,
    violations: Boolean(row.violations),
  };
  if (full) {
    run.result = JSON.parse(row.result_json);
    run.report = row.report_md || '';
  }
  return run;
}

function tail(text, n) {
  return text.length > n ? text.slice(-n) : text;
}

function createLottoRouter(options = {}) {
  const {
    db,
    guard,
    pythonPath = process.env.LOTTO_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
    lottoOptDir = process.env.LOTTO_OPT_DIR,
    timeoutMs = Number(process.env.LOTTO_TIMEOUT_MS) || 5 * 60 * 1000,
    userOf = (req) => (req.user && (req.user.username || req.user.name)) || null,
  } = options;
  if (!db) throw new Error('createLottoRouter: db(better-sqlite3)가 필요합니다');
  if (typeof guard !== 'function') throw new Error('createLottoRouter: guard(시스템 관리자 확인 미들웨어)가 필요합니다');

  db.exec(SCHEMA);
  const insertRun = db.prepare(`INSERT INTO lotto_runs
    (created_at, created_by, preset, sets, seed, draw_from, draw_to, seconds, violations, result_json, report_md)
    VALUES (@created_at, @created_by, @preset, @sets, @seed, @draw_from, @draw_to, @seconds, @violations, @result_json, @report_md)`);
  const listRuns = db.prepare(`SELECT ${LIST_COLUMNS} FROM lotto_runs ORDER BY id DESC LIMIT ?`);
  const getRun = db.prepare('SELECT * FROM lotto_runs WHERE id = ?');
  const deleteRun = db.prepare('DELETE FROM lotto_runs WHERE id = ?');

  const router = express.Router();
  router.use(guard);
  router.use(express.json({ limit: '10kb' }));

  let running = null; // 한 번에 하나만 계산한다 (CPU를 많이 쓴다)

  router.get('/status', (req, res) => {
    res.json({
      running: Boolean(running),
      startedAt: running ? running.startedAt : null,
      configured: Boolean(lottoOptDir),
    });
  });

  router.post('/run', (req, res) => {
    const body = req.body || {};
    const preset = body.preset == null ? 'to_be' : body.preset;
    const sets = body.sets == null ? 30 : Number(body.sets);
    let seed = null;
    if (!PRESETS.includes(preset)) {
      return res.status(400).json({ error: '방식은 개선안(to_be) 또는 원안(as_is)만 고를 수 있어요.' });
    }
    if (!SET_SIZES.includes(sets)) {
      return res.status(400).json({ error: '세트 수는 30 또는 50만 고를 수 있어요.' });
    }
    if (body.seed != null && body.seed !== '') {
      seed = Number(body.seed);
      if (!Number.isInteger(seed) || seed < 1 || seed > 999999999) {
        return res.status(400).json({ error: '시드는 1 이상의 정수로 넣어 주세요. 비워 두면 매번 새 조합이 나와요.' });
      }
    }
    if (!lottoOptDir) {
      return res.status(500).json({ error: '로또 엔진 폴더(LOTTO_OPT_DIR)가 설정되지 않았어요.' });
    }
    if (running) {
      return res.status(409).json({ error: '다른 계산이 진행 중이에요. 끝난 뒤 다시 실행해 주세요.' });
    }

    running = { startedAt: new Date().toISOString() };
    const createdBy = userOf(req);
    const started = Date.now();
    let outDir = null;
    let log = '';
    let timedOut = false;
    let done = false;
    let timer = null;

    // 브라우저가 먼저 끊겨도 계산은 끝까지 하고 기록에 남긴다
    const finish = (status, payload) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      running = null;
      if (outDir) fs.rmSync(outDir, { recursive: true, force: true });
      if (!res.headersSent) res.status(status).json(payload);
    };

    try {
      outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lotto-run-'));
    } catch (err) {
      return finish(500, { error: '임시 폴더를 만들지 못했어요.', detail: String(err.message || err) });
    }
    const args = ['cli.py', 'run', '--config', path.join('config', `${preset}.yaml`),
      '--sets', String(sets), '--out', outDir];
    if (seed !== null) args.push('--seed', String(seed));

    let child;
    try {
      child = spawn(pythonPath, args, {
        cwd: lottoOptDir,
        windowsHide: true,
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      });
    } catch (err) {
      return finish(500, { error: '로또 엔진을 시작하지 못했어요.', detail: String(err.message || err) });
    }

    const onData = (chunk) => {
      log = tail(log + chunk.toString('utf8'), MAX_LOG);
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    timer = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, timeoutMs);

    child.on('error', (err) => {
      const missing = err && err.code === 'ENOENT';
      finish(500, {
        error: missing
          ? '파이썬 또는 로또 엔진 폴더를 찾지 못했어요. LOTTO_PYTHON, LOTTO_OPT_DIR 설정을 확인해 주세요.'
          : '로또 엔진을 실행하지 못했어요.',
        detail: String(err.message || err),
      });
    });

    child.on('close', (code) => {
      if (done) return;
      if (timedOut) {
        return finish(504, { error: `계산이 ${Math.round(timeoutMs / 60000)}분을 넘겨 멈췄어요.`, detail: tail(log, 2000) });
      }
      // 0 = 정상, 1 = 결과는 나왔지만 독립 검증에서 규칙 위반이 나옴
      if (code !== 0 && code !== 1) {
        return finish(500, { error: '계산 중 오류가 났어요.', detail: tail(log, 2000) });
      }
      let result;
      let report = '';
      try {
        const file = fs.readdirSync(outDir).find((f) => f.endsWith('.json'));
        if (!file) throw new Error('결과 파일(.json)이 없습니다');
        result = JSON.parse(fs.readFileSync(path.join(outDir, file), 'utf8'));
        const md = path.join(outDir, file.replace(/\.json$/, '.md'));
        if (fs.existsSync(md)) report = fs.readFileSync(md, 'utf8');
      } catch (err) {
        return finish(500, { error: '계산 결과를 읽지 못했어요.', detail: `${err.message}\n${tail(log, 1500)}` });
      }
      const range = Array.isArray(result.range) ? result.range : [];
      const row = {
        created_at: new Date().toISOString(),
        created_by: createdBy,
        preset,
        sets: Array.isArray(result.sets) ? result.sets.length : sets,
        seed: Number.isInteger(result.seed) ? result.seed : seed,
        draw_from: range[0] == null ? null : range[0],
        draw_to: range[1] == null ? null : range[1],
        seconds: Math.round((Date.now() - started) / 100) / 10,
        violations: code === 1 ? 1 : 0,
        result_json: JSON.stringify(result),
        report_md: report,
      };
      let id;
      try {
        id = insertRun.run(row).lastInsertRowid;
      } catch (err) {
        return finish(500, { error: '결과를 저장하지 못했어요.', detail: String(err.message || err) });
      }
      finish(200, { run: toRun(getRun.get(id), true) });
    });
  });

  router.get('/runs', (req, res) => {
    const limit = Math.min(Math.max(parseInt(req.query.limit, 10) || 50, 1), 200);
    res.json({ runs: listRuns.all(limit).map((r) => toRun(r, false)) });
  });

  router.get('/runs/:id', (req, res) => {
    const row = getRun.get(Number(req.params.id));
    if (!row) return res.status(404).json({ error: '그 결과를 찾지 못했어요.' });
    res.json({ run: toRun(row, true) });
  });

  router.delete('/runs/:id', (req, res) => {
    const info = deleteRun.run(Number(req.params.id));
    if (!info.changes) return res.status(404).json({ error: '그 결과를 찾지 못했어요.' });
    res.json({ ok: true });
  });

  // 깨진 JSON 요청은 HTML 오류 페이지 대신 JSON 으로 답한다
  router.use((err, req, res, next) => {
    if (err && err.type === 'entity.parse.failed') return res.status(400).json({ error: '요청 형식이 잘못됐어요.' });
    return next(err);
  });

  return router;
}

module.exports = { createLottoRouter };
