# Report HTML Refactor

## 목적

- 현재 시각 톤과 구조를 유지하면서 PDF 인쇄 안정성을 확보합니다.
- 최종 산출물은 계속 self-contained 단일 HTML(`dist/*.html`)입니다.
- normal, real-assets, stress를 서로 다른 출력 프로파일로 관리합니다.

## 출력 프로파일

### `normal-compact`

- 기본 normal 빌드용 프로파일
- 목표: placeholder 기반 정상 데이터의 페이지 밀도 개선
- 주요 차이:
  - TOC / LOT / LOF budget 완화
  - finding page budget 완화
  - print 본문 글자 크기와 line-height 소폭 축소
  - 이미지 max-height 소폭 확대

### `normal-balanced`

- 실제 PNG/JPG 자산 검증용 프로파일
- 목표: 실제 스크린샷 가독성과 여백의 균형
- 주요 차이:
  - normal-compact보다 여백과 budget을 약간 보수적으로 유지
  - 실제 이미지의 읽기 쉬운 크기를 우선

### `stress-safe`

- stress 데이터셋 전용 프로파일
- 목표: 페이지 수보다 overflow/clipping 방지 우선
- 기존 safe 예산 유지

## 현재 산출물

```text
dist/
  report.html
  report.pdf
  report.validation.json
  report-real-assets.html
  report-real-assets.pdf
  report-real-assets.validation.json
  report-stress.html
  report-stress.pdf
  report-stress.validation.json
  report-table-sample.html
  report-table-sample.pdf
  report-table-sample.validation.json
  real-asset-samples/
    vertical-portal-capture.png
    wide-admin-dashboard.jpg
    hires-console-view.png
    dense-response-log.jpg
```

## 빌드

전체 빌드:

```bash
python3 build_report.py
```

개별 빌드:

```bash
python3 build_report.py --dataset default
python3 build_report.py --dataset real-assets
python3 build_report.py --dataset stress
```

프로파일 override:

```bash
python3 build_report.py --dataset default --profile normal-balanced
python3 build_report.py --dataset stress --profile stress-safe
```

WSL/Linux 메모:

- WSL에서는 `/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`를 자동 탐색하여 PDF를 생성합니다.
- `real-assets`는 Pillow가 없어도 `dist/real-asset-samples/`의 기존 PNG/JPG를 재사용해 빌드할 수 있습니다.

## 이번 라운드 핵심 변경점

### 1. normal 페이지 밀도 조정

- 기본 normal 출력 프로파일을 `normal-compact`로 연결했습니다.
- TOC와 표/그림 차례가 정상 데이터에서는 1페이지에 수용되도록 budget을 조정했습니다.
- finding page budget을 소폭 상향하여 정상 데이터 기준 두 번째 취약점의 불필요한 continuation을 제거했습니다.
- 결과적으로 기본 normal PDF는 기존 22페이지에서 19페이지로 감소했습니다.
- 추가 미세 조정 실험에서도 19페이지 아래로는 내려가지 않았습니다.
  - section span probe 기준 실제 2페이지를 쓰는 핵심 구간:
    - `chapter-2-continuation`
    - `chapter-4-section`
    - `finding-vul-002-section-1`
  - 즉 현재 19페이지는 부록보다 2장 진단 개요와 상세 결과 본문 길이에 의해 고정되는 상태입니다.

### 2. 실제 PNG/JPG 검증 경로 추가

- `real-assets` 데이터셋을 추가했습니다.
- `dist/real-asset-samples/`에 실제 PNG/JPG 샘플 자산을 생성하고, 이를 `dist/report-real-assets.html`에 data URI로 내장합니다.
- 포함 케이스:
  - 세로로 긴 캡처
  - 가로로 긴 캡처
  - 해상도가 큰 캡처
  - 작은 글자가 많은 캡처

### 3. 다중 페이지 표 검증 강화

- Chromium/Edge의 `thead` 반복 규칙만 신뢰하지 않고, build 단계에서 명시적 continuation table을 생성하는 샘플을 추가했습니다.
- 결과물:
  - `dist/report-table-sample.html`
  - `dist/report-table-sample.pdf`
- 샘플은 `[표 5] 웹 취약점 진단 대상` 구조를 기준으로 28행을 넣어 continuation table을 강제로 생성합니다.

### 4. TOC / page token 검증 분리

