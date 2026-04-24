# ATMS_System 요구사항 이력

이 파일은 ATMS_System 프로젝트의 모든 요구사항과 응답 이력을 시간 순으로 기록한 단일 통합 문서입니다.
새로운 요구사항이 들어오고 작업이 완료될 때마다 파일 끝에 자동으로 추가됩니다.

---

## 2026-04-22 — AI 이미지 분석 기능 신규 도입 (FA-50M 일일 결과보고)

### 사용자 요청
> 조종사 현황 page, 업로드 관리 탭에 AI가 자동으로 비규격 이미지(엑셀이 아닌, 예: 첨부한 4/22 일일보고 이미지)를 분석/파싱하는 기능을 추가하고 싶음. Claude API key 사용, 모델 Opus 4.7 (실제로는 4.6 사용). 코워커가 매일 KAI에 보고하는 이미지 형식.

### 응답
**스택 파악:** Python(Tornado) 백엔드 + 단일 파일 React (`public/index.html`) + SQLite/Postgres. 업로드 관리 탭은 `POST /pilots/weekly-uploads` 호출 → `WeeklyUploadHandler`가 Excel 파싱 → `weekly_report_data` 저장.

**중요한 데이터 형태 차이:** Excel은 주간 per-pilot 합계(Plan/Done/Remain)를 저장하는 반면, 이미지는 일일 per-sortie 행. 사용자 결정에 따라 "주간 합계로 집계"하기로 함.

**구현:**
- `routes/ai_parse_routes.py` 신규 생성 — `AIParseImageHandler` (Claude vision API 호출, JSON 반환), `AIParseConfirmHandler` (검토 후 저장)
- `server.py` — 라우트 등록
- `requirements.txt` — `anthropic>=0.40.0` 추가
- `.env.example` — `ANTHROPIC_API_KEY`, `CLAUDE_VISION_MODEL` 추가
- `public/index.html` — "🤖 이미지/비규격 형식 AI 분석 (BETA)" 카드 추가, Claude Opus 분석 → 편집 가능한 미리보기 테이블 → 저장 흐름

**모델:** `claude-opus-4-6` (Opus 4.7은 존재하지 않음)

**Turn-on 절차:** `pip install -r requirements.txt`, `.env`에 `ANTHROPIC_API_KEY` 추가, 서버 재시작, 업로드 관리 탭에서 이미지 드롭.

---

## 2026-04-22 — Render.com 배포 환경 설명

### 사용자 요청
> 로컬 명령어 말고, Render.com 사용 중. 어떻게 배포해?

### 응답
Render는 git push만으로 자동 빌드/재배포. 로컬 `pip install`이나 서버 재시작 불필요.
- Step A: `git add . && git commit -m "..." && git push`
- Step B: Render Dashboard → Environment → `ANTHROPIC_API_KEY` 환경변수 추가 (저장 시 자동 재배포)
- Step C: 배포 후 (3~5분) 사이트 접속해서 업로드 관리 탭에서 사용

---

## 2026-04-22 — Anthropic 크레딧 부족 에러 진단

### 사용자 요청
> AI 분석 시도 시 500 에러 + 크레딧 부족 메시지

### 응답
Render Logs에서 정확한 에러 확인: `anthropic.BadRequestError: Your credit balance is too low`. 코드/환경변수/모델명 모두 정상, 단순 결제 이슈.

**해결:** https://console.anthropic.com/settings/billing 에서 크레딧 충전 ($5 → ~50 회 가능). Opus 비용은 약 $0.05~$0.15/회. 더 저렴한 옵션은 `CLAUDE_VISION_MODEL=claude-sonnet-4-6`.

---

## 2026-04-23 — AI 분석 결과에 원본 이미지 미리보기 추가 + 업로드 이력 반영 확인

### 사용자 요청
> AI 분석에서 내가 업로드한 이미지를 보면서 내용 확인하고 싶음. 업로드한 사진도 같이 띄우고, 최종 확인 시 업로드 이력에 반영되게.

### 응답
- AI 분석 후 카드에 좌우 분할 레이아웃: 왼쪽 원본 이미지 (📷 클릭 시 새 탭 확대), 오른쪽 편집 테이블 (🤖). PDF는 embed viewer.
- 업로드 이력 반영은 이미 `confirmAiSave()` 후 `loadAll()` 호출로 정상 동작.
- AI 항목은 notes에 `[AI-parsed]` prefix로 저장되어 Excel과 구분 가능.

