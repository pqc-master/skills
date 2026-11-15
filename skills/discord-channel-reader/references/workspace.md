# 문제 소스 ZIP 해제와 전체 프로젝트 패키징

실행 파일 설치에서는 `<SKILL>/bin/pqc-discord workspace`를 사용한다. Windows는 실행기에 `.exe`를 붙인다. 소스 설치에서는 `python3 <SKILL>/scripts/pqc_workspace.py`로 같은 하위 명령을 실행한다.

## 원본 확보

첨부 [다운로드](downloading.md) 결과의 SHA-256과 메시지·첨부 ID를 작업 기록에 남긴다. 원본은 보존하고 새 디렉터리에 압축을 푼다.

```sh
<SKILL>/bin/pqc-discord workspace extract --archive /ABSOLUTE/problem_source.zip --output /ABSOLUTE/NEW/original
```

`original.extraction.json`에 압축 파일 해시와 추출한 파일별 크기·해시·실행 비트를 기록한다. 상대 경로 이탈, 절대 경로, 링크·특수 파일, 암호화 ZIP, Windows 예약 이름, 대소문자·Unicode 충돌을 거부한다. 파일은 읽기·쓰기용으로 추출하며 macOS·Linux에서는 원래 실행 비트도 반영한다. Windows의 파일 권한은 POSIX 실행 비트와 같지 않으므로 원본 실행 비트는 manifest에서 확인하고 실행 대상 OS의 빌드·시험으로 검증한다. 추출 자체로 코드를 실행하지 않는다.

기본 한도는 항목 10,000개, 파일당 128 MiB, 전체 확장 크기 512 MiB다. 기존 출력 폴더와 manifest는 덮어쓰지 않는다. 손상·읽기 오류가 발생하면 부분 추출을 완료로 제시하지 않는다.

## 전체 프로젝트 ZIP

분석·전환·검증은 원본 사본에서 수행한다. 최종 변경을 고정하고 아래 명령으로 전체 프로젝트를 묶는다. 출력은 프로젝트 밖에 둔다.

```sh
<SKILL>/bin/pqc-discord workspace pack --project /ABSOLUTE/migrated-project --output /ABSOLUTE/artifacts/sourcecode.zip
```

프로젝트 루트 아래 경로를 ZIP 루트로 사용한다. 숨김 빌드 설정·의존성 고정 파일·필수 자산·빈 디렉터리를 보존한다. ZIP의 실행 비트는 패키징 환경의 파일 모드에서 가져오므로 Windows에서 Unix용 결과물을 만들 때는 실행 방법과 권한을 대상 OS에서 추가 확인한다. `build`, `dist`는 이름만으로 제외하지 않는다. 재현에 필요한 소스를 임의로 빼지 않는다.

기본 제외 대상은 VCS 디렉터리, 가상환경, `node_modules`, Python 캐시, 실제 `.env` 설정, `.npmrc`·`.pypirc`·`publisher.json` 등이다. `.env.example`·`.env.sample`·`.env.template`은 포함하므로 실제 비밀이 들어 있지 않은지 검토한다. PEM 비밀키 표식과 일부 키 저장소 확장자는 패키징을 중단시킨다. 이 필터는 모든 비밀을 탐지하지 않으므로 제출용 사본의 설정·시험 키·프롬프트·로그를 별도로 검토한다.

`sourcecode.zip.manifest.json`에는 `archive_sha256`, `archive_bytes`, `file_count`, `total_bytes`, `files`(경로·크기·SHA-256·실행 비트), `directories`, `excluded`(경로·이유)가 들어간다. 읽지 못한 디렉터리가 있으면 불완전한 ZIP을 만들지 않고 중단한다.

## 최종 파일로 재검증

1. 최종 ZIP을 새로운 디렉터리에 다시 푼다.
2. 제공한 빌드·설치 명령으로 빌드한다. 기존 작업 폴더의 생성물에 의존하지 않는다.
3. 필수 기능·보안 회귀 시험을 다시 실행하고 명령·환경·종료 코드·근거 경로를 남긴다.
4. 검증 후 코드를 수정했다면 새 ZIP·해시로 다시 시험한다. 최종 ZIP 해시와 검증 결과를 보고서에 연결한다.

ZIP 파일이 만들어졌다는 사실을 재빌드 성공으로 보고하지 않는다. 제출할 ZIP에는 코드·빌드/시험/벤치마크 스크립트·필요한 자산과 비밀 없는 근거를 포함한다. 보고서에는 ZIP 해시를 적으며, 그 보고서를 다시 ZIP에 넣어 자기 해시가 바뀌는 순환을 만들지 않는다.

Discord 제출 한도는 다운로드·압축 도구 한도와 다르다. 파일당 20 MiB·요청 전체 25 MiB를 넘으면 `submit`이 거부한다. 필요한 프로젝트 파일을 조용히 제외하거나 임의 채널·외부 서비스로 우회하지 않는다.
