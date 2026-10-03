# 청정해 인트라넷에 "로또 최적화" 페이지 붙이기 (PC의 Claude Code용 순서)

사무실 PC에서 인트라넷 폴더(`D:\ClAUDE\InOut_JEJUCJH`)를 열어 둔 Claude Code가 이 순서대로 작업합니다.
사장님은 Claude Code에 아래 한 줄만 붙여 넣으면 됩니다.

> https://github.com/yangseokjin/lotto-opt 의 integrations/intranet/APPLY.md 대로 인트라넷에 로또 최적화 페이지를 붙여 줘. 재시작 전에는 꼭 물어봐.

로또 최적화 페이지를 이미 붙인 PC라면 처음부터 다시 하지 말고 맨 아래 "당첨 확인 추가 (이미 붙인 PC)" 만 하면 됩니다.

## 지킬 것
- 운영 중인 인트라넷(포트 4000, `node src\index.js`)은 5단계에서 사장님이 허락하기 전까지 멈추거나 재시작하지 않는다.
- `client/dist` 를 덮어쓰는 빌드(`npm run build`)도 5단계에서만 한다. 시험 빌드는 임시 폴더로 한다.
- 같은 DB로 두 번째 서버를 띄우지 않는다. 메일 확인이나 백업 같은 작업이 두 번 돈다.
- `.env` 와 DB 안의 비밀값(비밀번호, API 키)을 화면에 출력하지 않는다.
- 커밋하지 않은 다른 작업이 있으면 건드리지 말고 먼저 사장님께 알린다. 이 작업은 새 브랜치(예: `lotto-optimizer`)에서 한다.
- 화면과 안내에 "당첨 확률이 오른다"는 표현을 쓰지 않는다. 모든 조합의 1등 확률은 1/8,145,060으로 같다.

