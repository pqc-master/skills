# 연결 설정과 조회 범위

## 기존 봇 설정 재사용

인증 우선순위는 프로세스 환경변수, 설정 파일 순서다. 파일은 명시한 `--env-file`을 우선 사용하고, 생략하면 `~/.config/discord-channel-reader/.env`, 없으면 `~/.fiesta-discord/.env`를 사용한다. `DISCORD_BOT_TOKEN` 또는 `FIESTA_RELAY_BOT_TOKEN`을 읽는다. 쉘로 파일을 source하지 않는다. POSIX 설정 파일 권한은 600으로 둔다. 전역 `--env-file` 옵션은 하위 명령보다 앞에 둔다.

```sh
python3 /ABSOLUTE/SKILL/PATH/scripts/discord_reader.py \
  --env-file /ABSOLUTE/PRIVATE/PATH/.env doctor
```

기존 Fiesta 설정은 읽기만 한다. Fiesta 전용 topic이나 대회 설정이 필요하지 않으며 게시·웹훅 권한도 요구하지 않는다.

## 봇이 없는 경우

[Discord Developer Portal](https://discord.com/developers/applications)에서 애플리케이션/봇을 만들고 대상 서버에 초대한다. 해당 채널에서 **View Channel**, **Read Message History** 권한을 부여하고 Bot 설정에서 **Message Content Intent**를 활성화한다. 앱 규모에 따라 privileged intent 승인이 필요할 수 있다. 스레드는 부모 채널의 권한과 비공개 스레드의 가시성에 영향을 받는다. 음성·스테이지 채널의 텍스트 대화에는 Connect 권한도 필요하다. 서버 관리자 권한을 일괄 요구하지 않는다.

토큰은 채팅에 붙이지 않고 로컬 환경변수나 비공개 설정 파일에 저장한다. 다음 코드는 사용자의 터미널에서 숨김 입력을 받아 새 파일을 생성하며 기존 파일을 덮어쓰지 않는다.

```sh
python3 - <<'PYSETUP'
import getpass, os
from pathlib import Path
path = Path.home() / '.config/discord-channel-reader/.env'
path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
token = getpass.getpass('Discord bot token: ').strip()
if not token or any(c.isspace() for c in token):
    raise SystemExit('유효한 봇 토큰을 입력하세요.')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('DISCORD_BOT_TOKEN=' + token + '\n')
print('설정 파일을 저장했습니다.')
PYSETUP
```

Discord 설정 → 고급 → 개발자 모드를 켜면 서버·카테고리·채널의 우클릭 메뉴에서 ID를 복사할 수 있다. 카테고리 ID는 채널 ID와 다르다.

## 전체 수집의 의미

API가 반환할 수 있는 현재 메시지 전부를 페이지 단위로 가져온다. 삭제 기록이나 이전 편집본을 복원하는 기능이 아니다. 기본적으로 내보내기 시작 후 생성된 메시지를 제외한다. 수집 도중 변경되는 메시지까지 동일 시점으로 고정할 수는 없다.

스레드는 별도 채널이므로 부모 채널 메시지 API만으로는 수집되지 않는다. `--include-threads`로 활성 스레드 및 보관된 공개 스레드, 권한이 허용하는 비공개 스레드를 조회한다. 비공개 스레드 중 봇에 보이지 않는 것은 탐지조차 못 할 수 있으므로 결과는 봇에 보이는 범위다. 포럼·미디어 채널의 게시글도 스레드다. 스레드 검색이나 기록 조회 중 실패한 범위는 부분 결과로 보고한다.

메시지 JSONL의 첨부는 이름·크기·URL 등 메타데이터를 보존한다. 첨부 파일 본문, 반응한 모든 사용자 목록, 과거에 삭제된 반응 등은 메시지 내보내기 대상이 아니다. 서명된 첨부 URL은 만료될 수 있다. 내보낸 기록은 로컬에만 보관하며 파일 경로를 제시한다.

## 오류 대응

- 401: 봇 토큰을 확인한다. 토큰을 로그에 출력하지 않는다.
- 403 또는 열람 권한 부족: 봇의 채널별 권한과 스레드 접근을 확인한다.
- 빈 메시지 목록: 실제 빈 채널인지 `READ_MESSAGE_HISTORY` 권한 누락인지 확인한다. 후자를 빈 채널로 보고하지 않는다.
- 본문 정보 누락: 애플리케이션 MESSAGE CONTENT intent 상태를 확인한다. 빈 content만으로 잘못된 설정이라고 단정하지 않는다. 첨부/시스템 메시지는 정상적으로 본문이 없을 수 있다.
- 429: 응답의 `retry_after` 또는 `Retry-After`를 따른다. 재시도 예산을 넘으면 부분 결과를 보존하고 중단한다.
- 중단/네트워크 오류: 완료 상태를 먼저 확인한다. 기존 출력에 덧붙여 완료로 만들지 말고 새 경로로 다시 실행한다.

## 공식 API 근거

확인일: 2026-11-15. Discord REST API v10. Python 표준 라이브러리만 사용한다.

- [Channel resource](https://docs.discord.com/developers/resources/channel): 채널 유형·부모 관계, 보관된 스레드 목록과 커서.
- [Guild resource](https://docs.discord.com/developers/resources/guild): 길드 채널 목록(스레드 제외), 활성 스레드 목록, 역할·멤버 정보.
- [Message resource](https://docs.discord.com/developers/resources/message#get-channel-messages): 요청당 최대 100개, `before` 커서, 최신 순 응답, 기록 열람 권한 누락 시 빈 목록.
- [Permissions](https://docs.discord.com/developers/topics/permissions): 역할·채널 덮어쓰기와 스레드 권한.
- [Gateway / privileged intents](https://docs.discord.com/developers/events/gateway#privileged-intents): MESSAGE CONTENT가 HTTP API 본문 필드에도 미치는 영향.
- [Application resource](https://docs.discord.com/developers/resources/application): MESSAGE CONTENT 플래그.
- [Rate limits](https://docs.discord.com/developers/topics/rate-limits): 제한 헤더와 429 대기 시간.