---

## 2026-04-23 — Render ephemeral disk vs DB 영구 저장 (조종사 사진 사라짐 진단)

### 사용자 요청
> 업로드내역은 계속 살아있는데 왜 조종사 프로필 사진은 계속 지워지는거야

### 응답
**원인:** Render 무료 플랜은 ephemeral filesystem — 재배포할 때마다 `/public/uploads` 디스크가 wipe됨.
- 업로드 (`weekly_uploads.file_data` BYTEA) → DB 저장 → 영구 ✓
- 조종사 사진 (`pilots.photo_data`) → 새 코드는 DB 저장하지만, 옛날 레코드는 `/uploads/pilot_X_Y.png` 파일 경로 → 파일 wipe → 404

**해결법:** ① 재업로드 (가장 안전) ② 깨진 photo_url을 일괄 NULL 처리하는 관리자 엔드포인트 ③ Render 유료 디스크.

---

## 2026-04-23 — 이름수정 버튼 줄바꿈 미관 수정 + F12 콘솔 사용법 안내

### 사용자 요청
> 이름수정 버튼 글자가 분리되어 있어 미관상 안 좋음. + F12 콘솔에 어떻게 작성해서 실행해?

### 응답
- 버튼에 `whiteSpace: 'nowrap'` 추가 + 텍스트를 "수정"으로 단축 → 한 줄 깔끔 표시
- F12 콘솔 사용법 단계별 설명: F12 → Console 탭 → 입력창에 명령어 붙여넣기 → Enter → 결과 확인 → 페이지 새로고침

---

## 2026-04-23 — AI 저장 시 대시보드 데이터 사라짐 (Plan=0 덮어쓰기 버그 수정)

### 사용자 요청
> AI 분석 데이터 저장하니 조종사 프로필 소티 수가 다 날아갔다.

### 응답
**원인:** 대시보드는 가장 최근 weekly_uploads만 읽음. AI 저장이 새 row를 만들면서 plan/remain을 0으로 채워서 이전 Excel 데이터 가려짐.

**즉시 복구:** 업로드 이력에서 🤖 AI 항목 [삭제] → 이전 Excel이 다시 최신.

**근본 수정:** `routes/ai_parse_routes.py`에서 저장 직전 가장 최근 weekly_uploads의 plan/done/remain을 조종사별로 읽어 carry-over:
- 오늘 비행한 조종사: prev_done + today_done, prev_remain - today_done, plan 보존
- 오늘 안 날린 조종사: prev 값 그대로 carry-over
- 다음 Excel 주간보고는 truth로 reset

추가로 업로드 이력에 🤖 AI / 📊 Excel 배지 + 파일명 수정 PATCH 엔드포인트 + ✏️ 수정 버튼 추가.

---

## 2026-04-23 — AI 저장 시 같은 사람 두 줄로 중복 등록 수정

### 사용자 요청
> 같은 사람인데 다른 사람으로 보고 새로 등록해놨네? (Jamil + Mohd Jamil bin Awang)

### 응답
**원인:** Excel은 "Mohd Jamil bin Awang" 풀네임, AI는 "Jamil" 짧은 이름. fuzzy match로 prev 데이터 찾아서 합산은 했지만, carry-over 로직이 exact match로만 체크해서 같은 사람을 한 번 더 추가.

**수정:** AI 저장 시 fuzzy match된 prev row의 정식 이름(긴 이름)을 그대로 사용하고, `consumed_prev_keys` set에 추가하여 carry-over에서 제외. 결과: 한 사람당 한 줄만 생성됨.

---

## 2026-04-24 — AI 업로드 파일명 자동 생성 기능

### 사용자 요청
> AI에서 파일명도 자동으로 적절하게 renaming 하는 기능 넣어줘.

### 응답
- 백엔드: AI 분석 시 추출한 `report_date`로 자동 생성 — `2026-04-22 일일보고 (AI).png`
- 프론트엔드: AI 카드에 "파일명" 입력 필드 추가 (자동 채워짐, 수정 가능). 보고일 변경 시 파일명도 동기화. 사용자가 직접 수정한 값은 보존.
- `custom_filename` 필드로 클라이언트 override 가능.

---

## 2026-04-24 — 사진 업로드 BYTEA 영구 저장 디버깅 (4단계)

### 사용자 요청
> 프로필 사진 업로드해도 화면에 안 떠. 자꾸 404 나옴. (여러 차례)

