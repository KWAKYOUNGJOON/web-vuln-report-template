# Report HTML Refactor

## 개요

- 원본 루트 `report.html`은 보존하고, 수정용 소스는 `report-src/`로 분리했습니다.
- 배포/인쇄용 산출물은 `python build_report.py` 실행으로 `dist/report.html`에 다시 단일 HTML로 생성됩니다.
- 런타임 `fetch()`나 외부 partial import는 사용하지 않습니다. 최종 결과물은 self-contained 단일 HTML입니다.

## 디렉터리 구조

```text
report-src/
  partials/
    00-audit-panel.html
    01-cover.html
    02-toc.html
    03-figures-tables.html
    04-overview.html
    05-diagnostic-overview.html
    06-summary.html
    07-details-vul-001.html
    08-details-vul-002.html
    09-countermeasures.html
    10-appendix-a.html
    11-appendix-b.html
    12-appendix-c.html
  css/
    base.css
    components.css
    print.css
  js/
    placeholders.js
    page-tokens.js
    qa-panel.js
    init.js
build_report.py
dist/
  report.html
```

## 분리 기준

- `partials/`: 문서 의미 단위로 분리했습니다. 표지, 목차, 각 장, 상세 결과, 부록을 독립 수정 가능하게 유지합니다.
- `css/base.css`: 리셋, 본문 레이아웃, 제목/문단/테이블 기본 규칙, placeholder 기본 상태 등 공통 기초 규칙입니다.
- `css/components.css`: 제출 전 점검 패널, 배지, TOC, 취약점 상세 카드, 증빙 패널, 프로세스 도식 등 화면/공통 컴포넌트 규칙입니다.
- `css/print.css`: 기존 `@media print`와 `@page` 규칙을 그대로 분리했습니다. 페이지 시작, 상세 결과 페이지 나눔, 체크리스트 압축, appendix 보정 규칙이 여기에 있습니다.
- `js/placeholders.js`: token/placeholder 판정용 정규식과 기본 텍스트 정규화 로직입니다.
- `js/page-tokens.js`: `data-field="page.*"` 또는 상위 `data-toc-key` 기반 page token 키 추출 로직입니다.
- `js/qa-panel.js`: unresolved 항목 수집, class 부여, 제출 전 점검 패널 요약/목록 렌더링 로직입니다.
- `js/init.js`: 기존과 동일하게 문서 하단에서 즉시 실행되도록 IIFE를 닫습니다.

## 빌드

```bash
python build_report.py
```

생성 결과:

- `dist/report.html`

빌드 스크립트 동작:

1. `partials/*.html`을 파일명 순서대로 결합합니다.
2. `css/*.css`를 지정된 순서대로 `<style>`에 inline 삽입합니다.
3. `js/*.js`를 지정된 순서대로 `<script>`에 inline 삽입합니다.
4. 가능하면 루트 원본 `report.html`과 핵심 구조 카운트/시퀀스를 자동 비교합니다.

## 수정 원칙

- 실제 수정은 `report-src/`에서만 진행합니다.
- `dist/report.html`은 빌드 산출물이므로 직접 수정하지 않습니다.
- 클래스명, `id`, `data-field`, `data-repeat`, `data-toc-key`는 출력 동일성과 스크립트 동작에 직접 연결되어 있으므로 임의 변경을 피합니다.
- 인쇄 레이아웃 관련 규칙은 먼저 `css/print.css`에서 검토합니다.

## 자동 검증 항목

`python build_report.py` 실행 시 다음 항목을 자동 점검합니다.

- 최종 HTML 내 단일 `<style>`/`<script>` 내장 여부
- `main.report-document` 및 `submission-audit-panel` 존재 여부
- `@media print`, `@page` 유지 여부
- 루트 원본 `report.html` 대비 다음 카운트 일치 여부
- `<section>` 개수
- `data-field` 개수
- `data-repeat` 개수
- `placeholder`, `requires-input`, `toc-page` class 개수
- `{{page:*}}` 토큰 개수
- section id / section `data-toc-key` / heading id / heading `data-toc-key` 순서 일치 여부

## 수동 확인 포인트

자동 검증만으로는 브라우저 실제 페이지네이션까지 완전 보장할 수 없습니다. 최종 제출 전 아래 항목을 수동 확인하십시오.

1. 브라우저 화면에서 표지, 목차, 1~5장, 부록 A~C의 간격과 박스 스타일이 기존과 동일한지 확인합니다.
2. 인쇄 미리보기에서 `print-page-start`가 걸린 섹션이 기존과 같은 페이지 시작 위치를 유지하는지 확인합니다.
3. 상세 결과(`4장`)에서 각 `vuln-detail` 블록이 기존처럼 개별 페이지 흐름을 유지하는지 확인합니다.
4. `2장 점검 체크리스트`와 `부록 A 체크리스트`의 폰트/셀 패딩이 과도하게 늘어나지 않았는지 확인합니다.
5. 제출 전 점검 패널에서 unresolved placeholder / page token 집계가 정상인지 확인합니다.
6. 목차와 표/그림 차례의 `{{page:*}}` 토큰 표기가 기존과 같은 naming rule을 따르는지 확인합니다.

## 루트 파일 교체 절차

수동 검증이 끝난 뒤에만 루트 파일 교체를 진행하십시오.

1. `python build_report.py`
2. `dist/report.html`을 브라우저와 인쇄 미리보기에서 확인
3. 필요 시 `report-final.pdf`와 페이지 흐름 비교
4. 검증 완료 후에만 루트 `report.html` 교체 여부를 결정

## 현재 한계

- 브라우저 엔진별 인쇄 pagination 차이는 코드 자동 비교만으로 완전 검증할 수 없습니다.
- PDF 기준 시각 차이는 브라우저 headless 렌더링 또는 수동 인쇄 미리보기 확인이 필요합니다.
- 따라서 시각 동일성은 일부 자동 검증 + 수동 확인 절차를 함께 사용해야 합니다.
