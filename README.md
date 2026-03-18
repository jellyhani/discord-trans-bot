# 🌐 Discord Unified Translation Bot

고성능 AI(GPT-5 / GPT-4.1 mini) 기반의 실시간 디스코드 번역 봇입니다. 
문맥을 파악한 정확한 번역은 물론, 한국어 구어체/오타 교정 기능까지 통합되어 있습니다.

## 🚀 주요 기능
- **통합 번역 (Unified Flow)**: 언어 감지 + 오타 교정 + 번역을 단 한 번의 API 호출로 수행하여 속도와 비용을 최적화했습니다.
- **스마트 하이브리드 모델**: 
  - 기본: `gpt-4.1-mini` (초고속, 저비용)
  - 문맥 필요 시: `gpt-5-mini` (추론 기반 정밀 번역)
- **역할 기반 자동 설정**: 특정 역할을 가진 유저에게 미리 설정된 번역 환경을 자동으로 부여합니다.
- **채널별 전용 설정**: 유저 설정보다 우선하는 채널별 고정 번역 규칙 지원.
- **로그 및 통계**: 관리자 로그 채널 전송 및 그래프를 통한 사용량 시각화.
- **고급 로그 관리**: `logs/` 폴더 내에 일일 단위로 회전하는 로그 시스템.

## 📁 프로젝트 구조
- `bot.py`: 메인 실행 파일.
- `core/`: 번역 엔진, 오타 감지, 문부부호 처리 등 핵심 로직.
- `database/`: SQLite DB 및 캐시, 사용자 설정 관리.
- `utils/`: 로그 매니저, 사용량 추적, 통계 차트 생성.
- `cogs/`: 디스코드 기능별(이벤트, 명령어, 관리자) 모듈.
- `scripts/`: 성능 테스트 및 관리용 유틸리티.
- `logs/`: 실시간 로그 저장 (일일 단위 회전).

## 🛠 설치 및 실행
1.  **환경 변수 설정**: `.env` 파일을 만들고 아래 내용을 채웁니다. (또는 `.env.example` 참고)
    ```env
    DISCORD_BOT_TOKEN=your_discord_token
    OPENAI_API_KEY=your_openai_key
    DISCORD_GUILD_ID=your_server_id
    ```
2.  **의존성 설치**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **인텐트 활성화**: 
    - [Discord Developer Portal](https://discord.com/developers/applications)에서 **MESSAGE CONTENT**와 **SERVER MEMBERS** 인텐트를 반드시 켭니다.
4.  **봇 실행**:
    ```bash
    python bot.py
    ```

## 🎮 주요 명령어

### 유저용 (Common)
- `/translate (text) (language)`: 수동 번역 요청.
- `/status`: **[통합]** 본인의 현재 설정(언어/자동번역) 및 상세 사용량 통계 확인.
- `/languages`: 지원하는 번역 언어 목록 확인.

### 관리용 (Administrator - `manage_guild` 권한 필요)
- `/setlang (language) [member/role]`: **[통합]** 본인, 특정 멤버 또는 역할의 번역 언어를 일괄 설정 및 관리.
- `/userlist`: **[신규]** 서버 내 설정된 모든 유저 및 역할의 언어 매핑 목록 조회.
- `/serverstats [chart]`: **[고도화]** 서버 전체 통계 요약 + **유저별 사용량 순위(Top 10)** + 시각화 차트.
- `/setlog [channel] [level]`: **[통합]** 로그 채널 및 상세도(Minimal/Normal/Verbose) 설정.
- `/setvision [model] [trigger]`: 이미지 번역용 비전 모델 및 트리거 접두사(예: `-i`) 설정.
- `/setchannel (action) (channel) [lang]`: 채널별 전용 번역 규칙(고정 번역) 설정.
- `/optimize`: 데이터베이스 공간 최적화(VACUUM) 수행.
- `/syncroles`: 서버 전체 멤버의 역할을 스캔하여 언어 설정을 일괄 동기화.
- `/dict /ignorechannel /clearcache`: 사전 관리, 채널 제외, 캐시 초기화 등.

## 📝 관리 및 유지보수
- **비용 모니터링**: `/serverstats`에서 월간 예산 대비 사용량을 실시간으로 감시하며, 예산 임박 시 경고 알림을 표시합니다. (설정: `config.py`의 `MONTHLY_COST_LIMIT`)
- **삭제 연동**: 사용자가 원본 메시지를 삭제하면 봇이 전송한 모든 번역 답변(이미지 포함)이 자동으로 함께 삭제됩니다.
- **로그 시스템**: `logs/` 폴더 내에 일일 단위로 회전하는 로그 시스템을 통해 모든 API 호출과 오류를 추적합니다.