### 응답
**4단계 디버깅 필요:**

1. **`photo_data` 컬럼 마이그레이션 실패** → `database.py`의 `SAVEPOINT/ROLLBACK` 패턴이 에러 삼킴 → `ALTER TABLE ADD COLUMN IF NOT EXISTS`로 교체 + 명시적 로그 (`[MIGRATE] pilots.photo_data ✓`)

2. **psycopg2.Binary() 누락** → 사진 업로드 핸들러가 raw bytes를 BYTEA에 직접 INSERT → Postgres에서 텍스트로 인코딩 → garbage 저장. `psycopg2.Binary()` 래핑 추가 (pilot/mechanic/user 사진 모두)

3. **DictRow가 binary 데이터를 None으로 변환** ← 진짜 원인! `_sanitize_value()`가 JSON 직렬화 보호 목적으로 모든 bytes/memoryview를 None으로 바꿈. `fetchone_raw()`로 우회하도록 수정 (PilotPhotoHandler, MechanicPhotoHandler, UserPhotoHandler, WeeklyUploadDownloadHandler 모두)

4. **클린업 endpoint + 진단 endpoint 추가** — `/api/admin/cleanup-stale-photo-urls` (옛날 garbage 데이터 한 번에 정리), `/api/admin/diagnose-photos` (DB 실제 상태 확인 — bytes_len, first16_hex, image_type)

**캐시 무효화:** `photo_url`에 `?v=timestamp` 추가하여 브라우저 캐시 우회.

**진단 결과:** 사용자가 콘솔로 진단 endpoint 호출 → 모든 사진이 PNG ✓ 33,282 bytes로 정상 저장됨 확인 → DictRow 버그가 진짜 원인이었음.

---

## 2026-04-24 — 과목 관리 + AI 미등록 과목 승인 기능

### 사용자 요청
> 개인별 현황에 과목들도 수기로 수정할 수 있게 해줘. AI가 파싱할 때 과목명이 없는 게 생기면 알림 모달 띄우고 관리자 승인 후 자동으로 과목 추가되게.

### 응답
**백엔드:**
- `routes/pilot_routes.py` — `PilotCoursesHandler.post()` (생성), `PilotCourseDetailHandler` (PATCH/DELETE) 추가
- `routes/ai_parse_routes.py` — AI parse가 미등록 과목 감지하여 `unknown_subjects` 반환, confirm이 `new_courses` 받아 자동 등록
- `server.py` — `/api/pilots/courses/(\d+)` 라우트 등록

**프론트엔드:**
- 개인별 현황 탭 상단에 노란색 "⚙ 과목 관리" 버튼 (admin 전용)
- 모달: SIM/CPT 과목 / 비행 과목 두 칼럼, 각 과목별 수정/삭제, 새 과목 추가 폼
- AI 분석 시 미등록 과목 감지 → 토스트 "⚠ 미등록 과목 N개 발견" 노란 경고
- 저장 시 미등록 과목 있으면 승인 모달 자동 오픈 (저장 진행 차단)
- 각 과목별 ✓ 추가 / ✏ 이름 변경 후 추가 / ✗ 무시 선택, SIM/Flight 분류 변경 가능
- 예시 행에 이미지에서 발견된 컨텍스트 (조종사명/교관/시간) 표시

---

## 2026-04-24 — AI 데이터를 개인별 현황 탭에 자동 반영

### 사용자 요청
> 4/22, 4/23 AI 이미지 분석해서 데이터 저장한 값들 개인별 현황 탭에 표기가 안 되어 있는데?

### 응답
**원인:** 개인별 현황 탭은 `pilot_training` 테이블 (조종사 × 과목 완료 날짜/시간)을 읽는데, AI 저장이 `weekly_uploads`만 채우고 `pilot_training`엔 안 썼음.

**수정:**
- `_duration_from_slot()` helper 추가 — `"9:30~10:30"` → `"1:00"` 변환
- AI confirm이 이제 `per_sortie_rows`도 받아서: 조종사 이름 + sortie_code 매칭 → `pilot_training` UPSERT (`completed_date` = report_date, `completed_time` = duration)
- 매칭 안 된 (조종사 또는 과목) 경우는 skip 카운트로 응답
- 프론트엔드: payload에 `per_sortie_rows` 포함, 토스트에 "개인별 훈련 N건 반영" 추가

