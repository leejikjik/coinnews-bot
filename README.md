# 코인 롱/숏 확률 텔레그램 봇 (Render 배포)

## 변경 요약
- `httpx==0.27.0` → **`0.24.1`로 다운그레이드** (PTB 20.3 의존성 충돌 해결)
- `gunicorn==20.1.0` 추가 (web 서비스 실행용)

## 환경변수
- 필수: `TELEGRAM_BOT_TOKEN`, `GROUP_CHAT_ID`, `ADMIN_USER_ID`, `WEBHOOK_URL`, `WEBHOOK_SECRET`
- 선택: `WATCHLIST`(기본 `BTCUSDT,ETHUSDT`), `PUMP_THRESHOLD_PCT`(기본 `2.5`), `TZ`(기본 `Asia/Seoul`)

## 배포 순서
1. 이 리포지토리 4개 파일 푸시
2. Render **Blueprint Deploy**
3. web/worker 둘 다 환경변수 입력
4. 배포 완료 후 DM에서 `/start`, `/ratio BTCUSDT 5m` 테스트
