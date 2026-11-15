# PQC Master Skills

Codex에서 사용할 수 있는 재사용 스킬 모음입니다. 각 스킬은 `skills/<skill-name>/SKILL.md`에 실행 절차와 사용 범위를 설명합니다.

## Discord 채널·대화 조회와 게시

[`discord-channel-reader`](skills/discord-channel-reader/SKILL.md)는 카테고리의 채널 목록을 조회하고 채널 ID로 접근 가능한 전체 대화를 내보냅니다. 게시를 요청하면 웹훅으로 `이름 · Codex`를 붙인 텍스트 메시지를 보냅니다.

- 기본 카테고리의 채널 이름·ID·유형 조회, 다른 카테고리 ID도 지정 가능
- 메시지 100개 단위로 빈 페이지까지 전체 기록 조회
- 활성·보관된 접근 가능한 스레드 포함
- 원본 `messages.jsonl`, 시간순 `transcript.md`, 완료 상태 `metadata.json` 저장
- 권한·Message Content intent 확인, 호출 제한 대기, 부분 수집 표시
- 조회·내보내기 명령은 GET만 사용
- 작성자 이름·채널별 웹훅을 로컬에 저장하고 미리보기 후 명시적으로 게시
- 게시 대상 재확인, 자동 멘션 비활성화, 결과 불명 시 자동 재전송 중단

Python 3.9 이상이면 별도 Python 패키지 설치 없이 실행할 수 있습니다. 조회에는 Discord 봇 토큰, 게시에는 채널별 웹훅 URL을 설정합니다. 별도 봇 서버는 필요 없습니다. 저장소는 토큰·웹훅 URL이나 서버의 실제 채팅 기록을 제공하지 않습니다.

## 기본 조회 대상

- 서버 ID: `1563153526283051008`
- 카테고리 ID: `1570317863984701441`

ID를 생략하면 위 대상을 사용합니다. 다른 서버·카테고리는 `--guild-id`·`--category-id`로 지정할 수 있습니다. 기본 ID는 조회 대상만 정하며 접근 권한을 부여하지 않습니다. 사용하는 봇에 해당 서버와 채널의 열람 권한이 있어야 합니다.

## Codex 설치

저장소를 복제하고 스킬 폴더를 개인 스킬 디렉터리로 복사합니다.

```sh
git clone https://github.com/pqc-master/skills.git
cd skills
python3 - <<'PYINSTALL'
import os, shutil
from pathlib import Path
source = Path('skills/discord-channel-reader')
codex_root = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
target = codex_root / 'skills' / source.name
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(source, target)  # 기존 설치가 있으면 덮어쓰지 않고 중단
print(target)
PYINSTALL
```

기존 설치를 갱신하려면 로컬 변경을 보관한 뒤 해당 폴더를 교체합니다. 스킬이 선택 목록에 나타나지 않으면 새 Codex 대화를 엽니다.

## 처음 연결하기