**4/22, 4/23 데이터 복구:** 업로드 이력에서 두 항목 삭제 → 다시 업로드/저장 (이번엔 pilot_training도 같이 INSERT)

---

## 2026-04-24 — AI 분석 결과 미리보기 기능 (저장 후 다시 보기)

### 사용자 요청
> AI 분석 파싱 데이터 화면도 저장해서 미리보기 버튼을 만들어 내용 다시 보고 싶을 때 쉽게 볼 수 있게끔 해줘.

### 응답
**DB:** `weekly_uploads.ai_parse_json TEXT` 컬럼 추가 (idempotent migration with logging)

**백엔드:**
- AI confirm 시 `per_sortie_rows`, `aggregated_rows`, `report_date`, `special_notes`, `model_used`, `saved_at`을 JSON으로 묶어 저장
- 새 endpoint `GET /api/pilots/weekly-uploads/{id}/ai-preview` — 저장된 parse JSON + 원본 이미지 (base64) 반환
- 업로드 목록 조회에 `has_ai_preview` flag 추가

**프론트엔드:**
- 업로드 이력 행에 🔍 미리보기 보라색 버튼 (AI 업로드만)
- 모달: 헤더 정보 (파일명, 보고일, 업로드자, 모델, 저장일시) + 특이사항 + 원본 이미지 + 소티별 상세 테이블 + 조종사별 집계 테이블

**기존 4/22, 4/23 업로드는 ai_parse_json이 비어있어서 미리보기 버튼 안 뜸.** 삭제 후 재저장 필요.

---

## 2026-04-24 — 실시간 반영 이해 + 낙관적 UI 업데이트 적용

### 사용자 요청
> 어떤 웹사이트는 삭제/추가 같은 변화가 생기면 새로고침 안 해도 자동으로 반영되어 화면이 바뀜. 어떻게 함? + 내가 변경한 거 즉시 반영 안 되는 느낌.

### 응답
**실시간 업데이트 4가지 방식 설명:** Polling, WebSocket (이미 프로젝트에 인프라 존재), SSE, Optimistic UI.

**진단:** Render 무료 플랜 cold start로 `loadAll()`의 6개 병렬 API 호출이 10초 이상 걸림. 그래서 사용자 액션 후 토스트만 뜨고 화면은 한참 뒤에 바뀌는 것처럼 체감됨.

**수정:** 주요 동작에 낙관적 UI 업데이트 적용 (`public/index.html`). 서버 응답 기다리지 않고 로컬 state 즉시 갱신, 실패 시 rollback.
- 과목 추가/수정/삭제
- 업로드 이력 삭제 / 이름 수정
- 조종사 사진 업로드
- 개인별 현황 셀 (날짜/시간) 저장/삭제

---

## 2026-04-24 — 과목 관리 모달 크기 확장 + 순서 변경 기능

### 사용자 요청
> 개인별 현황, 과목 관리 기능 팝업 화면 크기를 좀 더 키우고, 과목별 순서를 옮길 수 있게 해줘.

### 응답
**Modal 컴포넌트 확장** (`public/index.html`)
- `size` prop 추가: `lg` (880px), `xl` (1200px), `full` (1400px). 기본값(520px)은 기존 호환 유지.

**과목 관리 모달**
- `size="xl"` 적용으로 훨씬 넓게 표시
- 테이블에 **순서** 칼럼 추가 (맨 왼쪽)
- 각 행에 ▲ (위로) / ▼ (아래로) 버튼 — 첫 행/마지막 행에서는 비활성화
- `moveCourse()` 함수: sort_order 기반으로 이웃과 swap, 동일 값이면 전체 재번호(10/20/30...). 낙관적 업데이트 적용 (UI 즉시 반영 + 서버 PATCH 병렬 호출).
- 테이블 maxHeight 340 → 520 로 확장.

**기타 모달도 같이 확장**
- AI 미리보기 모달 → `size="xl"` (이미지 + 상세 + 집계 테이블 나란히)
- 미등록 과목 승인 모달 → `size="lg"` (컨텍스트 행이 많음)

---

## 2026-04-24 — 주간보고 대시보드와 개인별 현황 데이터 일치

### 사용자 요청
> 주간보고 대쉬보드랑 개인별현황 기록이랑 데이터 값이 매칭이 안 되는데?

