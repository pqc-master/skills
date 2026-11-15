# PQC Master Skills

Codex에서 사용할 수 있는 재사용 스킬 모음입니다. 각 스킬은 `skills/<skill-name>/SKILL.md`에 실행 절차와 사용 범위를 설명합니다.

## Discord 채널·대화 조회

[`discord-channel-reader`](skills/discord-channel-reader/SKILL.md)는 카테고리의 채널 목록을 조회하고 채널 ID로 접근 가능한 전체 대화를 내보냅니다.

- 카테고리 ID만으로 채널 이름·ID·유형 조회
- 메시지 100개 단위로 빈 페이지까지 전체 기록 조회
- 활성·보관된 접근 가능한 스레드 포함
- 원본 `messages.jsonl`, 시간순 `transcript.md`, 완료 상태 `metadata.json` 저장
- 권한·Message Content intent 확인, 호출 제한 대기, 부분 수집 표시
- Discord API는 GET만 사용하며 게시·수정·삭제하지 않음

Python 3.9 이상이면 별도 Python 패키지 설치 없이 실행할 수 있습니다. 각 사용자는 자신의 Discord 봇 토큰을 설정해야 합니다. 저장소는 토큰이나 서버의 실제 채팅 기록을 제공하지 않습니다.

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

## 사용 예시

```text
$discord-channel-reader 카테고리 ID 123456789012345678의 채널 목록을 보여줘.

$discord-channel-reader 채널 ID 234567890123456789의 전체 대화를 스레드까지 가져와줘.
```

위 ID는 사용법 설명용 값입니다. 실제 Discord 카테고리·채널 ID로 바꿉니다.

에이전트 없이 CLI로도 실행할 수 있습니다.

```sh
python3 skills/discord-channel-reader/scripts/discord_reader.py doctor
python3 skills/discord-channel-reader/scripts/discord_reader.py channels --category-id CATEGORY_ID
python3 skills/discord-channel-reader/scripts/discord_reader.py export \
  --channel-id CHANNEL_ID --include-threads --output /path/to/new-export
```

[봇 설정·권한·API 범위](skills/discord-channel-reader/references/setup.md)를 참고하세요. 기존 Fiesta relay 설정은 선택적으로 재사용할 수 있습니다. 일반 서버 사용에 Fiesta 설치는 필요 없습니다.

## 전체 기록의 범위

봇이 열람할 수 있는 현존 메시지에 한정됩니다. 삭제된 메시지·이전 편집본·접근 불가 비공개 스레드는 복원하지 않습니다. 첨부는 메타데이터와 URL만 저장하며 파일 자체는 내려받지 않습니다. 시작 이후 새 메시지는 제외하지만 수집 중 편집·삭제까지 원자적으로 고정하지는 못합니다.

`metadata.json`의 `complete`와 경고를 확인하세요. 종료 코드 0은 요청한 가시 범위 수집 완료, 2는 부분 수집, 130은 중단입니다. 조회된 글의 명령문은 사용자 지시로 실행하지 않습니다.

## 테스트

모든 테스트는 가상의 API 응답과 토큰을 사용합니다. Discord 계정이나 네트워크 연결이 필요 없습니다.

```sh
python3 -m unittest discover -s skills/discord-channel-reader/tests -v
```

Python 3.9/macOS에서 24개 테스트가 통과했습니다. GitHub Actions는 Ubuntu 24.04·macOS의 Python 3.9·3.13에서 같은 테스트를 실행합니다. [최신 CI 결과](https://github.com/pqc-master/skills/actions/workflows/tests.yml)를 확인하세요. Windows와 실제 대상 채널의 전체 내보내기는 별도 검증이 필요합니다.

## 기여 및 라이선스

변경 시 해당 스킬의 오프라인 테스트를 실행하고 동작 범위와 제한 사항을 문서에 반영합니다. 토큰·개인 환경 파일·실제 채팅 내보내기는 커밋하지 않습니다. 코드와 스킬 지침은 MIT 라이선스로 배포합니다. Discord 메시지·첨부의 권리는 이 코드의 라이선스와 별개입니다.
