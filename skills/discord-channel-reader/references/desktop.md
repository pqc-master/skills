# 실행 파일로 설정하고 설치하기

macOS·Windows 배포본에는 Python 실행 환경과 설정 화면이 포함된다. 사용자 컴퓨터에 Python이나 Node.js를 따로 설치하지 않아도 된다.

## 다운로드와 실행

[다운로드 페이지](https://github.com/pqc-master/skills/releases/tag/desktop-v0.1.0)에서 다음 파일 중 하나를 받는다.

- **macOS · Apple Silicon:** `PQC-Discord-macos-arm64.zip`을 모두 풀고 `PQC Discord.app`을 연다.
- **Windows · x64:** `PQC-Discord-windows-x64.zip`을 모두 풀고 `PQC Discord/PQC Discord.exe`를 연다.

ZIP 안의 `pqc-discord` 폴더에는 스킬 실행기가 들어 있다. 앱과 이 폴더를 함께 보관하며 실행 파일 하나만 따로 옮기지 않는다. macOS 앱은 ad-hoc 서명되며 Apple 공증을 받지 않았고 Windows 앱은 코드 서명되지 않았다. 최초 실행 시 운영체제의 확인이 필요할 수 있다. 출처·체크섬을 확인할 수 있는 공식 배포본을 사용한다.

## 처음 설정

1. Discord에서 봇을 만들고 대상 서버에 초대한다. [봇 설정 안내](setup.md#봇-생성과-서버-초대)를 참고한다.
2. 설정 화면에 **봇 토큰**과 **표시 이름**을 입력한다. 토큰은 가려서 표시한다.
3. **저장하고 연결 확인**을 누른다. 토큰 인증이 성공하면 저장하고, 표시 이름도 로컬에 저장한다.
4. **Codex에 스킬 설치**를 누른다. 스킬과 실행 환경을 개인 스킬 폴더에 복사한다.
5. 새 Codex 대화에서 `$discord-channel-reader`를 사용한다.

이미 저장된 토큰은 입력란에 다시 표시하지 않는다. 빈칸으로 두면 기존 값을 유지한다. 표시 이름은 웹훅을 미리 만들지 않아도 저장할 수 있다. 설정 과정에서는 메시지나 파일을 게시하지 않는다.

**설정 화면에서 게시할 채널을 고르거나 웹훅 URL을 입력하지 않는다.** 현재 작업 중인 문제 채널은 제출 요청에서 정한다. 제출할 때 봇이 해당 채널의 자기 웹훅을 찾아 재사용하거나 생성하고, 게시물 상단에 `이름 · Codex`를 표시한다. 이를 위해 문제 채널에서 봇의 **웹훅 관리** 권한이 필요하다.

## 저장 위치와 갱신

설정은 사용자 홈 디렉터리의 `~/.config/discord-channel-reader/`에 저장한다. `.env`는 봇 토큰, `publisher.json`은 표시 이름이다. 이전 고급 웹훅 설정이 있다면 함께 보존한다. macOS 파일 권한은 소유자 전용이며 Windows에서는 사용자 프로필 안에 저장한다. 토큰과 설정 파일은 Git에 올리지 않는다.

스킬은 기본적으로 `~/.codex/skills/discord-channel-reader`에 설치한다. `CODEX_HOME`이 설정되어 있으면 그 아래 `skills/discord-channel-reader`를 사용한다. 실행 환경은 스킬 폴더의 `bin`에 포함된다. 알려진 이전 배포 파일만 갱신하고 직접 수정한 파일은 덮어쓰지 않는다. 수정 파일 충돌이 표시되면 해당 변경을 보관한 뒤 다시 설치한다.

환경변수의 봇 토큰은 파일보다 우선한다. 이 경우 화면에 출처를 표시하고 파일 토큰을 바꾸는 동작을 중단한다. 다른 프로그램의 환경변수를 앱이 임의로 변경하지 않는다.

## 실행 파일 명령

Codex는 설치된 실행기를 우선 사용한다. 아래 `<SKILL>`은 실제 스킬 설치 경로로 바꾼다. Windows는 실행기 이름 뒤에 `.exe`를 붙인다.

```sh
<SKILL>/bin/pqc-discord read channels
<SKILL>/bin/pqc-discord submit preview --channel-id CHANNEL_ID --source-zip solution.zip --report report.md
<SKILL>/bin/pqc-discord submit send --channel-id CHANNEL_ID --source-zip solution.zip --report report.md
```

`preview`는 네트워크에 접속하지 않는다. `send`는 지정한 채널의 웹훅을 준비하고 두 파일을 게시한다. 실제 메시지 링크가 반환되어야 제출 성공으로 판단한다. [상세 제출 절차](submitting.md)를 참고한다.

## 검증 범위

빌드는 macOS arm64·Windows x64에서 수행하고 압축 해제한 GUI 시작과 CLI 실행을 확인한다. CLI 자체 검사에는 실제 토큰이나 네트워크를 사용하지 않는다. GUI의 `--demo`는 가상 설정만 사용하며 실제 계정에 연결하지 않는다. 실제 Discord 제출은 **NOT TESTED**다. 실행 환경·소스 커밋·서명 상태는 배포 파일의 `build-info.json`을 확인한다.