## 1. 엔진 준비 (`D:\ClAUDE\lotto-opt`)
1. Python 3.10 이상이 있는지 확인한다: `py -3 --version` 또는 `python --version`. 3.14도 된다.
2. 엔진을 받는다: `git clone https://github.com/yangseokjin/lotto-opt D:\ClAUDE\lotto-opt`. 이미 있으면 `git pull` 한다.
   - lotto-opt v0.2 이상이 필요하다 (README 첫 줄이 `# lotto-opt v0.2`). 당첨 확인 버튼은 엔진의 `check` 명령도 필요하다 (`cli.py` 맨 위 사용법에 `cli.py check` 줄이 있으면 된다).
   - main에 둘 다 없으면 `git checkout claude/project-thread-g77adz` 로 쓴다. 이 브랜치는 v0.2(PR #1) 위에 당첨 확인(PR #3)을 더한 것이다. 두 PR이 main에 합쳐지면 main으로 돌아온다.
3. 가상환경을 만든다: `py -3 -m venv .venv` 후 `.venv\Scripts\python -m pip install -r requirements.txt`.
4. 한 번 돌려 본다: `.venv\Scripts\python cli.py run --config config/to_be.yaml --sets 30 --seed 11 --out <임시 폴더>`.
   20~60초 뒤 `저장: ....json` 이 나오면 성공이다. 최근 당첨번호는 엔진이 인터넷에서 받아 `data\draws.json` 에 저장한다.

## 2. 서버 연결
1. `integrations/intranet/server/lottoRouter.js` 를 `server/src/lottoRouter.js` 로 복사한다. 라우터 파일이 모인 폴더가 따로 있으면 그곳에 둔다.
2. `server/src/index.js` 에서 `app.use('/api', requireAuth)` 뒤, 다른 관리자 API(`/api/db-backup/status` 등)와 같은 위치에 연결한다.
   ```js
   const { createLottoRouter } = require('./lottoRouter');
   app.use('/api/lotto', createLottoRouter({ db, guard: requireSystemAdmin }));
   ```
   - `db` 는 `server/src/db.js` 의 better-sqlite3 객체, `requireSystemAdmin` 은 `server/src/auth.js` 의 미들웨어다. 이름이나 내보내는 방식이 다르면 맞춘다.
   - 실행한 사람 이름은 `req.user.username` 에서 읽는다. 다르면 `userOf: (req) => ...` 옵션으로 맞춘다.
   - `pageAccessGate` 가 `/api/lotto` 를 막으면, `/backup-status` 페이지와 같은 방식으로 등록한다.
   - `auditLogGate` 가 POST/DELETE 에 사유를 요구하면, 다른 페이지가 사유를 보내는 방식을 따른다. 로또 실행은 업무 데이터 수정이 아니므로 기존 예외 방식으로 빼도 된다.
   - 라우터는 처음 연결될 때 `lotto_runs` 테이블만 새로 만든다 (`CREATE TABLE IF NOT EXISTS`). 기존 테이블은 건드리지 않는다.
3. `server/.env` 끝에 두 줄을 덧붙인다. 기존 내용은 출력하지 않는다.
   ```
   LOTTO_OPT_DIR=D:\ClAUDE\lotto-opt
   LOTTO_PYTHON=D:\ClAUDE\lotto-opt\.venv\Scripts\python.exe
   ```
   `index.js` 맨 앞에서 dotenv 가 읽히는지 확인한다. 선택: `LOTTO_TIMEOUT_MS` (기본 5분).

## 3. 화면 연결
1. `integrations/intranet/client/LottoOptimizer.jsx` 를 `client/src/pages/LottoOptimizer.jsx` 로 복사한다.
   - 맨 위 `import api from '../api';` 를 인트라넷 `api.js` 의 내보내기 방식에 맞춘다 (named export면 `import { api } from '../api';`).
   - `api` 의 baseURL 이 `/api` 가 아니면 페이지 안의 `/lotto/...` 경로를 맞춘다.
   - 실행 요청은 `{ timeout: 10분 }` 을 따로 준다. api.js 의 기본 시간 제한이 짧아도 계산(20~60초)이 끊기지 않게 하려는 것이니 그대로 둔다.
2. `client/src/App.jsx` 에 `/backup-status` 와 똑같이 adminOnly 로 등록한다.
   ```jsx
   <Route path="/lotto" element={<Gate page="/lotto" adminOnly user={user}><LottoOptimizer /></Gate>} />
   ```
3. `client/src/components/Nav.jsx` 에 "로또 최적화" 링크를 넣는다. 보이는 조건은 백업 현황 링크와 같은 시스템 관리자 조건으로 한다.
4. 다른 화면과 모양이 너무 다르면 페이지 안의 CSS(`.lo-*`)만 손본다.

## 4. 시험 (운영 중인 인트라넷은 그대로 둔 채)
1. 서버 시험: `D:\ClAUDE\lotto-opt\integrations\intranet` 폴더에서, 인트라넷의 express·better-sqlite3 를 쓰도록 `NODE_PATH` 에 인트라넷 node_modules 를 준다 (npm workspaces라 보통 `D:\ClAUDE\InOut_JEJUCJH\node_modules`, 없으면 `server\node_modules`). 그리고 `node --test test/lottoRouter.test.js` 를 돌린다 (셸에 맞는 문법으로). 시험용 DB는 임시 폴더에 만들어졌다가 지워진다.
   - 진짜 엔진까지 시험하려면 `LOTTO_REAL_OPT_DIR=D:\ClAUDE\lotto-opt`, `LOTTO_REAL_PYTHON=D:\ClAUDE\lotto-opt\.venv\Scripts\python.exe` 를 준다.
   - 17개가 모두 통과해야 한다 (진짜 엔진이 없으면 1개는 건너뜀). 관리자가 아닌 요청이 403으로 막히는 것도 여기서 확인된다.
2. 화면 빌드 시험: `client` 폴더에서 `npx vite build --outDir <임시 폴더> --emptyOutDir`. `client/dist` 는 건드리지 않는다.

## 5. 반영 (사장님 허락을 받은 뒤에만)
먼저 이렇게 여쭤본다: "인트라넷을 재시작해야 로또 페이지가 생겨요. 1분쯤 접속이 끊기는데 지금 해도 될까요?"
허락을 받으면 다음 순서로 한다.
1. DB 백업을 확인한다. `data/backups` 에 오늘 날짜 파일이 없으면 `server/data/inout.db` 를 복사해 둔다.
2. `npm run build` 로 `client/dist` 를 새로 만든다.
3. 이 PC에서 인트라넷을 띄우는 방식(작업 스케줄러, 바탕화면 아이콘, `start-server.bat` 등)을 확인하고 그 방식대로 다시 띄운다.
4. 확인한다: 시스템 관리자로 로그인 → "로또 최적화" → 30세트 실행 → 결과 표가 나오는지 → "당첨 확인" 버튼을 눌러 최신 회차 결과 표가 나오는지. 직원 계정에는 메뉴가 안 보이는지.
5. 새 브랜치에 커밋한다. 원격 저장소에 올릴지는 사장님께 물어본다.

## 되돌리기
`index.js` 의 `/api/lotto` 연결 두 줄, `App.jsx` 의 Route, `Nav.jsx` 링크를 지우고 다시 빌드·재시작하면 원래대로 돌아간다. `lotto_runs` 테이블은 남아 있어도 다른 기능에 영향이 없다.

## 당첨 확인 추가 (이미 붙인 PC)
로또 최적화 페이지가 이미 돌아가고 있는 PC에서, 결과마다 "당첨 확인" 버튼을 더하는 순서다. 위 "지킬 것"은 그대로 지킨다.

새로 생기는 것:
- 서버: `POST /api/lotto/runs/:id/check` (시스템 관리자 전용). 저장된 결과를 임시 파일로 써서 엔진의 `cli.py check <파일> --json` 을 돌린다. 본문 `{}` 는 최신 회차, `{ "draw": 1244 }` 는 그 회차, `{ "numbers": [6개], "bonus": n }` 은 직접 입력한 번호와 비교한다. 결과는 DB에 저장하지 않으므로 DB 구조는 바뀌지 않는다.
- 화면: 결과 위쪽 버튼 줄과 "지난 결과" 표의 각 줄에 "당첨 확인" 버튼. 누르면 최신 회차와 비교해 당첨번호, 최고 등수, 등수별 세트 수, 세트별 맞은 번호(색 공)와 등수를 보여 준다. 회차를 넣거나 번호를 직접 넣어 다시 확인할 수 있다.

1. 엔진 업데이트 (`D:\ClAUDE\lotto-opt`)
   - `git status` 로 고친 파일이 없는지 본다. 있으면 사장님께 먼저 알린다.
   - `git fetch origin` 후 `git checkout claude/project-thread-g77adz` 하고 `git pull`. 지금 쓰는 `claude/project-thread-hdlqmc`(v0.2)에 당첨 확인 한 커밋만 더한 브랜치라 계산 결과는 바뀌지 않는다. PR #1, #3 이 main에 합쳐졌으면 `git checkout main` 후 `git pull` 하면 된다.
   - 확인: `.venv\Scripts\python cli.py check <지난 결과 .json> --json` 이 JSON을 출력하면 된다. 결과 파일이 없으면 `cli.py run --config config/to_be.yaml --sets 30 --seed 11 --out <임시 폴더>` 로 하나 만든다.
2. 키트 받기: 키트 사본(예: `D:\ClAUDE\lotto-opt-kit`)에서 `git fetch origin` 후 `claude/project-thread-8wizxf` 브랜치로 바꾼다 (당첨 확인이 들어간 키트). 이 PR이 main에 합쳐졌으면 main을 쓴다.
3. 서버: 키트의 `server/lottoRouter.js` 를 인트라넷에 둔 `lottoRouter.js` 위에 덮어쓴다. 처음 붙일 때 인트라넷에 맞춰 이 파일을 고쳤다면(가져오는 이름, `userOf` 등) `git diff` 로 그 부분을 확인하고 다시 넣는다. `index.js` 의 연결 코드와 `.env` 는 그대로 둔다.
   - `pageAccessGate`, `auditLogGate` 가 새 경로(`POST /api/lotto/runs/:id/check`)를 막는지 본다. 당첨 확인은 아무것도 저장하지 않으므로 `/api/lotto` 의 다른 경로와 같은 방식으로 통과시킨다.
4. 화면: 키트의 `client/LottoOptimizer.jsx` 를 `client/src/pages/LottoOptimizer.jsx` 위에 덮어쓴 뒤, 처음 붙일 때 맞춘 부분(맨 위 `api` 가져오기, `/lotto/...` 경로, CSS)을 똑같이 다시 맞춘다. 덮어쓰기 전의 `git diff` 로 무엇을 고쳤는지 먼저 본다.
5. 시험 (4단계와 같은 방법): `node --test test/lottoRouter.test.js` 17개 통과, `LOTTO_REAL_OPT_DIR` 를 주면 진짜 엔진으로 실행과 당첨 확인까지 확인한다. 화면은 임시 폴더로 빌드해 본다.
6. 반영 (사장님 허락을 받은 뒤에만): 5단계 1~3과 같다. 먼저 "당첨 확인 버튼을 넣으려면 인트라넷을 재시작해야 해요. 1분쯤 접속이 끊기는데 지금 해도 될까요?" 하고 여쭤본다.
7. 확인: 시스템 관리자로 "로또 최적화" → 지난 결과의 "당첨 확인" → 최신 회차 결과가 나오는지, 회차 칸에 다른 회차를 넣어도 되는지. 직원 계정은 `/api/lotto/runs/1/check` 가 403 인지.
8. 같은 `lotto-optimizer` 브랜치에 커밋한다. 원격 저장소에 올릴지는 사장님께 물어본다.

화면에 "엔진에 당첨 확인 기능이 아직 없어요"가 나오면 1단계(엔진 브랜치)가 안 된 것이다.
되돌리기: 두 파일을 이전 커밋으로 되돌리고 다시 빌드·재시작한다. 엔진은 `git checkout claude/project-thread-hdlqmc` 로 돌아간다.
