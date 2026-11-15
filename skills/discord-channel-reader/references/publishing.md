# 작성자 이름을 붙여 Discord에 게시하기

각자의 컴퓨터에서 스킬을 실행할 때 Discord 웹훅으로 텍스트를 보낸다. 별도 봇 서버나 상시 실행 프로그램은 필요 없다. 조회·내보내기에는 봇 토큰을 사용하지만, 게시에는 채널별 웹훅 URL을 사용한다.

표시 이름을 `민영`으로 설정하면 메시지 작성자 이름에 **`민영 · Codex`**가 표시된다. 다른 사람은 자신의 컴퓨터에서 다른 이름을 설정하면 된다. 접미사까지 합쳐 최대 80 UTF-16 단위를 허용한다. 이 이름은 사용자가 정한 표시이며 Discord 계정을 인증한 결과는 아니다.

## 1. 게시할 채널에 웹훅 만들기

1. Discord **서버 설정 → 연동(Integrations) → 웹훅 → 새 웹훅**으로 이동한다. 해당 서버의 웹훅 관리 권한이 필요하다.
2. 기본 이름을 `PQC 작업 공유` 등으로 정하고 글을 올릴 일반 텍스트 채널을 선택한다.
3. 저장한 뒤 **웹훅 URL 복사**를 누른다. URL에는 게시 권한을 가진 토큰이 포함되므로 채팅·GitHub에 공유하지 않는다.

[Discord 공식 웹훅 생성 안내](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks)를 참고한다. 다른 채널에도 게시하려면 그 채널의 웹훅을 추가로 만든다. 웹훅 하나를 카테고리 전체의 게시 주소로 사용하지 않는다.

기본 서버는 `1563153526283051008`, 채널을 찾을 기본 카테고리는 `1570317863984701441`이다. 게시 대상은 카테고리가 아닌 **웹훅이 연결된 채널 ID**로 지정한다. 웹훅 메타데이터에는 카테고리 정보가 없어 게시 명령이 카테고리 소속까지 검사하지는 않는다.

## 2. 처음 연결할 때 함께 설정

