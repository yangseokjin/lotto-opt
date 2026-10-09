// 로또 최적화 페이지 (시스템 관리자 전용). 서버 쪽은 server/lottoRouter.js (/api/lotto).
import { useEffect, useRef, useState } from 'react';
import api from '../api';

const PRESET_LABEL = { to_be: '개선안', as_is: '원안', spread: '분산 우선' }; // as_is: 예전에 저장된 결과 표시용 (새로 실행은 안 됨)
const ODDS_NOTE =
  '모든 조합의 1등 확률은 1/8,145,060으로 같습니다. 이 페이지는 여러 세트에 번호를 고르게 나눠 담을 뿐, 당첨 확률을 높이지 않습니다.';
const RUN_TIMEOUT_MS = 10 * 60 * 1000; // 계산이 20~60초 걸려서 기본 요청 시간 제한을 쓰지 않는다
const CHECK_TIMEOUT_MS = 90 * 1000; // 당첨번호를 인터넷에서 받아 오느라 몇 초 걸릴 수 있다
const RANK_LABEL = { 1: '1등', 2: '2등', 3: '3등', 4: '4등', 5: '5등' };

// 동행복권 공 색깔
function ballColor(n) {
  if (n <= 10) return '#fbc400';
  if (n <= 20) return '#69c8f2';
  if (n <= 30) return '#ff7272';
  if (n <= 40) return '#aaaaaa';
  return '#b0d840';
}

const pad = (n) => String(n).padStart(2, '0');
const pct = (p) => (typeof p === 'number' ? `${(p * 100).toFixed(1)}%` : '-');