### 응답
**원인 진단:**
- 주간보고 대시보드는 `weekly_report_data` (Excel/AI에 저장된 Plan/Done/Remain 숫자)
- 개인별 현황은 `pilot_training` (실제 완료 셀 날짜/시간)
- 두 저장소가 별개라 불일치 가능. 주요 원인:
  1. Excel 자체가 Plan/Done 타이핑값과 Individual Status 시트가 모순
  2. AI 업로드가 이미 완료된 과목을 증분 (weekly_report_data +1 이지만 pilot_training UPSERT는 행 추가 아님)

**해결 — 사용자가 "개인별 셀 수가 진짜" 선택:**

1. 진단 endpoint 추가 (`routes/ai_parse_routes.py` → `DiagnoseTrainingCountsHandler`)
   - `GET /api/admin/diagnose-training-counts`
   - 조종사별로 dashboard_sim_done / individual_sim_done / sim_diff 나란히 반환
   - 프론트 콘솔에서 `console.table()` 로 차이 한눈에 확인 가능

2. 대시보드 재계산 (`routes/pilot_routes.py` → `PilotWeeklyHandler`)
   - 기존: 최근 weekly_uploads 의 저장된 숫자 사용
   - 변경: 항상 `pilot_training` 의 COUNT 로 계산
   - Plan = `pilot_courses` COUNT (카테고리별)
   - Done = `pilot_training` COUNT (완료 날짜 NOT NULL)
   - Remain = max(0, Plan - Done)
   - → 두 화면이 항상 일치

**이후 동작:** weekly_uploads 는 여전히 업로드 이력/원본 파일 보관용으로 사용되지만, 실제 훈련 진도 숫자는 pilot_training 이 source of truth.

---

## 2026-04-24 — 과목 일련번호 자동 재정렬 + 업로드 이력 "0" 제거

### 사용자 요청
> 과목 수기로 수정하면 일련번호가 자동으로 안 맞춰지고 저렇게 이상하게 맞춰져 있어. 그리고 업로드 이력의 엑셀 파일 기록내역에 Manage칸 0이 표기되어 있는 거 뭐야.

### 응답
**Fix 1 — 과목 번호 자동 재정렬**

문제: C-27이 두 번 나오거나 C-33이 C-29 앞에 오는 식으로 수동 편집 후 과목 번호가 뒤섞임.

해결:
- 백엔드: `PilotCoursesRenumberHandler` 추가 (`POST /api/pilots/courses/renumber`)
  - SIM 과목 먼저 (sort_order 순), Flight 과목 이어서
  - `course_no` → C-01, C-02, ... 순차적으로 덮어씀
  - `seq_no` (카테고리 내 번호) + `sort_order` 도 함께 정리 (10, 20, 30...)
- 프론트엔드: `renumberCourses()` 함수 추가, 과목 추가/삭제/순서변경 후 자동 호출
- 과목 관리 모달 푸터 좌측에 **🔢 번호 재정렬 (C-01부터 다시)** 버튼 추가 — 기존에 뒤섞인 번호 한 번에 정리

**Fix 2 — Excel 업로드 행의 Manage 칸 "0" 제거**

문제: JSX `{u.has_ai_preview && <button>...}` 에서 `has_ai_preview=0` 이면 `0` 이 그대로 렌더링됨 (React 클래식 버그).

해결: `{!!u.has_ai_preview && <button>...}` 로 Boolean 강제 변환.

---

## 2026-04-24 — 요구사항 이력 파일 자동 관리

### 사용자 요청
> 앞으로 내가 적은 요구사항과 너의 답변을 날짜붙여서 파일로 따로 저장해줘. 나중에 한눈에 알아보기 쉽게. 간단하게 요구사항 제목도 붙이고. 해당 이력 관리 파일은 하나로 통일해서 파일안에 제목, 나의 질문, 너의 답변 전체를 다 작성해.

### 응답
- 메모리에 선호도 저장 (`feedback_requirements_log.md`) — 향후 모든 ATMS_System 작업에서 자동으로 이 파일 업데이트하도록 함
- 이 파일 (`REQUIREMENTS_HISTORY.md`) 생성하여 지금까지의 모든 요구사항 정리
- 형식: `## YYYY-MM-DD — [제목]` → `### 사용자 요청` → `### 응답`
- 단순 질문/응답은 제외, 실제 코드 변경/기능 작업만 기록
- 새 항목은 항상 파일 끝에 추가 (절대 기존 내용 덮어쓰지 않음)

---
