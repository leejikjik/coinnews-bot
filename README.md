# 코인 롱/숏 확률 텔레그램 봇 (Render 배포)

## 기능
- DM 명령어:
  - `/start` : 환영 인사 + 고유 ID 부여
  - `/ratio <심볼> [간격]` : 롱/숏 확률 (기본 5m)
  - `/watchlist` : 모니터링 목록
  - `/help` : 도움말
  - `/admin_broadcast <메시지>` : 관리자만 가능
- 그룹방: 명령어 차단, 스케줄 자동 리포트만 전송
- 스케줄:
  - 매시 정각: 1시간 리포트
  - 4시간마다: 4시간 리포트
  - 5분마다: 급등 감지(기본 +2.5%)

## 배포 절차
1) Render에서 **New +** → **Blueprint**로 본 리포지토리 연결
2) `render.yaml`에 따라 서비스 2개가 생성됨
   - `coin-longshort-web` (Flask)
   - `coin-longshort-worker` (PTB 루프 + APScheduler)
3) 환경변수 설정
   - `TELEGRAM_BOT_TOKEN` : 봇 토큰
   - `GROUP_CHAT_ID` : 자동 전송할 대상 그룹 ID (예: -100xxxxxxxxxx)
   - `ADMIN_USER_ID` : 관리자 텔레그램 ID (정수)
   - `WEBHOOK_URL` : `coin-longshort-web`의 퍼블릭 URL + `/webhook`
     - 예) https://your-web.onrender.com/webhook
   - `WEBHOOK_SECRET` : 임의 문자열(Flask/Telegram 시크릿 헤더 일치)
   - `WATCHLIST` : 모니터링 심볼 CSV (기본 BTCUSDT,ETHUSDT)
   - `PUMP_THRESHOLD_PCT` : 급등 감지 임계값(%) 기본 2.5
4) **그룹에 봇 추가 & 메시지 권한 허용**
5) 배포 완료 후, 개인 DM에서 `/start` 테스트 → `/ratio BTCUSDT 5m`

## 주의
- 그룹에서는 명령어 무시. 자동 리포트만 발송.
- 바이낸스 API 상태에 따라 일부 지표가 None일 수 있으며, 이때는 중립(50%) 처리.
- Render Free 플랜은 슬립이 있을 수 있으므로, 트래픽/리포트 주기를 조절하세요.
