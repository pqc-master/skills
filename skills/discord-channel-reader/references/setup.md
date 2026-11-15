# 처음 연결하기와 조회 범위

처음 연결할 때 봇 토큰·표시 이름·웹훅 URL을 한 번에 설정한다. 봇 생성과 읽기 권한은 아래에서, 게시할 채널의 웹훅 생성은 [웹훅 게시 가이드](publishing.md)에서 확인한다.

## 기본 대상과 인증

`categories`는 서버 `1563153526283051008`, `channels`는 카테고리 `1570317863984701441`을 기본으로 사용한다. `--guild-id` 또는 `--category-id`를 명시하면 해당 값을 사용한다. `export`에는 선택한 `--channel-id`가 항상 필요하다.

이 ID들은 조회 대상이며 인증 정보가 아니다. 각 사용자는 자신의 봇 토큰을 설정하고 해당 서버·채널의 열람 권한을 받아야 한다.

## 봇 생성과 서버 초대

이미 봇을 만들고 서버에 초대했다면 권한을 확인한 뒤 [통합 설정](#통합-설정)으로 이동한다. 이 스킬은 실행할 때 Discord HTTP API에 요청하므로 별도 봇 서버나 상시 실행 프로그램이 필요 없다. Discord에서 봇이 오프라인으로 표시되어도 조회할 수 있다.

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 **New Application**을 누르고 봇 이름을 입력해 생성한다.
2. 왼쪽 **Bot → Privileged Gateway Intents**에서 **Message Content Intent**를 켜고 저장한다. 메시지 본문·첨부 등을 가져오기 위한 설정이며, 앱 규모에 따라 별도 승인이 필요할 수 있다.
3. **Installation**에서 **Guild Install**을 활성화한다. **Install Link**는 **Discord Provided Link**로 선택하고, **Default Install Settings → Guild Install**에서 scope는 `bot`, 권한은 **View Channels**와 **Read Message History**로 설정한다.
4. **Install Link**를 열어 대상 서버에 봇을 추가한다. 기본 서버 ID는 `1563153526283051008`이다. 초대하는 계정에 해당 서버의 관리 권한이 있어야 한다.
5. 대상 카테고리 `1570317863984701441`과 조회할 채널에서 봇의 **채널 보기·메시지 기록 읽기**를 허용한다. 비공개 카테고리나 별도 권한이 설정된 채널은 초대할 때 부여한 권한만으로 접근되지 않을 수 있다.
6. 토큰이 없다면 Developer Portal의 **Bot → Reset Token**에서 발급받는다. 이미 발급받아 보관한 토큰이 있으면 그대로 사용한다. 재발급하면 이전 토큰은 사용할 수 없다.

[공식 봇 생성·설치 안내](https://docs.discord.com/developers/quick-start/getting-started)와 [Message Content Intent 설명](https://docs.discord.com/developers/events/gateway#message-content-intent)을 참고한다. 스레드는 부모 채널의 권한과 비공개 스레드의 가시성에 영향을 받는다. 음성·스테이지 채널의 텍스트 대화에는 **Connect** 권한도 필요하다. 이 스킬에 서버 관리자 권한을 일괄 부여할 필요는 없다.

## 통합 설정

스킬 설치 후 **사용자 본인의 macOS·Linux 터미널**에서 아래 명령을 한 번 실행한다. `CODEX_HOME`을 설정한 경우 해당 설치 위치를 사용한다. 아래 셸 구문은 Windows PowerShell용이 아니다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_setup.py"
```

복제한 저장소에서 직접 실행한다면 저장소 최상위 디렉터리에서 `python3 skills/discord-channel-reader/scripts/discord_setup.py`를 사용한다.

설정 순서는 다음과 같다.

1. **봇 토큰:** 저장된 전용 설정이 없으면 토큰을 숨김 입력한다. 토큰 앞에 `Bot `을 붙이지 않는다. 이미 설정한 토큰은 재사용하고, 환경변수나 Fiesta 설정이 발견되면 봇 이름·설정 출처를 확인한 뒤 재사용 여부를 선택한다. 새 토큰은 봇 인증이 성공한 뒤 저장한다.
2. **게시 기능 선택:** `웹훅 게시도 설정할까요?`에 답한다. 조회만 사용할 때는 건너뛴다.
3. **표시 이름·웹훅:** 처음 설정한다면 표시 이름을 입력하고, 이어서 웹훅 URL을 숨김 입력한다. 기존 이름·채널별 웹훅이 있으면 재사용하며, 필요한 경우 채널을 추가할 수 있다.

이름을 `민영`으로 설정하면 게시할 때 `민영 · Codex`로 표시된다. 설정은 다음 위치에 소유자만 읽고 쓸 수 있는 권한(`600`)으로 저장한다. 토큰·웹훅 URL은 채팅·명령 인자·GitHub에 붙이지 않는다.

| 저장 위치 | 내용 |
| --- | --- |
| `~/.config/discord-channel-reader/.env` | 새로 입력한 봇 토큰. 환경변수·Fiesta 설정을 재사용하면 기존 출처를 그대로 사용 |
| `~/.config/discord-channel-reader/publisher.json` | 표시 이름과 채널별 웹훅 URL |

이후 실행에서 저장한 값을 자동으로 읽으므로 매번 입력할 필요가 없다. 설정 과정은 인증·웹훅 조회만 수행하며 메시지를 보내지 않는다. 봇 토큰 저장 후 웹훅 설정에서 실패하더라도 저장한 봇 설정은 유지된다. 결과에 표시된 완료·실패 단계를 확인하고 같은 명령을 다시 실행하면 된다.

필요한 부분만 설정할 때는 다음 옵션을 사용한다.

| 옵션 | 동작 |
| --- | --- |
| `--skip-publish` | 봇 토큰만 설정 |
| `--skip-bot` | 이름·웹훅만 설정 |
| `--name "민영"` | 표시 이름을 미리 지정 |
| `--guild-id SERVER_ID` | 웹훅의 대상 서버 지정 |
| `--replace-token` | 새 봇 토큰을 입력해 전용 설정 파일의 토큰 교체 |

프로세스의 `DISCORD_BOT_TOKEN`·`FIESTA_RELAY_BOT_TOKEN`은 파일보다 우선한다. 이 환경변수가 있으면 파일 토큰 교체가 바로 적용되지 않으므로 `--replace-token`은 중단하고 환경변수 정리를 안내한다. 실제 사용할 환경에서 해당 값을 정리한 뒤 다시 실행한다. 다른 프로그램의 설정을 자동 변경하지 않는다.

## 연결 확인

위 README의 방법으로 스킬을 설치했다면 macOS·Linux 터미널에서 다음을 실행한다. `CODEX_HOME`을 설정한 경우 그 설치 위치를 사용한다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_reader.py" doctor
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_reader.py" channels
```

복제한 저장소에서 직접 실행하려면 저장소 최상위 디렉터리에서 `python3 skills/discord-channel-reader/scripts/discord_reader.py doctor`와 `python3 skills/discord-channel-reader/scripts/discord_reader.py channels`를 사용한다.

`doctor` 결과에서 다음을 확인한다. 토큰 값은 출력하지 않는다.

| 항목 | 확인할 내용 |
| --- | --- |
| `username`, `bot_id` | 방금 초대한 봇인지 확인 |
| `bot_authentication` | `"ok"`이면 봇 토큰 인증 성공 |
| `message_content_intent` | `true`이면 본문 접근 설정 확인 완료. `false`이면 Bot 설정에서 켜고, `null`이면 함께 출력된 `warning` 확인 |
| `credential_source` | 새 파일을 사용했다면 홈 디렉터리 아래 `.config/discord-channel-reader/.env` 경로 |
| `channel_access` | `"not tested"`가 정상 출력. `doctor`는 채널 권한까지 검사하지 않음 |

`doctor`가 종료 코드 0으로 끝나더라도 모든 설정이 완료됐다는 뜻은 아니다. 이어서 실행한 `channels`에서 기본 카테고리의 채널 이름과 ID가 나오는지 확인한다. 목록 조회 성공도 개별 채널의 메시지 기록 열람까지 보장하지는 않는다. 대화 내보내기 시 해당 채널의 권한과 결과의 `metadata.json`을 확인한다.

새 토큰을 저장했는데 예전 봇이 나온다면 `credential_source`를 확인한다. **프로세스 환경변수는 `--env-file`보다도 우선**한다. 아래 명령은 두 토큰 환경변수를 해당 실행에서만 제외하여 새 설정 파일로 인증을 확인한다. 다른 프로그램의 설정은 변경하지 않는다.

```sh
env -u DISCORD_BOT_TOKEN -u FIESTA_RELAY_BOT_TOKEN \
  python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_reader.py" \
  --env-file "$HOME/.config/discord-channel-reader/.env" doctor
```

## 기존 봇 설정 재사용

인증 우선순위는 프로세스 환경변수, 설정 파일 순서다. 파일은 명시한 `--env-file`을 우선 사용하고, 생략하면 `~/.config/discord-channel-reader/.env`, 없으면 `~/.fiesta-discord/.env`를 사용한다. `DISCORD_BOT_TOKEN` 또는 `FIESTA_RELAY_BOT_TOKEN`을 읽는다. 쉘로 파일을 source하지 않는다. POSIX 설정 파일 권한은 600으로 둔다. 전역 `--env-file` 옵션은 하위 명령보다 앞에 둔다.

```sh
python3 /ABSOLUTE/SKILL/PATH/scripts/discord_reader.py \
  --env-file /ABSOLUTE/PRIVATE/PATH/.env doctor
```

`/ABSOLUTE/SKILL/PATH`와 `/ABSOLUTE/PRIVATE/PATH/.env`는 실제 경로로 바꾼다. 기존 Fiesta 설정은 읽기만 한다. Fiesta 전용 topic이나 대회 설정이 필요하지 않으며 게시·웹훅 권한도 요구하지 않는다.

## 다른 서버·카테고리 조회

Discord 설정 → 고급 → 개발자 모드를 켜면 서버·카테고리·채널의 우클릭 메뉴에서 ID를 복사할 수 있다. 카테고리 ID는 채널 ID와 다르다.

`categories --guild-id SERVER_ID` 또는 `channels --category-id CATEGORY_ID`로 다른 대상을 지정한다. 사용하는 봇이 그 서버에 초대되어 있고 해당 채널에 접근할 수 있어야 한다.

## 전체 수집의 의미

API가 반환할 수 있는 현재 메시지 전부를 페이지 단위로 가져온다. 삭제 기록이나 이전 편집본을 복원하는 기능이 아니다. 기본적으로 내보내기 시작 후 생성된 메시지를 제외한다. 수집 도중 변경되는 메시지까지 동일 시점으로 고정할 수는 없다.

스레드는 별도 채널이므로 부모 채널 메시지 API만으로는 수집되지 않는다. `--include-threads`로 활성 스레드 및 보관된 공개 스레드, 권한이 허용하는 비공개 스레드를 조회한다. 비공개 스레드 중 봇에 보이지 않는 것은 탐지조차 못 할 수 있으므로 결과는 봇에 보이는 범위다. 포럼·미디어 채널의 게시글도 스레드다. 스레드 검색이나 기록 조회 중 실패한 범위는 부분 결과로 보고한다.

메시지 JSONL의 첨부는 이름·크기·URL 등 메타데이터를 보존한다. 첨부 파일 본문, 반응한 모든 사용자 목록, 과거에 삭제된 반응 등은 메시지 내보내기 대상이 아니다. 서명된 첨부 URL은 만료될 수 있다. 내보낸 기록은 로컬에만 보관하며 파일 경로를 제시한다.

## 오류 대응

- 401: 봇 토큰을 확인한다. 토큰을 로그에 출력하지 않는다.
- 403 또는 열람 권한 부족: `doctor`에 표시된 봇이 대상 서버에 초대됐는지 먼저 확인하고, 카테고리·채널별 권한과 스레드 접근을 확인한다. 다른 봇을 초대하고 기존 봇의 토큰을 사용하는 경우도 확인한다.
- 빈 메시지 목록: 실제 빈 채널인지 `READ_MESSAGE_HISTORY` 권한 누락인지 확인한다. 후자를 빈 채널로 보고하지 않는다.
- 본문 정보 누락: 애플리케이션 MESSAGE CONTENT intent 상태를 확인한다. 빈 content만으로 잘못된 설정이라고 단정하지 않는다. 첨부/시스템 메시지는 정상적으로 본문이 없을 수 있다.
- 429: 응답의 `retry_after` 또는 `Retry-After`를 따른다. 재시도 예산을 넘으면 부분 결과를 보존하고 중단한다.
- 중단/네트워크 오류: 완료 상태를 먼저 확인한다. 기존 출력에 덧붙여 완료로 만들지 말고 새 경로로 다시 실행한다.

## 공식 API 근거

확인일: 2026-11-15. Discord REST API v10. Python 표준 라이브러리만 사용한다.

- [Getting started](https://docs.discord.com/developers/quick-start/getting-started): 애플리케이션 생성, 봇 토큰, 서버 설치 설정과 초대.
- [Channel resource](https://docs.discord.com/developers/resources/channel): 채널 유형·부모 관계, 보관된 스레드 목록과 커서.
- [Guild resource](https://docs.discord.com/developers/resources/guild): 길드 채널 목록(스레드 제외), 활성 스레드 목록, 역할·멤버 정보.
- [Message resource](https://docs.discord.com/developers/resources/message#get-channel-messages): 요청당 최대 100개, `before` 커서, 최신 순 응답, 기록 열람 권한 누락 시 빈 목록.
- [Permissions](https://docs.discord.com/developers/topics/permissions): 역할·채널 덮어쓰기와 스레드 권한.
- [Gateway / privileged intents](https://docs.discord.com/developers/events/gateway#privileged-intents): MESSAGE CONTENT가 HTTP API 본문 필드에도 미치는 영향.
- [Application resource](https://docs.discord.com/developers/resources/application): MESSAGE CONTENT 플래그.
- [Rate limits](https://docs.discord.com/developers/topics/rate-limits): 제한 헤더와 429 대기 시간.
