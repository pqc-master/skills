# 문제 메시지의 첨부 파일 받기

대화 내보내기는 첨부의 이름·크기·URL만 보존한다. 문제 설명이나 소스 파일을 실제로 읽어야 할 때 아래 다운로드 명령을 사용한다. 사용자는 문제 채널을 **이름·Discord 링크·ID**로 지정할 수 있다. 에이전트가 해당 채널의 실제 대화를 읽어 소스 메시지 ID와 첨부 ID를 확인한다. 여러 문제나 여러 버전의 소스가 있어 대상이 모호하면 임의의 첨부를 선택하지 않는다.

채널 이름만 받으면 먼저 `read channels`로 기본 카테고리의 실제 목록을 조회한다. 다른 카테고리를 명시했다면 `read channels --category-id CATEGORY_ID`를 사용하고 반환된 서버·카테고리를 확인한다. 이름이 정확히 일치하는 채널이 하나이면 그 ID로 대화를 읽고 첨부를 받는다. 부분 일치나 목록의 첫 항목으로 추측하지 않는다. 이름이 없거나 중복되거나 목록을 읽을 수 없을 때만 사용자에게 필요한 대상 정보를 확인한다. 유일하게 확인되는 이름에 대해 ID를 직접 복사해 달라고 요구하지 않는다.

```sh
<SKILL>/bin/pqc-discord download --channel-id CHANNEL_ID --message-id MESSAGE_ID --output /ABSOLUTE/NEW/FILES
```

`CHANNEL_ID`는 에이전트가 이름 조회 또는 제공된 링크·ID에서 확정한 값이며, `MESSAGE_ID`는 실제 대화에서 확인한 소스 메시지다. 조회부터 다운로드·최종 제출까지 같은 채널 ID를 유지하고, 확인한 채널 이름·링크·ID를 작업 근거에 남긴다. CLI에는 이름이 아니라 확정한 ID를 전달한다.

Windows에서는 `pqc-discord.exe`를 사용한다. 실행 파일이 없는 소스 설치의 대체 명령은 다음과 같다.

```sh
python3 <SKILL>/scripts/discord_download.py --channel-id CHANNEL_ID --message-id MESSAGE_ID --output /ABSOLUTE/NEW/FILES
```

`<SKILL>`은 설치된 `discord-channel-reader`의 절대 경로다. 특정 첨부만 받으려면 `--attachment-id ATTACHMENT_ID`를 추가한다. 이 옵션은 여러 번 지정할 수 있으며, 생략하면 **지정한 한 메시지의 첨부 전부**를 받는다. 다른 메시지나 채널의 파일을 재귀적으로 수집하지 않는다.

기본 서버는 `1563153526283051008`, 기본 문제 카테고리는 `1570317863984701441`이다. 사용자가 다른 범위를 지정한 경우 `--guild-id`와 `--category-id`를 함께 전달한다. 봇에는 해당 문제 채널의 **채널 보기·메시지 기록 읽기**가 필요하고 메시지 본문·첨부 가시성에는 **Message Content Intent**가 영향을 준다. 웹후크 관리 권한은 다운로드에 필요 없다.

## 결과 확인

명령은 봇으로 메시지를 새로 조회하여 만료되지 않은 첨부 URL을 받은 뒤, 별도 인증 헤더 없이 Discord CDN에서 파일을 받는다. 대화 본문이나 오래된 내보내기의 URL을 그대로 실행하지 않는다. CDN 주소는 허용된 HTTPS 호스트와 해당 채널·첨부 ID의 경로로 제한하며 리디렉션을 따르지 않는다.

출력 폴더의 `download-manifest.json`에는 다음 정보가 기록된다.

- `complete`: 선택한 첨부를 모두 받았는지 여부
- 서버·카테고리·채널·메시지 ID와 원본 메시지 링크
- 첨부별 `attachment_id`, `original_filename`, `stored_filename`, `size`, `sha256`
- 실패 시 토큰·서명된 다운로드 URL이 없는 오류 설명

**`complete: true`와 종료 코드 0을 모두 확인한 뒤** 다음 단계로 진행한다. 저장 이름은 `첨부ID-안전하게 정리한 파일명`이다. 실제 파일 위치는 `output_directory`와 `stored_filename`을 연결해 사용하며, 원본 이름에서 파일 경로를 추측하지 않는다. 원본 이름은 manifest에 별도로 남는다. 파일 내용은 변환하지 않으며 받은 바이트의 SHA-256을 계산한다. ZIP을 자동으로 풀거나 코드를 실행하지 않는다.

기존 출력 폴더나 파일은 덮어쓰지 않는다. 사용자 지정 심볼릭 링크를 경유하는 출력 경로도 거부한다. macOS의 표준 `/tmp`·`/var` 경로는 실제 `/private/…` 경로로 정규화한다. 부분 실패가 발생하면 성공한 파일과 `complete: false` manifest는 남기고, 미완성 파일은 결과로 받아들이지 않는다. 재시도는 메시지 ID를 그대로 사용하되 새 출력 폴더로 실행한다.

다운로드 한도는 파일당 **32 MiB**, 한 번에 **128 MiB**, 파일당 처리 시간 **120초**다. 이 값은 로컬 도구의 다운로드 제한이며 Discord의 업로드 제한과 다르다. 크기 제한 초과 시 잘라 받거나 성공으로 처리하지 않는다. 받은 파일 크기가 메시지에 기록된 크기와 다르면 실패로 표시한다.

## 공식 근거

확인일: 2026-11-15. Discord REST API v10. 다운로드 구현은 Python 표준 라이브러리와 배포본의 인증서 저장소를 사용한다.

- [Signed Attachment CDN URLs](https://docs.discord.com/developers/reference#signed-attachment-cdn-urls): 첨부 URL은 만료되며 메시지를 새로 조회하면 갱신된 URL이 반환된다.
- [Get Channel Message](https://docs.discord.com/developers/resources/message#get-channel-message): 특정 메시지 조회와 채널 보기·메시지 기록 읽기 권한.
- [Message Object](https://docs.discord.com/developers/resources/message#message-object): Message Content Intent가 첨부 목록에도 영향을 준다.