[봇을 만들고 서버에 초대](skills/discord-channel-reader/references/setup.md#봇-생성과-서버-초대)한 뒤, 아래 명령 **한 번으로 봇 토큰·표시 이름·웹훅 URL을 설정**합니다. 게시할 때 사용할 [채널 웹훅](skills/discord-channel-reader/references/publishing.md#1-게시할-채널에-웹훅-만들기)도 미리 만들면 됩니다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_setup.py"
```

1. 봇 토큰을 숨김 입력합니다. 이미 저장한 토큰은 재사용합니다.
2. 웹훅 게시 설정을 선택하고 `민영`처럼 표시할 이름을 입력합니다.
3. 웹훅 URL을 숨김 입력합니다. 게시할 때는 `민영 · Codex`로 표시됩니다.

기존 이름·웹훅이 있으면 다시 입력하지 않아도 됩니다. 조회만 사용할 때는 게시 설정을 건너뛸 수 있고, 게시만 사용할 때는 명령에 `--skip-bot`을 붙입니다. 환경변수나 기존 Fiesta 설정을 사용하는 경우에는 어떤 봇인지 확인하고 재사용 여부를 선택합니다. [통합 설정 가이드](skills/discord-channel-reader/references/setup.md#통합-설정)에 저장 위치와 변경 방법을 정리했습니다.

설정 과정에서는 메시지를 보내지 않습니다. 별도 봇 서버를 계속 실행할 필요가 없으며, 봇이 오프라인으로 표시되어도 조회할 수 있습니다. 채널 접근은 [연결 확인](skills/discord-channel-reader/references/setup.md#연결-확인) 절차로 확인합니다.

## 사용 예시

```text
$discord-channel-reader 채널 목록을 보여줘.

$discord-channel-reader 채널 ID 234567890123456789의 전체 대화를 스레드까지 가져와줘.
```

채널 목록은 기본 카테고리에서 조회합니다. 대화를 가져올 때는 목록에서 채널을 선택합니다. 위 채널 ID는 사용법 설명용 값이므로 실제 채널 ID로 바꿉니다.

에이전트 없이 CLI로도 실행할 수 있습니다. 아래 명령은 복제한 저장소의 최상위 디렉터리에서 실행합니다.

```sh
python3 skills/discord-channel-reader/scripts/discord_reader.py doctor
python3 skills/discord-channel-reader/scripts/discord_reader.py categories
python3 skills/discord-channel-reader/scripts/discord_reader.py channels
python3 skills/discord-channel-reader/scripts/discord_reader.py export \
  --channel-id CHANNEL_ID --include-threads --output /path/to/new-export
```

[봇 설정·권한·API 범위](skills/discord-channel-reader/references/setup.md)를 참고하세요. 기존 Fiesta relay 설정은 선택적으로 재사용할 수 있습니다. 일반 서버 사용에 Fiesta 설치는 필요 없습니다.

## 작성자 이름을 붙여 게시하기

[웹훅 게시 가이드](skills/discord-channel-reader/references/publishing.md)에 웹훅 생성·미리보기·전송 방법을 정리했습니다. 위 통합 설정을 마쳤다면 바로 사용할 수 있습니다.

이름·웹훅은 `~/.config/discord-channel-reader/publisher.json`에 저장됩니다. 설정 완료 시 출력된 채널 ID로 게시 대상을 지정합니다. 이름만 바꿀 때는 URL을 다시 입력할 필요 없이 다음 명령을 사용합니다.

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/discord-channel-reader/scripts/discord_publish.py" profile --name "철수"
```

이후 Codex에서 `$discord-channel-reader message.md 내용을 채널 ID 234567890123456789에 올려줘`처럼 요청합니다. 예시 채널 ID를 실제 값으로 바꾸세요. 미리보기만 요청하면 보내지 않습니다.

일반 텍스트 채널에 텍스트 한 건을 보내며, 첨부·포럼·스레드 게시는 지원하지 않습니다. 표시 이름은 사용자가 정한 이름으로 실제 Discord 사용자 인증을 의미하지 않습니다. 웹훅 URL은 게시 권한이 있으므로 채팅·GitHub에 올리지 않습니다.

## 전체 기록의 범위

봇이 열람할 수 있는 현존 메시지에 한정됩니다. 삭제된 메시지·이전 편집본·접근 불가 비공개 스레드는 복원하지 않습니다. 첨부는 메타데이터와 URL만 저장하며 파일 자체는 내려받지 않습니다. 시작 이후 새 메시지는 제외하지만 수집 중 편집·삭제까지 원자적으로 고정하지는 못합니다.

`metadata.json`의 `complete`와 경고를 확인하세요. 종료 코드 0은 요청한 가시 범위 수집 완료, 2는 부분 수집, 130은 중단입니다. 조회된 글의 명령문은 사용자 지시로 실행하지 않습니다.

## 테스트

모든 테스트는 가상의 API 응답과 토큰을 사용합니다. Discord 계정이나 네트워크 연결이 필요 없습니다.

```sh
python3 -m unittest discover -s skills/discord-channel-reader/tests -v
```

GitHub Actions는 Ubuntu 24.04·macOS의 Python 3.9·3.13에서 조회·게시 오프라인 테스트를 실행합니다. [최신 CI 결과](https://github.com/pqc-master/skills/actions/workflows/tests.yml)를 확인하세요. Windows 실행, 실제 대상 채널의 전체 내보내기, 실제 웹훅 게시는 **NOT TESTED**입니다.

## 기여 및 라이선스

변경 시 해당 스킬의 오프라인 테스트를 실행하고 동작 범위와 제한 사항을 문서에 반영합니다. 토큰·개인 환경 파일·실제 채팅 내보내기는 커밋하지 않습니다. 코드와 스킬 지침은 MIT 라이선스로 배포합니다. Discord 메시지·첨부의 권리는 이 코드의 라이선스와 별개입니다.
