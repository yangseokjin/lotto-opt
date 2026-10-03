# lotto-opt v0.1

로또 6/45 포트폴리오 구조 최적화 엔진 (OR-Tools CP-SAT). 모든 조합의 당첨 확률은 같으며, 이 엔진은 커버리지·분포·중복 같은 포트폴리오 구조만 최적화합니다.

## 실행
```
python3 -m pip install ortools pyyaml
python3 cli.py run --config config/to_be.yaml            # 개선안
python3 cli.py run --config config/as_is.yaml            # 원본 기획서
python3 cli.py run --config config/to_be.yaml --seed 7 --sets 30 --time-scale 2
python3 cli.py compare --config config/as_is.yaml --config config/to_be.yaml   # 프리셋 비교표
python3 cli.py run --config config/to_be.yaml --set 'targets.odd_even={"4:2": 0.36, "3:3": 0.33, "2:4": 0.24, other: 0.07}'
```
`--set 점.경로=값` 으로 설정 파일을 고치지 않고 아무 항목이나 바꿔 실험할 수 있습니다.
결과는 `out/<프리셋>_<세트수>sets_seed<시드>.md/.json` 에 저장됩니다. 종료 코드 1은 독립 검증에서 위반이 나왔다는 뜻입니다.

## 구조
| 파일 | 역할 |
|---|---|
| `lotto_opt/data.py` | 동행복권 공식 API → 실패 시 공개 미러, `data/draws.json` 캐시, 회차 누락·번호 검증 |
| `lotto_opt/stats.py` | 가중 빈도, Hot/Warm/Cold, 최장 미출현, 목표 분포 자동 산출(`auto`) |
| `lotto_opt/constraints/set_level.py` | 세트 제약: 그룹, 이월수, 합계, 연속수, AC, 구간, 홀짝/저고 개수 |
| `lotto_opt/constraints/global_level.py` | 전역 제약: 출현 횟수, 커버리지, 평균회귀 강제, 연속수 0쌍 비율, 분포 밴드, 교집합 |
| `lotto_opt/objective.py` | 사전식 단계: 분포 오차 → 교집합 → 출현 편차 |
| `lotto_opt/solver.py` | 모델 조립, 단계별 풀이, `relax` 목록 자동 완화 |
| `lotto_opt/validate.py` | 솔버와 독립된 순수 파이썬 재검사 |
| `lotto_opt/report.py` | 지정 출력 형식(.md)과 JSON |

## 설정
제약·목표·완화·목적 단계는 모두 `config/*.yaml` 에 있습니다. `targets` 값이 `auto` 이면 최근 `data.window` 회차에서 산출하고, 숫자 분포를 쓰면 그 값을 목표로 씁니다.

## 홀짝 목표
기본은 최근 100회 실측값(`targets.odd_even: auto`)입니다. 기획서 값(4:2 36%, 3:3 33%, 2:4 24%, 기타 7%)을 쓰려면 `config/to_be.yaml` 의 주석 줄을 쓰거나 위 `--set` 예시처럼 실행하세요.

## 메모
- 세트 정렬식 대칭 제거가 첫 해 탐색을 크게 늦춰서(켜면 약 140초, 끄면 12초) 기본으로 꺼 두었습니다(`rules.symmetry_breaking`).
- `group_mix: auto` 는 현재 그룹을 같은 100회에 대입한 표본 내 추정치입니다.