function errorText(e) {
  const data = e && e.response && e.response.data;
  if (data && data.error) return data.detail ? `${data.error}\n${data.detail}` : data.error;
  return (e && e.message) || '알 수 없는 오류가 났어요.';
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function setInfo(s, r) {
  const diffs = new Set();
  for (let i = 0; i < s.length; i += 1) for (let j = i + 1; j < s.length; j += 1) diffs.add(s[j] - s[i]);
  const odd = s.filter((n) => n % 2 === 1).length;
  const low = s.filter((n) => n <= 22).length;
  return {
    sum: s.reduce((a, b) => a + b, 0),
    oddEven: `${odd}:${s.length - odd}`,
    lowHigh: `${low}:${s.length - low}`,
    ac: diffs.size - (s.length - 1),
    hot: s.filter((n) => r.hot.includes(n)).length,
    warm: s.filter((n) => r.warm.includes(n)).length,
    cold: s.filter((n) => r.cold.includes(n)).length,
    carry: s.filter((n) => r.carry.includes(n)),
  };
}

function distText(d) {
  return Object.entries(d || {})
    .map(([k, v]) => `${k === 'other' ? '기타' : k} ${v}`)
    .join(' · ');
}

async function copyText(text) {
  // 인트라넷이 http 라서 navigator.clipboard 가 없을 수 있다
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
}

function downloadCsv(run) {
  const r = run.result;
  const header = ['세트', '번호1', '번호2', '번호3', '번호4', '번호5', '번호6', '합계', '홀짝', '저고', 'AC', 'Hot', 'Warm', 'Cold', '이월수'];
  const rows = r.sets.map((s, i) => {
    const x = setInfo(s, r);
    return [i + 1, ...s, x.sum, x.oddEven, x.lowHigh, x.ac, x.hot, x.warm, x.cold, x.carry.map(pad).join(' ')];
  });
  const cell = (v) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const csv = `﻿${[header, ...rows].map((row) => row.map(cell).join(',')).join('\r\n')}`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `로또_${PRESET_LABEL[run.preset] || run.preset}_${r.sets.length}세트_시드${r.seed}_제${run.drawTo}회까지.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Ball({ n, small }) {
  return (
    <span className={small ? 'lo-ball lo-ball-sm' : 'lo-ball'} style={{ background: ballColor(n) }}>
      {n}
    </span>
  );
}

function NumberGroup({ title, nums, highlight }) {
  return (
    <div className="lo-group">
      <div className="lo-group-title">
        {title} <span className="lo-muted">{nums.length}개</span>
      </div>
      <div className="lo-balls">
        {nums.map((n) => (
          <span key={n} className={highlight && highlight.includes(n) ? 'lo-top' : undefined}>
            <Ball n={n} small />
          </span>
        ))}
      </div>
    </div>
  );
}

// 404인데 로또 라우터의 한국어 답이 아니면 (예: "Not found") 요청이 인트라넷 공통 404까지 간 것이다.
// 곧 돌고 있는 서버의 lottoRouter.js 가 당첨 확인이 없는 옛 파일이라는 뜻이다.
function checkErrorText(e) {
  const res = e && e.response;
  const ours = res && res.data && typeof res.data.error === 'string' && /[가-힣]/.test(res.data.error);
  if (res && res.status === 404 && !ours) {
    return '서버가 아직 당첨 확인이 없는 옛 버전으로 돌고 있어요. 인트라넷 서버의 lottoRouter.js 를 새 파일로 바꾸고 서버를 다시 시작해 주세요 (APPLY.md "당첨 확인 추가" 3단계).';
  }
  return errorText(e);
}

function parseNumbers(text) {
  return text
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(Number);
}

function CheckResult({ check, drawTo }) {
  const sm = check.summary;
  const draw = check.draw;
  const win = new Set(check.numbers);
  const inSample = draw && drawTo && draw.draw_no <= drawTo;
  return (
    <div className="lo-check-result">
      <div className="lo-check-draw">
        <span className="lo-result-title">{draw ? `제${draw.draw_no}회 (${draw.date})` : '직접 입력한 번호'}</span>
        <div className="lo-balls">
          {check.numbers.map((n) => (
            <Ball key={n} n={n} />
          ))}
          <span className="lo-plus">+</span>
          <Ball n={check.bonus} />
        </div>
      </div>
      {inSample ? (
        <div className="lo-muted">
          {check.note || `참고: 이 결과는 제${drawTo}회까지의 당첨번호로 만들어서, 제${draw.draw_no}회는 이미 계산에 들어간 회차예요.`}
        </div>
      ) : null}
      <div className="lo-rank-row">
        <span className={sm.best_rank ? 'lo-rank-chip lo-rank-best' : 'lo-rank-chip'}>
          최고 등수 {sm.best_rank ? RANK_LABEL[sm.best_rank] : '낙첨'}
        </span>
        {[1, 2, 3, 4, 5].map((k) => (
          <span key={k} className={sm.by_rank[String(k)] ? 'lo-rank-chip lo-rank-hit' : 'lo-rank-chip'}>
            {RANK_LABEL[k]} {sm.by_rank[String(k)]}
          </span>
        ))}
        <span className="lo-rank-chip">낙첨 {sm.sets - sm.winning_sets}</span>
      </div>
      <div className="lo-muted">
        일치 개수별:{' '}
        {Object.entries(sm.by_match_count)
          .filter(([, v]) => v)
          .map(([k, v]) => `${k}개 ${v}세트`)
          .join(' · ')}
      </div>
      <div className="lo-table-wrap">
        <table className="lo-table">
          <thead>
            <tr>
              <th>세트</th>
              <th>번호 (색 = 맞은 번호)</th>
              <th>일치</th>
              <th>등수</th>
            </tr>
          </thead>
          <tbody>
            {check.results.map((r) => (
              <tr key={r.set} className={r.rank ? 'lo-win' : undefined}>
                <td className="lo-num">{pad(r.set)}</td>
                <td>
                  <div className="lo-balls lo-nowrap">
                    {r.numbers.map((n) => (
                      <span key={n} className={win.has(n) ? undefined : 'lo-miss'}>
                        <Ball n={n} />
                      </span>
                    ))}
                  </div>
                </td>
                <td className="lo-num">
                  {r.match_count}개{r.bonus_hit ? '+보너스' : ''}
                </td>
                <td>{r.rank ? <b>{RANK_LABEL[r.rank]}</b> : <span className="lo-muted">낙첨</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CheckPanel({ run, request }) {
  const [draw, setDraw] = useState('');
  const [manual, setManual] = useState(false);
  const [numbers, setNumbers] = useState('');
  const [bonus, setBonus] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [check, setCheck] = useState(null);
  const box = useRef(null);

  const doCheck = async (e) => {
    if (e) e.preventDefault();
    setError('');
    let body = {};
    if (manual) {
      body = { numbers: parseNumbers(numbers), bonus: Number(bonus) };
    } else if (draw.trim()) {
      body = { draw: Number(draw.trim()) };
    }
    setBusy(true);
    try {
      const { data } = await api.post(`/lotto/runs/${run.id}/check`, body, { timeout: CHECK_TIMEOUT_MS });
      setCheck(data.check);
    } catch (err) {
      setError(checkErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  // "지난 결과"의 당첨 확인 버튼을 누르면 그 결과가 노린 회차(분석 마지막 회차 + 1)로 바로 확인한다
  useEffect(() => {
    if (!request) return;
    if (box.current && box.current.scrollIntoView) box.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    doCheck();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  return (
    <div className="lo-check" ref={box}>
      <div className="lo-section-title">당첨 확인</div>
      <form className="lo-form" onSubmit={doCheck}>
        {manual ? (
          <>
            <label>
              당첨번호 6개
              <input
                type="text"
                inputMode="numeric"
                placeholder="예: 1 7 13 19 25 31"
                value={numbers}
                onChange={(e) => setNumbers(e.target.value)}
                disabled={busy}
              />
            </label>
            <label>
              보너스
              <input
                type="number"
                min="1"
                max="45"
                className="lo-short"
                value={bonus}
                onChange={(e) => setBonus(e.target.value)}
                disabled={busy}
              />
            </label>
          </>
        ) : (
          <label>
            회차 (선택)
            <input
              type="number"
              min="1"
              step="1"
              inputMode="numeric"
              placeholder="비우면 이 결과가 노린 회차"
              value={draw}
              onChange={(e) => setDraw(e.target.value)}
              disabled={busy}
            />
          </label>
        )}
        <button type="submit" className="lo-btn lo-btn-primary" disabled={busy}>
          {busy ? '확인 중…' : '당첨 확인'}
        </button>
        <button type="button" className="lo-link" onClick={() => setManual(!manual)} disabled={busy}>
          {manual ? '회차로 확인하기' : '번호 직접 입력하기'}
        </button>
      </form>
      {error ? <div className="lo-error">{error}</div> : null}
      {check ? <CheckResult check={check} drawTo={run.drawTo} /> : null}
    </div>
  );
}

function RunResult({ run, onCopied, checkRequest }) {
  const r = run.result;
  const sm = r.summary || {};
  const cg = sm.coverage_groups || {};
  const top = r.hot.slice(0, 5);
  const [localRequest, setLocalRequest] = useState(0);
  const copyNumbers = async () => {
    const text = r.sets.map((s, i) => `${pad(i + 1)}세트  ${s.map(pad).join(' ')}`).join('\n');
    try {
      await copyText(text);
      onCopied('번호를 복사했어요.');
    } catch (e) {
      onCopied('복사하지 못했어요. 표를 직접 선택해 복사해 주세요.');
    }
  };
  return (
    <div className="lo-card">
      <div className="lo-result-head">
        <div>
          <div className="lo-result-title">
            제{run.drawFrom}회 ~ 제{run.drawTo}회 기준 · {PRESET_LABEL[run.preset] || run.preset} · {r.sets.length}세트
            {` · 제${r.target_draw || run.drawTo + 1}회용`}
          </div>
          <div className="lo-muted">
            시드 {r.seed} · {formatDate(run.createdAt)}
            {run.createdBy ? ` · ${run.createdBy}` : ''}
            {run.seconds != null ? ` · ${Math.round(run.seconds)}초` : ''}
          </div>
        </div>
        <div className="lo-actions">
          <span className={run.violations ? 'lo-badge lo-badge-bad' : 'lo-badge lo-badge-ok'}>
            {run.violations ? '규칙 위반 있음' : '규칙 위반 없음'}
          </span>
          <button type="button" className="lo-btn" onClick={copyNumbers}>
            번호 복사
          </button>
          <button type="button" className="lo-btn" onClick={() => downloadCsv(run)}>
            엑셀(CSV) 저장
          </button>
          <button type="button" className="lo-btn" onClick={() => setLocalRequest(Date.now())}>
            당첨 확인
          </button>
        </div>
      </div>

      <CheckPanel run={run} request={Math.max(localRequest, checkRequest || 0)} />

      <div className="lo-groups">
        <NumberGroup title="Hot (테두리 = 최상위 5)" nums={r.hot} highlight={top} />
        <NumberGroup title="Warm" nums={r.warm} />
        <NumberGroup title="Cold" nums={r.cold} />
        <NumberGroup title="직전 회차 이월수" nums={r.carry} />
      </div>

      <div className="lo-table-wrap">
        <table className="lo-table">
          <thead>
            <tr>
              <th>세트</th>
              <th>번호</th>
              <th>합계</th>
              <th>홀짝</th>
              <th>저고</th>
              <th>AC</th>
              <th>H/W/C</th>
              <th>이월수</th>
            </tr>
          </thead>
          <tbody>
            {r.sets.map((s, i) => {
              const x = setInfo(s, r);
              return (
                <tr key={i}>
                  <td className="lo-num">{pad(i + 1)}</td>
                  <td>
                    <div className="lo-balls lo-nowrap">
                      {s.map((n) => (
                        <Ball key={n} n={n} />
                      ))}
                    </div>
                  </td>
                  <td className="lo-num">{x.sum}</td>
                  <td className="lo-num">{x.oddEven}</td>
                  <td className="lo-num">{x.lowHigh}</td>
                  <td className="lo-num">{x.ac}</td>
                  <td className="lo-num">
                    {x.hot}/{x.warm}/{x.cold}
                  </td>
                  <td className="lo-num">{x.carry.length ? x.carry.map(pad).join(', ') : '-'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ul className="lo-summary">
        <li>
          번호 커버리지 {sm.coverage}/45 (Hot {cg.hot}/{r.hot.length}, Warm {cg.warm}/{r.warm.length}, Cold {cg.cold}/
          {r.cold.length})
        </li>
        <li>홀짝 분포: {distText(sm.odd_even)}</li>
        <li>저고 분포: {distText(sm.low_high)}</li>
        <li>
          세트 간 겹침: 최대 {sm.overlap_max}개 (2개 공유 {sm.overlap2}쌍, 3개 공유 {sm.overlap3}쌍)
        </li>
        <li>
          번호별 사용 횟수: {sm.appear_min}~{sm.appear_max}회 · 합계 {sm.sum_min}~{sm.sum_max}
        </li>
        {r.odds && r.odds.best ? (
          <li>
            한 회차에 하나라도 5등 이상일 확률 {pct(r.odds.best['3'])} (무작위로 고른 {r.odds.sets}세트는{' '}
            {pct(r.odds.random_best && r.odds.random_best['3'])}) · 4등 이상 {pct(r.odds.best['4'])}
          </li>
        ) : null}
        <li>조건 완화: {r.relaxed && r.relaxed.length ? r.relaxed.join(', ') : '없음'}</li>
      </ul>

      {run.report ? (
        <details className="lo-report">
          <summary>전체 리포트 보기</summary>
          <pre>{run.report}</pre>
        </details>
      ) : null}
    </div>
  );
}

export default function LottoOptimizer() {
  const [preset, setPreset] = useState('to_be');
  const [sets, setSets] = useState(30);
  const [seed, setSeed] = useState('');
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [current, setCurrent] = useState(null);
  const [runs, setRuns] = useState([]);
  const [checkRequest, setCheckRequest] = useState(0);

  const loadRuns = async () => {
    const { data } = await api.get('/lotto/runs');
    setRuns(data.runs || []);
    return data.runs || [];
  };

  const openRun = async (id, withCheck = false) => {
    setError('');
    try {
      const { data } = await api.get(`/lotto/runs/${id}`);
      setCurrent(data.run);
      setCheckRequest(withCheck ? Date.now() : 0);
    } catch (e) {
      setError(errorText(e));
    }
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const list = await loadRuns();
        if (alive && list.length) {
          const { data } = await api.get(`/lotto/runs/${list[0].id}`);
          if (alive) setCurrent(data.run);
        }
      } catch (e) {
        if (alive) setError(errorText(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!running) return undefined;
    const started = Date.now();
    setElapsed(0);
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(t);
  }, [running]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(''), 2500);
    return () => clearTimeout(t);
  }, [notice]);

  const run = async (e) => {
    e.preventDefault();
    setError('');
    setRunning(true);
    try {
      const body = { preset, sets };
      if (seed.trim()) body.seed = Number(seed.trim());
      const { data } = await api.post('/lotto/run', body, { timeout: RUN_TIMEOUT_MS });
      setCurrent(data.run);
      setCheckRequest(0);
      await loadRuns();
    } catch (err) {
      setError(errorText(err));
      loadRuns().catch(() => {});
    } finally {
      setRunning(false);
    }
  };

  const remove = async (id) => {
    if (!window.confirm('이 결과를 지울까요?')) return;
    setError('');
    try {
      await api.delete(`/lotto/runs/${id}`);
      const list = await loadRuns();
      if (current && current.id === id) {
        if (list.length) await openRun(list[0].id);
        else setCurrent(null);
      }
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <div className="lo-page">
      <style>{CSS}</style>
      <div className="lo-header">
        <h2>로또 최적화</h2>
        <span className="lo-muted">시스템 관리자 전용 · lotto-opt 엔진</span>
      </div>

      <form className="lo-card lo-form" onSubmit={run}>
        <label>
          방식
          <select
            value={preset}
            onChange={(e) => {
              setPreset(e.target.value);
              if (e.target.value === 'spread') setSets(50); // 분산 우선은 50세트가 기본
            }}
            disabled={running}
          >
            <option value="to_be">개선안</option>
            <option value="spread">분산 우선 (세트끼리 덜 겹치게)</option>
          </select>
        </label>
        <label>
          세트 수
          <select value={sets} onChange={(e) => setSets(Number(e.target.value))} disabled={running}>
            <option value={30}>30세트</option>
            <option value={50}>50세트</option>
          </select>
        </label>
        <label>
          시드 (선택)
          <input
            type="number"
            min="1"
            step="1"
            inputMode="numeric"
            placeholder="비우면 매번 새 조합"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            disabled={running}
          />
        </label>
        <button type="submit" className="lo-btn lo-btn-primary" disabled={running}>
          {running ? `계산 중… ${elapsed}초` : '실행'}
        </button>
        <div className="lo-hint">
          최근 100회 당첨번호를 받아 계산해요. 보통 20~60초 걸려요. 같은 시드를 넣으면 같은 결과가 다시 나와요.
          {preset === 'spread'
            ? ' 분산 우선은 세트끼리 번호를 덜 겹치게 해서, 한 회차에 하나라도 5등 이상 나올 확률을 높여요(50세트 약 80%, 무작위 약 70%). 대신 홀짝·저고 같은 목표 분포와는 조금 더 달라져요.'
            : ''}
        </div>
      </form>

      {error ? <div className="lo-error">{error}</div> : null}
      {notice ? <div className="lo-notice">{notice}</div> : null}

      {current ? <RunResult key={current.id} run={current} onCopied={setNotice} checkRequest={checkRequest} /> : null}

      <div className="lo-card">
        <div className="lo-section-title">지난 결과</div>
        {runs.length === 0 ? (
          <div className="lo-muted">아직 결과가 없어요. 위에서 실행해 보세요.</div>
        ) : (
          <div className="lo-table-wrap">
            <table className="lo-table lo-history">
              <thead>
                <tr>
                  <th>날짜</th>
                  <th>방식</th>
                  <th>세트</th>
                  <th>시드</th>
                  <th>기준 회차</th>
                  <th>실행한 사람</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.map((h) => (
                  <tr key={h.id} className={current && current.id === h.id ? 'lo-selected' : undefined}>
                    <td>
                      <button type="button" className="lo-link" onClick={() => openRun(h.id)}>
                        {formatDate(h.createdAt)}
                      </button>
                    </td>
                    <td>{PRESET_LABEL[h.preset] || h.preset}</td>
                    <td className="lo-num">{h.sets}</td>
                    <td className="lo-num">{h.seed}</td>
                    <td className="lo-num">~제{h.drawTo}회</td>
                    <td>{h.createdBy || ''}</td>
                    <td className="lo-row-actions">
                      <button type="button" className="lo-link" onClick={() => openRun(h.id, true)}>
                        당첨 확인
                      </button>
                      <button type="button" className="lo-link lo-danger" onClick={() => remove(h.id)}>
                        삭제
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="lo-odds">{ODDS_NOTE}</p>
    </div>
  );
}

const CSS = `
.lo-page { max-width: 1100px; margin: 0 auto; padding: 16px; color: #1f2937; }
.lo-header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.lo-header h2 { margin: 0; font-size: 22px; }
.lo-muted { color: #6b7280; font-size: 13px; }
.lo-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; margin-bottom: 16px; }
.lo-form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px; }
.lo-form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: #374151; }
.lo-form select, .lo-form input { height: 36px; padding: 0 10px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; min-width: 150px; background: #fff; }
.lo-hint { flex-basis: 100%; color: #6b7280; font-size: 12px; }
.lo-btn { height: 36px; padding: 0 14px; border: 1px solid #d1d5db; border-radius: 6px; background: #fff; font-size: 14px; cursor: pointer; }
.lo-btn:disabled { opacity: .6; cursor: default; }
.lo-btn-primary { background: #2563eb; border-color: #2563eb; color: #fff; min-width: 120px; }
.lo-error { white-space: pre-wrap; background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; border-radius: 8px; padding: 12px; margin-bottom: 16px; font-size: 14px; }
.lo-notice { background: #ecfdf5; border: 1px solid #a7f3d0; color: #065f46; border-radius: 8px; padding: 10px 12px; margin-bottom: 16px; font-size: 14px; }
.lo-result-head { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.lo-result-title { font-weight: 600; font-size: 16px; margin-bottom: 2px; }
.lo-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.lo-badge { font-size: 12px; padding: 4px 8px; border-radius: 999px; }
.lo-badge-ok { background: #ecfdf5; color: #065f46; }
.lo-badge-bad { background: #fef2f2; color: #991b1b; }
.lo-groups { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; margin-bottom: 12px; }
.lo-group-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.lo-balls { display: flex; flex-wrap: wrap; gap: 4px; }
.lo-nowrap { flex-wrap: nowrap; }
.lo-ball { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 50%; color: #fff; font-weight: 700; font-size: 13px; text-shadow: 0 0 2px rgba(0,0,0,.45); flex: none; }
.lo-ball-sm { width: 24px; height: 24px; font-size: 11px; }
.lo-top .lo-ball { box-shadow: 0 0 0 2px #111827; }
.lo-table-wrap { overflow-x: auto; }
.lo-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.lo-table th, .lo-table td { padding: 6px 8px; border-bottom: 1px solid #f3f4f6; text-align: left; white-space: nowrap; }
.lo-table th { color: #6b7280; font-weight: 600; font-size: 12px; }
.lo-num { font-variant-numeric: tabular-nums; }
.lo-summary { margin: 12px 0 0; padding-left: 18px; font-size: 14px; line-height: 1.7; }
.lo-report summary { cursor: pointer; margin-top: 12px; color: #2563eb; font-size: 14px; }
.lo-report pre { white-space: pre-wrap; font-size: 12px; background: #f9fafb; border-radius: 6px; padding: 12px; max-height: 480px; overflow: auto; }
.lo-section-title { font-weight: 600; margin-bottom: 8px; }
.lo-link { background: none; border: none; padding: 0; color: #2563eb; cursor: pointer; font-size: 14px; }
.lo-danger { color: #b91c1c; }
.lo-selected td { background: #eff6ff; }
.lo-check { border-top: 1px solid #f3f4f6; margin: 4px 0 16px; padding-top: 12px; }
.lo-check .lo-form { margin-bottom: 8px; }
.lo-check .lo-error { margin: 8px 0; }
.lo-short { min-width: 80px !important; width: 80px; }
.lo-check-result { display: flex; flex-direction: column; gap: 8px; }
.lo-check-draw { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.lo-plus { align-self: center; color: #6b7280; font-weight: 700; padding: 0 2px; }
.lo-rank-row { display: flex; flex-wrap: wrap; gap: 6px; }
.lo-rank-chip { font-size: 13px; padding: 4px 10px; border-radius: 999px; background: #f3f4f6; color: #374151; font-variant-numeric: tabular-nums; }
.lo-rank-hit { background: #fef3c7; color: #92400e; font-weight: 600; }
.lo-rank-best { background: #1d4ed8; color: #fff; font-weight: 600; }
.lo-miss .lo-ball { background: #e5e7eb !important; color: #9ca3af; text-shadow: none; }
.lo-win td { background: #fffbeb; }
.lo-row-actions { display: flex; gap: 12px; }
.lo-odds { color: #6b7280; font-size: 12px; text-align: center; margin: 8px 0 24px; }
`;
