# 웹 취약점 진단 결과 보고서 HTML/PDF 템플릿

## 프로젝트 소개

이 저장소는 웹 취약점 진단 결과 보고서를 HTML 기반으로 작성하고, 최종 제출용 PDF까지 함께 생성하기 위한 템플릿입니다.  
실제 수정은 [`report-src/`](/mnt/d/취약점-보고서/report-src)에서 수행하고, [`build_report.py`](/mnt/d/취약점-보고서/build_report.py)를 실행해 self-contained 단일 HTML과 print-safe PDF를 생성합니다. PDF는 브라우저 `Ctrl+P`가 아니라 headless export로 생성하며, 브라우저 인쇄 메타 머리글/바닥글이 포함되지 않도록 빌드 단계에서 강제합니다.

공개 저장소 기준 기본 제출본은 [`dist/report.html`](/mnt/d/취약점-보고서/dist/report.html)과 [`dist/report.pdf`](/mnt/d/취약점-보고서/dist/report.pdf)입니다. 이 README는 리팩토링 메모가 아니라, 저장소 방문자가 프로젝트 목적, 빌드 방법, 제출 기준 파일을 바로 이해할 수 있도록 현재 사용 기준 중심으로 정리한 문서입니다.

## 주요 특징

- 단일 HTML 결과물 생성: CSS와 JavaScript가 인라인된 self-contained HTML을 생성합니다.
- PDF 출력 최적화: A4 기준 인쇄 레이아웃과 page-break 제어를 반영한 print-safe 템플릿입니다.
- 긴 표, 긴 증빙, 취약점 증가 대응: 본문과 부록이 길어져도 continuation page 구조로 분리할 수 있습니다.
- page token 자동 치환: `{{page:*}}` 토큰을 빌드 단계에서 페이지 맵으로 치환합니다.
- continuation page 자동 생성: 긴 장, 취약점 섹션, 표 샘플을 여러 페이지로 자동 분할합니다.
- 실자산 검증 가능: 실제 PNG/JPG 캡처와 기관 로고를 대입해 가독성을 점검하는 `real-assets` 빌드 경로를 지원합니다.
- 표 헤더 반복 검증 가능: multi-page table continuation과 `(계속)` 캡션 흐름을 별도 샘플로 확인할 수 있습니다.
- 스트레스 테스트 가능: 분량이 큰 데이터셋으로 overflow, clipping, page-break 회귀를 점검할 수 있습니다.

## 저장소 구조

- [`.vscode/`](/mnt/d/취약점-보고서/.vscode): HTML, CSS, JS, JSON, Python 작업용 에디터 설정입니다.
- [`report-src/`](/mnt/d/취약점-보고서/report-src): 보고서 원본입니다. partial, template, data, CSS, JS를 여기서 수정합니다.
- [`build_report.py`](/mnt/d/취약점-보고서/build_report.py): HTML/PDF 생성과 QA용 보조 산출물 생성을 담당하는 단일 빌드 스크립트입니다.
- [`dist/report.html`](/mnt/d/취약점-보고서/dist/report.html): 현재 공개 저장소에 포함된 self-contained HTML 제출본입니다.
- [`dist/report.pdf`](/mnt/d/취약점-보고서/dist/report.pdf): 현재 공개 저장소에 포함된 PDF 제출본입니다.
- `dist/*.validation.json`, `dist/report-real-assets.*`, `dist/report-table-sample.*`, `dist/report-stress.*`: 필요 시 로컬에서 재생성하는 보조 검증 산출물입니다. 현재 공개 저장소에는 포함하지 않으며, `.gitignore` 대상으로 관리합니다.

## 빠른 시작

1. 문안, 표, 취약점 데이터, 부록 증빙 구조를 [`report-src/`](/mnt/d/취약점-보고서/report-src)에서 수정합니다.
2. 빌드를 실행합니다.

```bash
python3 build_report.py --dataset default
```

3. 제출 기준 결과물을 [`dist/report.html`](/mnt/d/취약점-보고서/dist/report.html)과 [`dist/report.pdf`](/mnt/d/취약점-보고서/dist/report.pdf)에서 확인합니다.
4. 실제 기관 로고, 실제 고객 증빙 PNG/JPG, 실제 진단 결과로 교체한 경우 PDF를 다시 육안 검수합니다.

## 빌드 방법

기본 빌드:

```bash
python3 build_report.py
```

기본 제출본만 다시 생성할 때:

```bash
python3 build_report.py --dataset default
```

보조 검증용 출력이 필요할 때:

```bash
python3 build_report.py --dataset real-assets
python3 build_report.py --dataset stress
```

- 수정은 [`report-src/`](/mnt/d/취약점-보고서/report-src)에서 진행합니다.
- 공식 PDF 생성 명령은 `python3 build_report.py --dataset default`입니다.
- 브라우저 `Ctrl+P` 경로는 브라우저가 시간, 문서 제목, 파일 경로, 쪽수 머리글/바닥글을 붙일 수 있으므로 공식 산출 방식으로 사용하지 않습니다.
- 빌드 스크립트는 현재 환경에서 Microsoft Edge headless를 자동 탐지해 PDF를 생성하며, 브라우저 플래그로 인쇄 머리글/바닥글을 비활성화합니다.
- dataset JSON 값은 모두 비신뢰 입력으로 취급하며, HTML 렌더링은 escape-by-default 정책으로 처리합니다.
- 제한적 HTML이 꼭 필요한 경우에도 dataset 문자열을 그대로 넣지 않고, 빌드 스크립트 내부에서 검증 후 생성한 trusted fragment만 사용해야 합니다.
- URL 계열 값은 상대경로, `http(s)://`, 제한된 raster `data:image/*`(`png`, `jpeg`, `gif`, `webp`)만 허용하며 `javascript:`, `vbscript:`, `file:`, `data:image/svg+xml` 등은 차단합니다.
- 이미지 `src`에 사용하는 상대경로는 현재 디렉터리 기준의 자산 경로만 허용합니다. 루트형 경로, 백슬래시 경로, `..` 경로 순회는 로컬 파일 포함을 막기 위해 차단합니다.
- PDF 생성 시 `--allow-file-access-from-files`는 기본 비활성화입니다. 정말 필요한 개발용 점검만 `python3 build_report.py --allow-local-file-access`로 명시적으로 opt-in 하십시오.
- 최종 제출 기준은 [`dist/report.html`](/mnt/d/취약점-보고서/dist/report.html), [`dist/report.pdf`](/mnt/d/취약점-보고서/dist/report.pdf)입니다.
- 실제 자산으로 교체한 뒤에는 표지 로고, 증빙 이미지 잘림, 긴 표 분할, TOC 페이지 번호를 다시 확인해야 합니다.