봇 토큰·이름·웹훅을 따로 설정할 필요 없이 [통합 설정](setup.md#통합-설정)을 한 번 실행한다. 이미 토큰을 저장했다면 재사용하고 이어서 게시 설정을 진행한다. 아래 명령을 **사용자 본인의 macOS·Linux 터미널**에서 실행한다. 이름을 직접 입력하고 싶으면 `--name`을 생략한다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_setup.py" --name "민영"
```

게시만 사용하려면 `--skip-bot`을 추가한다. 게시 설정을 선택한 뒤 웹훅 URL 입력 안내가 나오면 복사한 URL을 붙여넣고 Enter를 누른다. URL은 화면에 표시되지 않는다. 명령은 웹훅의 서버·채널을 조회한 뒤 다음 위치에 이름과 URL을 저장한다.

```text
~/.config/discord-channel-reader/publisher.json
```

파일은 소유자만 읽고 쓸 수 있도록 권한 `600`으로 저장한다. 기존 이름·채널 설정이 있으면 URL을 다시 입력하지 않고 재사용할 수 있다. 저장 완료 출력에 표시되는 **채널 ID**를 이후 명령에 사용한다. 설정 과정에서는 메시지를 게시하지 않는다.

웹훅만 추가·교체하는 기존 명령도 계속 사용할 수 있다. 기존의 다른 채널 설정을 보존하고 같은 채널의 URL을 다시 등록하면 해당 채널의 설정을 갱신한다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_publish.py" setup
```

기본 서버와 다른 서버에 연결하려면 통합 설정 또는 위 `setup` 명령에 `--guild-id SERVER_ID`를 지정한다. 게시 전용 명령의 `--config PATH`로 다른 설정 파일을 사용할 때는 하위 명령보다 앞에 둔다. 파일을 저장소 밖에 보관하고 Git에 올리지 않는다.

복제한 저장소에서 직접 실행하려면 저장소 최상위 디렉터리에서 설치 경로 대신 `skills/discord-channel-reader/scripts/` 아래의 해당 스크립트를 사용한다. Python 3.9 이상이며 추가 패키지는 필요 없다. 위 셸 구문은 Windows PowerShell용이 아니다.

## 3. 이름만 변경

다음 명령은 저장된 이름만 바꾼다. 웹훅 URL을 다시 입력하지 않으며, 네트워크 요청이나 게시도 하지 않는다. 변경한 이름은 이후 등록된 모든 채널로 보내는 새 글에 적용된다. 이미 게시한 글은 수정하지 않는다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_publish.py" profile --name "철수"
```

## 4. 연결 확인과 미리보기

`CHANNEL_ID`는 설정 완료 시 출력된 실제 채널 ID로 바꾼다. `doctor`는 웹훅이 설정한 서버·채널에 연결되어 있는지 확인한다. 메시지는 보내지 않는다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_publish.py" doctor --channel-id CHANNEL_ID
```

본문을 UTF-8 텍스트 파일로 작성한 뒤 `preview`로 작성자 표시 이름·대상 채널·내용을 확인한다. `preview`는 네트워크에 접속하지 않는다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_publish.py" preview \
  --channel-id CHANNEL_ID --content-file ./message.md
```

짧은 글은 `--content-file` 대신 `--text '공유할 내용'`을 사용할 수 있다. 본문은 최대 2,000 UTF-16 단위까지 허용한다. 일반 한글은 한 글자가 1단위, 일부 이모지는 2단위로 계산하는 보수적인 제한이다. 초과한 글을 자동으로 잘라 보내거나 여러 메시지로 나누지 않는다.

## 5. 게시

아래 **`send` 명령은 실제로 Discord에 메시지를 보낸다.** 게시할 채널과 내용을 확인한 뒤 실행한다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_publish.py" send \
  --channel-id CHANNEL_ID --content-file ./message.md
```

전송 직전에 웹훅의 서버·채널·ID가 설정과 일치하는지 다시 확인한다. 본문에 사용자·역할·`@everyone` 표기가 있어도 자동 멘션 알림을 보내지 않는다. 성공하면 게시한 메시지의 링크를 반환한다.

Codex에서는 다음처럼 요청한다. 아래 채널 ID는 예시이며 실제 ID로 바꾼다.

```text
$discord-channel-reader 표시 이름을 민영으로 바꿔줘.
$discord-channel-reader message.md를 채널 ID 234567890123456789에 올릴 내용으로 미리 보여줘.
$discord-channel-reader message.md 내용을 채널 ID 234567890123456789에 올려줘.
```

조회·요약·미리보기 요청만으로 게시하지 않는다. 게시를 명시적으로 요청하고 채널과 내용이 정해져 있으면 같은 게시에 대한 확인을 반복하지 않는다.

## 오류와 지원 범위

- **다른 서버·채널 또는 잘못된 웹훅:** 게시를 중단한다. 웹훅이 이동되었거나 재생성됐다면 `setup`으로 다시 등록한다. 입력 URL은 `https://discord.com/api/webhooks/…` 또는 `/api/v10/webhooks/…` 형태만 지원한다.
- **401·403·404:** 웹훅이 유효한지, 삭제되었는지 확인한다. 토큰이나 전체 API 응답은 출력하지 않는다.
- **429:** Discord가 지정한 대기 시간에 따라 제한된 횟수로 재시도한다. 대기 한도를 넘으면 중단한다.
- **전송 여부 불명:** 전송 중 네트워크 오류·서버 오류·확인할 수 없는 성공 응답이 오면 종료 코드 2로 끝낸다. 중복 게시를 피하려고 자동 재전송하지 않는다. 대상 채널에서 글이 올라갔는지 먼저 확인한다.
- **지원 범위:** 일반 텍스트 채널에 텍스트 한 건 게시. 첨부 업로드, 프로필 사진 변경, 포럼·미디어 글, 스레드 게시, 기존 메시지 수정·삭제는 지원하지 않는다.
- **종료 코드:** 0은 명령 성공, 1은 입력·설정·확정된 API 오류, 2는 전송 여부 불명, 130은 사용자 중단이다. 전송 중 중단했다면 채널에서 게시 여부를 확인한다. `preview` 성공은 실제 게시 성공을 의미하지 않는다.

## 공식 근거와 검증

확인일: 2026-11-15. Discord REST API v10, Python 표준 라이브러리 사용.

- [Get Webhook with Token](https://docs.discord.com/developers/resources/webhook#get-webhook-with-token): 봇 토큰 없이 웹훅 메타데이터 조회.
- [Execute Webhook](https://docs.discord.com/developers/resources/webhook#execute-webhook): `username`, `content`, `wait=true`, 스레드·포럼 관련 매개변수.
- [Allowed Mentions](https://docs.discord.com/developers/resources/message#allowed-mentions-object): `allowed_mentions: {"parse": []}`로 자동 멘션 비활성화.
- [Rate Limits](https://docs.discord.com/developers/topics/rate-limits#exceeding-a-rate-limit): 429 대기 시간과 재시도.

오프라인 테스트는 가상 URL·응답으로 설정 파일, 전송 대상 검사, 멘션, 호출 제한, 중복 게시 방지 처리를 검증한다. 실제 Discord 웹훅 게시·Windows 실행은 **NOT TESTED**이며, 테스트 중 실제 메시지를 보내지 않는다.