- page token은 여전히 build 단계에서 치환합니다.
- 검증 결과는 `page_map`으로 분리해 기록합니다.
- `layout probe`는 브라우저별 제약이 있어 보조 경로로만 유지하고, 실제 보정은 `section span probe`를 우선 사용합니다.
- `section span probe`는 `print-page-start` section을 개별 PDF로 재출력해 실제 page span을 측정합니다.
  - normal / real-assets / table-sample: 적용
  - stress: section 수가 많아 `미검증`
- 분류 기준:
  - `확정`: section span probe로 보정된 section 시작점, section 상단 근처의 heading / vuln-block
  - `추정`: table caption, figure caption, 긴 섹션 후반부 heading
  - `미검증`: stress의 후반 page map, PDF 텍스트 추출 기반의 직접 대조

## 자동 검증 항목

`*.validation.json`에는 아래 항목이 기록됩니다.

- `page_tokens_remaining`
- `fixed_height_overflow_pairs`
- self-contained 여부
- continuation section 수
- `page_map` 요약
- `section_span_probe` 요약
- `pagination_summary`
- raster 이미지 검증 결과
- Edge headless PDF 생성 결과와 page count

## 실제 이미지 가독성 기준

`report-real-assets.validation.json`의 `image_validation`은 아래 기준으로 계산합니다.

- 대상: PNG/JPG만 집계
- 계산 방식:
  - 이미지 원본 픽셀 크기
  - print CSS의 `max-height`
  - 컨테이너 최대 폭
  - 위 값을 이용한 유효 PPI 추정
- 기준:
  - 일반 캡처: 100 PPI 이상
  - high-resolution 캡처: 120 PPI 이상
  - dense-text 캡처: 140 PPI 이상

이 값은 어디까지나 추정 기반 자동 점검입니다. 최종 판정은 PDF 육안 검수가 필요합니다.

## 수동 검수 절차

### A. 기본 normal (`dist/report.pdf`)

1. 표지 1페이지 하단 안내문 위치가 이전과 동일한지 확인
2. TOC / 표 차례 / 그림 차례의 숫자가 실제 PDF 페이지와 일치하는지 확인
3. 1장, 2장, 3장의 continuation이 과도하지 않고 공백이 비정상적으로 크지 않은지 확인
4. 상세 결과의 finding continuation이 불필요하게 생기지 않았는지 확인
5. `chapter-2-continuation`이 실제 2페이지를 쓰는 구조이므로 `[표 11]`, `[표 12]` page number가 PDF와 일치하는지 재확인
6. `VUL-001`, `VUL-002` 시작 page가 각각 11, 14로 보정되었는지 확인

### B. 실제 이미지 (`dist/report-real-assets.pdf`)

1. 모든 PNG/JPG가 셀 밖으로 잘리지 않는지 확인
2. 세로형 캡처가 과도하게 축소되어 읽기 어려워지지 않는지 확인
3. dense-text 캡처의 작은 글자가 실제 육안으로 읽을 수 있는지 확인
4. appendix 이미지와 figure caption이 시각적으로 분리되지 않는지 확인
5. `appendix-c-*`가 3개 continuation section으로 분리되어도 caption 흐름이 자연스러운지 확인

### C. 표 헤더 (`dist/report-table-sample.pdf`)

1. 각 continuation page에 표 헤더가 다시 출력되는지 확인
2. caption이 `[표 5] ... (계속)` 형식으로 이어지는지 확인
3. caption과 표 본문 chunk가 분리되지 않는지 확인
4. 페이지 간 row clipping이 없는지 확인

## 검증 상태 분류

- `확정 검증`
  - self-contained
  - page token 미치환 여부
  - fixed height + overflow hidden 조합 탐지
  - explicit continuation section 생성 여부
  - Edge headless PDF page count
  - normal / real-assets / table-sample의 section span probe 총 페이지 수 대조
- `추정 기반 검증`
  - 실제 PNG/JPG 가독성 PPI 계산
  - section 내부 후반부 caption / figure / heading의 page map
- `미검증`
  - PDF 텍스트 추출 기반 TOC 숫자 직접 대조
  - 기관 실자산 교체 후 최종 가독성
  - 브라우저/프린터 드라이버 조합별 렌더링 차이
  - stress의 section span probe

## 현재 수동 확인 필요 항목

1. 실제 기관 PNG/JPG 교체 후도 현재 real-assets 샘플과 유사한 가독성이 유지되는지
2. 긴 표/이미지 caption의 실제 PDF page number가 추정과 어긋나지 않는지
3. 브라우저 버전 차이에 따른 table header 렌더링 차이