## 최종 산출물

제출 기준 파일:

- [`dist/report.html`](/mnt/d/취약점-보고서/dist/report.html): 배포와 보관이 쉬운 self-contained HTML 제출본입니다.
- [`dist/report.pdf`](/mnt/d/취약점-보고서/dist/report.pdf): 제출 직전 확인용 PDF 제출본입니다.

보조 검증 산출물:

- `dist/report-real-assets.*`: 실제 PNG/JPG 샘플과 로고를 반영한 가독성 검증용 출력입니다.
- `dist/report-table-sample.*`: multi-page table continuation, 헤더 반복, `(계속)` 캡션 검증용 출력입니다.
- `dist/report-stress.*`: 대량 데이터 기준 overflow 및 clipping 회귀 점검용 출력입니다.
- `dist/*.validation.json`: page token, page map, overflow 규칙, PDF 페이지 수 등 자동 검증 결과 요약입니다.

위 보조 검증 산출물은 필요 시 로컬에서 생성하는 QA 결과이며, 제출본 자체는 아닙니다. 현재 공개 저장소에 기본으로 남기는 파일은 [`dist/report.html`](/mnt/d/취약점-보고서/dist/report.html)과 [`dist/report.pdf`](/mnt/d/취약점-보고서/dist/report.pdf)입니다.

## 검증 항목

- 현재 공개 저장소의 [`dist/report.html`](/mnt/d/취약점-보고서/dist/report.html)은 self-contained 상태입니다.
  현재 확인 기준: linked stylesheet/script 없음, `@import` 없음, 인라인 style/script 사용.
- 현재 공개 저장소의 [`dist/report.html`](/mnt/d/취약점-보고서/dist/report.html)은 TOC용 미치환 page token이 0건입니다.
- 현재 빌드 소스 기준 fixed height와 `overflow: hidden`의 문제 조합은 탐지되지 않았습니다.
- 현재 공개 저장소의 [`dist/report.pdf`](/mnt/d/취약점-보고서/dist/report.pdf)는 19페이지입니다.
- 실제 PNG/JPG 샘플 검증은 `real-assets` 출력으로 수행합니다. 실제 기관 로고와 실제 증빙 이미지로 교체한 뒤 다시 빌드해 잘림과 가독성을 점검해야 합니다.
- multi-page table continuation 검증은 `table-sample` 출력으로 수행합니다. continuation page마다 표 헤더와 `(계속)` 캡션이 자연스럽게 이어지는지 확인해야 합니다.
- `stress` 출력은 긴 표, 긴 증빙, 취약점 증가 상황에서 clipping과 overflow 회귀를 확인하는 품질 보증용 결과입니다. 제출본이 아닙니다.

남은 수동 검수 포인트:

- placeholder와 예시 문구가 실제 기관명, 수행기관명, 일정, 취약점명, 대응 계획으로 모두 교체됐는지 확인
- TOC, 표/그림 차례, 본문 시작 페이지가 PDF와 육안상 일치하는지 확인
- 실제 로고와 실제 고객 증빙 이미지가 본문 프레임 밖으로 잘리지 않는지 확인
- 긴 표, 긴 증빙, 부록 continuation이 과도한 공백 없이 자연스럽게 이어지는지 확인
- 최종 제출 전에 대상 브라우저 또는 사내 PDF 변환기에서 한 번 더 출력 결과를 확인

## 운영 시 주의사항

- 실제 기관 로고와 실제 고객 증빙 이미지로 교체한 뒤에는 반드시 재빌드해야 합니다.
- 최종 제출 전에는 [`dist/report.pdf`](/mnt/d/취약점-보고서/dist/report.pdf)를 기준으로 육안 검수를 권장합니다.
- 제출용 PDF는 브라우저 `Ctrl+P` 대신 `python3 build_report.py --dataset default` 명령으로 다시 생성해야 합니다.
- 브라우저 버전이나 사내 PDF 변환기 차이로 줄바꿈, page-break, 표 헤더 반복 결과가 달라질 수 있습니다.
- `stress` 결과는 품질 보증용 점검 자료이며 제출본이 아닙니다.
- 템플릿에 남아 있는 placeholder, 예시 취약점, 예시 설명은 실제 결과로 교체한 뒤 외부 전달해야 합니다.

## 기타 안내

- 현재 저장소에는 별도 `LICENSE` 파일이 포함돼 있지 않습니다. 외부 배포나 재사용 전에는 조직 정책에 맞게 사용 범위를 확인하는 것을 권장합니다.
- 이 템플릿을 보안 보고서 예시로 사용할 때는 실제 고객명, 실제 URL, 실제 계정정보, 실제 로그, 실제 증빙 이미지를 그대로 커밋하지 않도록 주의하십시오.
